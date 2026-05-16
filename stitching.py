"""
stitching.py — Monje Lab Stitcher
===================================
Row, column, and full-slice stitching using an incremental two-image approach.

Core idea
---------
The stitching problem is always reduced to joining exactly two images:

    stitch(A, B) → C
    stitch(C, D) → E
    stitch(E, F) → G  …

Registration is computed ONCE on the reference channel and the resulting
shifts are reused for every other channel.  This guarantees all channels
are aligned identically and avoids redundant PCC computation.

Workflow
--------
1. compute_shifts()          — runs PCC on ref_ch, returns a ShiftPlan
2. stitch_full_slice()       — applies a ShiftPlan to any channel
3. stitch_full_slice_naive() — same structure, no shifts (nominal only)
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Dict, Tuple

from io_utils import load_tile
from blending import stitch_pair
from registration import estimate_shift_horizontal, estimate_shift_vertical


# ─────────────────────────────────────────────
#  SHIFT PLAN
# ─────────────────────────────────────────────

@dataclass
class ShiftPlan:
    """
    All PCC-derived shifts for one Z slice, computed on the ref channel.

    h_shifts[(r, c)] = (dy, dx, effective_overlap_x)
        Shift for the join between column c-1 and column c inside row r.

    v_shifts[r] = (dy, dx, effective_overlap_y)
        Shift for the join between row r-1 and row r.
    """
    h_shifts: Dict[Tuple[int, int], Tuple[float, float, int]] = field(default_factory=dict)
    v_shifts: Dict[int, Tuple[float, float, int]]             = field(default_factory=dict)


def compute_shifts(tiles, z, ref_ch, n_rows, n_cols,
                   overlap_x, overlap_y,
                   fudge=10, upsample=10, max_shift=50):
    """
    Run PCC on ref_ch for every join and return a ShiftPlan.

    Horizontal shifts are estimated tile-to-tile (not on accumulated
    images) so they are purely geometric and channel-independent.

    Vertical shifts are estimated between accumulated ref-channel row
    images, which correctly captures row-to-row drift.

    Returns
    -------
    ShiftPlan
    """
    plan = ShiftPlan()

    print(f"\n  Computing shifts on ref_ch={ref_ch}, z={z} …")

    # ── Horizontal shifts ──────────────────────────────────────────
    print("\n  -- Horizontal passes --")
    for r in range(n_rows):
        for c in range(1, n_cols):
            path_a = tiles.get((r, c - 1, z, ref_ch))
            path_b = tiles.get((r, c,     z, ref_ch))
            if path_a is None or path_b is None:
                plan.h_shifts[(r, c)] = (0.0, 0.0, overlap_x)
                print(f"    ({r},{c-1})→({r},{c}): MISSING — using (0, 0)")
                continue

            img_a = load_tile(path_a)
            img_b = load_tile(path_b)
            dy, dx = estimate_shift_horizontal(
                img_a, img_b, overlap_x,
                fudge=fudge, upsample=upsample, max_shift=max_shift,
            )
            eff_ov = max(1, min(overlap_x - int(round(dx)),
                                img_a.shape[1], img_b.shape[1]))
            plan.h_shifts[(r, c)] = (dy, dx, eff_ov)

    # ── Build ref-channel row images for vertical shift estimation ──
    print("\n  -- Building ref rows for vertical shift estimation --")
    ref_rows = []
    for r in range(n_rows):
        row_img = _apply_row_shifts(tiles, z, ref_ch, r, n_cols,
                                    overlap_x, plan, blend="average")
        ref_rows.append(row_img)
        print(f"    Ref row {r} → {row_img.shape}")

    # ── Vertical shifts ────────────────────────────────────────────
    print("\n  -- Vertical passes --")
    canvas = ref_rows[0]
    for r in range(1, n_rows):
        incoming = ref_rows[r]
        dy, dx = estimate_shift_vertical(
            canvas, incoming, overlap_y,
            fudge=fudge, upsample=upsample, max_shift=max_shift,
        )
        eff_ov = max(1, min(overlap_y - int(round(dy)),
                            canvas.shape[0], incoming.shape[0]))
        plan.v_shifts[r] = (dy, dx, eff_ov)

        # Advance canvas so next vertical estimate is against the
        # growing accumulated image, not just adjacent row pairs
        canvas, incoming = _align_and_pad(canvas, incoming, dx, axis="v")
        canvas = stitch_pair(canvas, incoming, eff_ov, axis="v", blend="average")

    return plan


# ─────────────────────────────────────────────
#  INTERNAL HELPERS
# ─────────────────────────────────────────────

def _align_and_pad(accum, incoming, drift, axis):
    """
    Zero-pad both images to correct for perpendicular drift before blending.

    axis="h": drift is vertical (rows)  — pad top / bottom
    axis="v": drift is lateral (cols)   — pad left / right

    drift > 0 → incoming is further in the positive direction
    drift < 0 → incoming is further in the negative direction
    """
    if drift == 0:
        return accum, incoming

    abs_d = abs(int(round(drift)))
    if axis == "h":
        if drift > 0:
            accum    = np.pad(accum,    ((0, abs_d), (0, 0)), constant_values=0)
            incoming = np.pad(incoming, ((abs_d, 0), (0, 0)), constant_values=0)
        else:
            accum    = np.pad(accum,    ((abs_d, 0), (0, 0)), constant_values=0)
            incoming = np.pad(incoming, ((0, abs_d), (0, 0)), constant_values=0)
    else:
        if drift > 0:
            accum    = np.pad(accum,    ((0, 0), (0, abs_d)), constant_values=0)
            incoming = np.pad(incoming, ((0, 0), (abs_d, 0)), constant_values=0)
        else:
            accum    = np.pad(accum,    ((0, 0), (abs_d, 0)), constant_values=0)
            incoming = np.pad(incoming, ((0, 0), (0, abs_d)), constant_values=0)

    return accum, incoming


def _apply_row_shifts(tiles, z, ch, row_idx, n_cols,
                      overlap_x, plan, blend):
    """
    Stitch one row by applying pre-computed horizontal shifts from *plan*.
    Used for both ref-channel row building and all output channels.
    """
    path = tiles.get((row_idx, 0, z, ch))
    if path is None:
        raise ValueError(f"Missing tile ({row_idx}, 0, z={z}, ch={ch})")

    accum = load_tile(path)
    print(f"    Row {row_idx}: start with tile (r={row_idx}, c=0) → {accum.shape}")

    for c in range(1, n_cols):
        path_b = tiles.get((row_idx, c, z, ch))
        if path_b is None:
            print(f"    Warning: missing ({row_idx},{c}) — skipped")
            continue

        incoming = load_tile(path_b)
        dy, dx, eff_ov = plan.h_shifts.get((row_idx, c), (0.0, 0.0, overlap_x))

        accum, incoming = _align_and_pad(accum, incoming, dy, axis="h")
        print(f"    → joining tile c={c}  (overlap_eff={eff_ov}, dy={dy:+.2f})")
        accum = stitch_pair(accum, incoming, eff_ov, axis="h", blend=blend)

    print(f"    Row {row_idx} done → {accum.shape}")
    return accum


# ─────────────────────────────────────────────
#  FULL-SLICE STITCHING  (corrected)
# ─────────────────────────────────────────────

def stitch_full_slice(tiles, z, ch, n_rows, n_cols,
                      overlap_x, overlap_y,
                      plan, blend="average", ):
    """
    Stitch the complete 2-D slice for *ch* using shifts from *plan*.

    *plan* must be a ShiftPlan produced by compute_shifts() on the ref
    channel.  All channels receive identical transforms — no PCC is run
    here.

    Returns
    -------
    canvas : 2-D float32 ndarray
    """
    # ── Step 1: stitch each row ────────────────────────────────────
    print(f"\n  Building rows (CORRECTED) for ch={ch}, z={z} …")
    row_images = []
    for r in range(n_rows):
        print(f"\n    --- Row {r} ---")
        row_img = _apply_row_shifts(tiles, z, ch, r, n_cols,
                                    overlap_x, plan, blend)
        row_images.append(row_img)

    # ── Step 2: stack rows using pre-computed vertical shifts ──────
    print(f"\n  Stacking rows (CORRECTED) for ch={ch}, z={z} …")
    canvas = row_images[0]

    for r in range(1, n_rows):
        incoming = row_images[r]
        dy, dx, eff_ov = plan.v_shifts.get(r, (0.0, 0.0, overlap_y))
        print(f"\n    --- Joining row {r-1} + row {r} "
              f"(dy={dy:+.2f}, dx={dx:+.2f}, overlap_eff={eff_ov}) ---")

        canvas, incoming = _align_and_pad(canvas, incoming, dx, axis="v")
        canvas = stitch_pair(canvas, incoming, eff_ov, axis="v", blend=blend)

    return canvas


# ─────────────────────────────────────────────
#  NAIVE FULL-SLICE STITCHING  (no registration)
# ─────────────────────────────────────────────

def stitch_full_slice_naive(tiles, z, ch, n_rows, n_cols,
                             overlap_x, overlap_y, blend="average"):
    """
    Stitch the full slice using only nominal overlap — no PCC corrections.
    Useful as a before/after reference.
    """
    print(f"\n  Building rows (NAIVE) for ch={ch}, z={z} …")
    row_images = []
    for r in range(n_rows):
        print(f"\n    --- Row {r} ---")
        path = tiles.get((r, 0, z, ch))
        if path is None:
            raise ValueError(f"Missing tile ({r}, 0, z={z}, ch={ch})")
        accum = load_tile(path)
        print(f"    Row {r}: start with tile (r={r}, c=0) → {accum.shape}")
        for c in range(1, n_cols):
            path_b = tiles.get((r, c, z, ch))
            if path_b is None:
                print(f"    Warning: missing ({r},{c}) — skipped")
                continue
            incoming = load_tile(path_b)
            print(f"    → joining tile c={c}  (overlap_eff={overlap_x}, dy=+0.00)")
            accum = stitch_pair(accum, incoming, overlap_x, axis="h", blend=blend)
        print(f"    Row {r} done → {accum.shape}")
        row_images.append(accum)

    print(f"\n  Stacking rows (NAIVE) for ch={ch}, z={z} …")
    canvas = row_images[0]
    for r in range(1, n_rows):
        print(f"\n    --- Joining row {r-1} + row {r} ---")
        canvas = stitch_pair(canvas, row_images[r], overlap_y, axis="v", blend=blend)

    return canvas