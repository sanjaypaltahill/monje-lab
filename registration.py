"""
registration.py — Monje Lab Stitcher
======================================
Phase-cross-correlation shift estimation, canvas-position solving,
and extraction of per-join corrections for the stitcher.

Key design decisions
---------------------
* Both ref and moving strips are taken at exactly *overlap_px* in the
  search dimension — equal sizes, no zero-padding.  Zero-padding one
  strip to match the other introduces a large artificial DC component
  that can dominate the cross-correlation and produce a bogus shift=0.

* fudge is not used in the PCC strip logic.  It remains as a parameter
  so callers don't break, but the correct search range is bounded by
  overlap_px itself.  Shifts larger than overlap_px/2 would indicate a
  wrong overlap estimate, which max_shift catches.

* normalization=None is used throughout (not "phase") to avoid the
  division-by-spectrum-magnitude step that amplifies noise in
  near-blank regions.

* max_shift is enforced: if |detected shift| exceeds max_shift the
  correction is zeroed and a warning is printed, preventing runaway
  accumulation from a bad PCC result.
"""

import warnings
import numpy as np
from skimage.registration import phase_cross_correlation
from skimage.transform import AffineTransform, warp
from io_utils import load_tile

# ─────────────────────────────────────────────
#  SHIFT ESTIMATION
# ─────────────────────────────────────────────

def _pcc(ref, moving, upsample):
    """
    Run phase_cross_correlation(ref, moving) with normalization=None.

    ref and moving must have identical shapes.
    Returns (dy, dx, error).
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        shift, error, _ = phase_cross_correlation(
            ref, moving,
            upsample_factor=upsample,
            normalization=None,
        )
    return float(shift[0]), float(shift[1]), float(error)


def estimate_shift_horizontal(img_a, img_b, overlap_px,
                               fudge=10, upsample=10, max_shift=50):
    """
    Estimate (dy, dx) to align tile B left-edge with tile A right-edge.

    ref    = rightmost overlap_px columns of tile A
    moving = leftmost  overlap_px columns of tile B

    Both strips are exactly the same size — no zero-padding — so PCC
    operates on content-only arrays without artificial DC boundaries.
    fudge is accepted for API compatibility but not used in strip sizing.

    Returns dy, dx — shift to apply to tile B to align with tile A.
    Positive dy: tile B sits lower than expected.
    Positive dx: tile B sits further right than expected.
    """
    h_a, w_a = img_a.shape
    h_b, w_b = img_b.shape

    cols = min(overlap_px, w_a, w_b)
    rows = min(h_a, h_b)

    ref_strip    = img_a[:rows, -cols:]   # right edge of A
    moving_strip = img_b[:rows, :cols]    # left  edge of B

    if ref_strip.std() < 1e-3 or moving_strip.std() < 1e-3:
        print("    Warning: blank strip — using (dy=0, dx=0).")
        return 0.0, 0.0

    dy, dx, error = _pcc(ref_strip, moving_strip, upsample)
    print(f"    PCC horizontal: dy={dy:+.2f}, dx={dx:+.2f}, error={error:.4f}")

    dy, dx = _clamp_shift(dy, dx, max_shift, "horizontal")
    return dy, dx


def estimate_shift_vertical(img_a, img_b, overlap_px,
                              fudge=10, upsample=10, max_shift=50):
    """
    Estimate (dy, dx) to align tile B top-edge with tile A bottom-edge.

    ref    = bottom overlap_px rows of tile A
    moving = top    overlap_px rows of tile B

    Both strips are exactly the same size — no zero-padding — so PCC
    operates on content-only arrays without artificial DC boundaries.
    fudge is accepted for API compatibility but not used in strip sizing.

    Returns dy, dx — shift to apply to tile B to align with tile A.
    Positive dy: tile B sits lower than expected.
    Positive dx: tile B drifts right of expected.
    """
    h_a, w_a = img_a.shape
    h_b, w_b = img_b.shape

    rows = min(overlap_px, h_a, h_b)
    cols = min(w_a, w_b)

    ref_strip    = img_a[-rows:, :cols]   # bottom edge of A
    moving_strip = img_b[:rows,  :cols]   # top    edge of B

    if ref_strip.std() < 1e-3 or moving_strip.std() < 1e-3:
        print("    Warning: blank strip — using (dy=0, dx=0).")
        return 0.0, 0.0

    dy, dx, error = _pcc(ref_strip, moving_strip, upsample)
    print(f"    PCC vertical:   dy={dy:+.2f}, dx={dx:+.2f}, error={error:.4f}")

    dy, dx = _clamp_shift(dy, dx, max_shift, "vertical")
    return dy, dx


def _clamp_shift(dy, dx, max_shift, label):
    """
    If either component exceeds max_shift, zero-out *both* components and warn.

    Zeroing both (rather than clamping each independently) avoids introducing
    a partial correction that can be worse than no correction.
    """
    if abs(dy) > max_shift or abs(dx) > max_shift:
        print(
            f"    WARNING [{label}]: shift (dy={dy:+.1f}, dx={dx:+.1f}) "
            f"exceeds max_shift={max_shift} — correction set to (0, 0)."
        )
        return 0.0, 0.0
    return dy, dx


# ─────────────────────────────────────────────
#  WARP
# ─────────────────────────────────────────────

def apply_shift_skimage(img, dy, dx, output_shape):
    """
    Pure-translation warp via skimage AffineTransform.

    skimage convention: translation=(x_shift, y_shift) = (dx, dy).
    """
    tform = AffineTransform(translation=(dx, dy))
    warped = warp(
        img,
        inverse_map=tform.inverse,
        output_shape=output_shape,
        order=1,
        mode="constant",
        cval=0.0,
        preserve_range=True,
    )
    return warped.astype(np.float32)


# ─────────────────────────────────────────────
#  GRID POSITION SOLVER
# ─────────────────────────────────────────────

def compute_positions(tiles, z, n_rows, n_cols,
                      overlap_x, overlap_y,
                      tile_h, tile_w,
                      max_shift, fudge, ref_ch, upsample):
    """
    Walk the grid left→right then top→bottom, accumulating absolute
    canvas (y, x) positions for every tile.

    Horizontal pass: estimates dy (vertical drift) and dx (horizontal
    placement) for each left→right join and accumulates into pos.

    Vertical pass: estimates dy (vertical placement) and dx (lateral
    drift) for each top→bottom join.  The vertical pass overwrites the
    y-component only, preserving the x position from the horizontal pass
    (column 0 x-positions come from the vertical pass directly).

    Returns pos : ndarray shape (n_rows, n_cols, 2) — [y, x] in pixels.
    """
    pos = np.zeros((n_rows, n_cols, 2), dtype=np.float64)

    # ── Horizontal pass ────────────────────────────────────────────
    print("\n  -- Horizontal passes (left → right) --")
    for r in range(n_rows):
        for c in range(1, n_cols):
            path_a = tiles.get((r, c - 1, z, ref_ch))
            path_b = tiles.get((r, c,     z, ref_ch))

            nominal_dx = tile_w - overlap_x

            if path_a is None or path_b is None:
                pos[r, c] = pos[r, c - 1] + [0, nominal_dx]
                print(f"    ({r},{c-1})→({r},{c}): MISSING tile — nominal")
                continue

            img_a = load_tile(path_a)
            img_b = load_tile(path_b)

            dy, dx = estimate_shift_horizontal(
                img_a, img_b, overlap_x,
                fudge=fudge, upsample=upsample, max_shift=max_shift,
            )

            pos[r, c, 0] = pos[r, c - 1, 0] + dy          # vertical drift
            pos[r, c, 1] = pos[r, c - 1, 1] + nominal_dx + dx

            _print_join(f"({r},{c-1})→({r},{c})", "H",
                        dy, nominal_dx + dx, 0, nominal_dx,
                        pos[r, c, 0], pos[r, c, 1])

    # ── Vertical pass ──────────────────────────────────────────────
    print("\n  -- Vertical passes (top → bottom) --")
    for c in range(n_cols):
        for r in range(1, n_rows):
            path_a = tiles.get((r - 1, c, z, ref_ch))
            path_b = tiles.get((r,     c, z, ref_ch))

            nominal_dy = tile_h - overlap_y

            if path_a is None or path_b is None:
                pos[r, c, 0] = pos[r - 1, c, 0] + nominal_dy
                print(f"    ({r-1},{c})→({r},{c}): MISSING tile — nominal")
                continue

            img_a = load_tile(path_a)
            img_b = load_tile(path_b)

            dy, dx = estimate_shift_vertical(
                img_a, img_b, overlap_y,
                fudge=fudge, upsample=upsample, max_shift=max_shift,
            )

            # Vertical pass owns the y component; x drift is additive
            pos[r, c, 0] = pos[r - 1, c, 0] + nominal_dy + dy
            pos[r, c, 1] = pos[r - 1, c, 1] + dx          # lateral drift

            _print_join(f"({r-1},{c})→({r},{c})", "V",
                        nominal_dy + dy, dx, nominal_dy, 0,
                        pos[r, c, 0], pos[r, c, 1])

    _print_position_table(pos, n_rows, n_cols)
    return pos


def _print_join(label, direction, actual_dy, actual_dx,
                nominal_dy, nominal_dx, canvas_y, canvas_x):
    corr_dy = actual_dy - nominal_dy
    corr_dx = actual_dx - nominal_dx
    print(f"    {label} [{direction}]  "
          f"nominal=({nominal_dy:+d},{nominal_dx:+d})  "
          f"corr=({corr_dy:+.1f},{corr_dx:+.1f})  "
          f"canvas=({canvas_y:.1f},{canvas_x:.1f})")


def _print_position_table(pos, n_rows, n_cols):
    print("\n  == Solved canvas positions ==")
    print(f"  {'Tile':>10}   {'y (px)':>10}   {'x (px)':>10}")
    for r in range(n_rows):
        for c in range(n_cols):
            print(f"  ({r:02d},{c:02d})     "
                  f"{pos[r,c,0]:>10.1f}   {pos[r,c,1]:>10.1f}")


# ─────────────────────────────────────────────
#  CORRECTION EXTRACTION
# ─────────────────────────────────────────────

def extract_corrections(pos, tile_h, tile_w, overlap_x, overlap_y):
    """
    Convert canvas positions into integer per-join correction dicts.

    Returns
    -------
    dy_per_col     : {(row, col): int}
        Vertical drift (dy) for the horizontal join between col-1 and col
        in the given row.  Applied as top/bottom padding when stitching
        a row from left to right.

    dx_per_row_col : {(row, col): int}
        Lateral drift (dx) for the vertical join between row-1 and row
        in the given column.  Applied as left/right padding when stacking
        row images vertically.
    """
    n_rows, n_cols = pos.shape[:2]
    dy_per_col     = {}
    dx_per_row_col = {}

    for r in range(n_rows):
        for c in range(1, n_cols):
            nominal_dx = tile_w - overlap_x
            actual_dy  = pos[r, c, 0] - pos[r, c - 1, 0]
            dy_per_col[(r, c)] = int(round(actual_dy))   # drift from horizontal join

    for c in range(n_cols):
        for r in range(1, n_rows):
            actual_dx = pos[r, c, 1] - pos[r - 1, c, 1]
            dx_per_row_col[(r, c)] = int(round(actual_dx))  # lateral drift from vertical join

    return dy_per_col, dx_per_row_col