"""
test_mode.py — Monje Lab Stitcher
===================================
Test-mode diagnostics for a single tile pair.

Produces three outputs per run:
  1. <tag>_NAIVE.png      — red/green/yellow overlay without any correction
  2. <tag>_CORRECTED.png  — red/green/yellow overlay with PCC correction applied
  3. <tag>_STITCHED.tif   — sinusoidal-blended stitch of the pair

Each PNG shows:
  • Left panel  : false-colour composite (red = tile A, green = tile B)
  • Middle panel: difference map (zero = perfect alignment)
  • Right panel : zoomed crop centred on the seam
"""

import os
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

from io_utils import load_tile, save_tiff
from registration import (
    estimate_shift_horizontal,
    estimate_shift_vertical,
    apply_shift_skimage,
)
from blending import stitch_pair_horizontal, stitch_pair_vertical


# ─────────────────────────────────────────────
#  OVERLAY HELPER
# ─────────────────────────────────────────────

def save_rg_overlay(img_fixed, img_moving, out_path,
                    title="Alignment check", zoom_region=None):
    """
    Save a three-panel diagnostic PNG.

    Panels
    ------
    0 : False-colour composite  (red=fixed, green=moving, yellow=overlap)
    1 : Signed difference map   (blue=fixed brighter, red=moving brighter)
    2 : Zoomed crop of the seam region  (only when zoom_region is provided)

    Parameters
    ----------
    zoom_region : (y0, y1, x0, x1) in canvas pixel coordinates, or None.
    """
    def _norm_u8(arr):
        lo, hi = arr.min(), arr.max()
        if hi > lo:
            return ((arr - lo) / (hi - lo) * 255).astype(np.uint8)
        return np.zeros_like(arr, dtype=np.uint8)

    r_ch = _norm_u8(img_fixed)
    g_ch = _norm_u8(img_moving)
    b_ch = np.zeros_like(r_ch)
    rgb  = np.stack([r_ch, g_ch, b_ch], axis=-1)

    n_panels = 3 if zoom_region is not None else 2
    fig, axes = plt.subplots(1, n_panels,
                             figsize=(7 * n_panels, 6),
                             facecolor="#111")
    fig.suptitle(title, color="white", fontsize=13, y=1.01)

    # Panel 0 — composite
    axes[0].imshow(rgb)
    axes[0].set_title("Red=fixed | Green=moving | Yellow=overlap",
                      color="white", fontsize=9)
    axes[0].axis("off")

    if zoom_region is not None:
        y0, y1, x0, x1 = zoom_region
        rect = Rectangle((x0, y0), x1 - x0, y1 - y0,
                         linewidth=2, edgecolor="cyan", facecolor="none")
        axes[0].add_patch(rect)

    # Panel 1 — difference
    diff = img_fixed.astype(np.float32) - img_moving.astype(np.float32)
    vmax = np.percentile(np.abs(diff), 99) or 1.0
    axes[1].imshow(diff, cmap="RdBu_r", vmin=-vmax, vmax=vmax)
    axes[1].set_title("Difference map  (zero = perfect overlap)",
                      color="white", fontsize=9)
    axes[1].axis("off")

    if zoom_region is not None:
        y0, y1, x0, x1 = zoom_region
        rect = Rectangle((x0, y0), x1 - x0, y1 - y0,
                         linewidth=2, edgecolor="cyan", facecolor="none")
        axes[1].add_patch(rect)

        # Panel 2 — zoomed composite
        axes[2].imshow(rgb[y0:y1, x0:x1])
        axes[2].set_title(f"Zoom: seam region  ({x1-x0}×{y1-y0} px)",
                          color="white", fontsize=9)
        axes[2].axis("off")

    plt.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight", facecolor="#111")
    plt.close(fig)
    print(f"  Overlay saved: {out_path}")


# ─────────────────────────────────────────────
#  HORIZONTAL TEST
# ─────────────────────────────────────────────

def _test_horizontal(tiles, z, ref_ch,
                     overlap_x, tile_h, tile_w,
                     fudge, upsample, max_shift,
                     out_dir, row_idx, col_idx):

    tag = f"H_r{row_idx}_c{col_idx}-{col_idx+1}_z{z:04d}"
    print(f"\n  TEST — HORIZONTAL  row={row_idx}, cols {col_idx}↔{col_idx+1}, Z={z}")

    path_a = tiles.get((row_idx, col_idx,     z, ref_ch))
    path_b = tiles.get((row_idx, col_idx + 1, z, ref_ch))
    if path_a is None or path_b is None:
        print("  Error: one or both test tiles are missing.")
        return

    img_a = load_tile(path_a)
    img_b = load_tile(path_b)
    print(f"  Tile A: {os.path.basename(path_a)}  {img_a.shape}")
    print(f"  Tile B: {os.path.basename(path_b)}  {img_b.shape}")

    dy, dx = estimate_shift_horizontal(
        img_a, img_b, overlap_x,
        fudge=fudge, upsample=upsample, max_shift=max_shift,
    )
    nominal_dx = tile_w - overlap_x
    print(f"  Nominal dx={nominal_dx}  PCC correction: dy={dy:+.2f}, dx={dx:+.2f}")

    # ── Canvas size ────────────────────────────────────────────────
    canvas_h = tile_h + abs(int(dy)) + 20
    canvas_w = tile_w + nominal_dx + abs(int(dx)) + 20

    # ── Zoom region (centred on the seam) ─────────────────────────
    zm = 300
    zoom = (
        max(0, canvas_h // 2 - zm), min(canvas_h, canvas_h // 2 + zm),
        max(0, tile_w - zm),        min(canvas_w, tile_w + zm),
    )

    # ── NAIVE overlay ─────────────────────────────────────────────
    ca = np.zeros((canvas_h, canvas_w), np.float32)
    cb = np.zeros((canvas_h, canvas_w), np.float32)
    ca[:tile_h, :tile_w] = img_a
    x1 = min(nominal_dx + tile_w, canvas_w)
    cb[:tile_h, nominal_dx:x1] = img_b[:, :x1 - nominal_dx]
    save_rg_overlay(ca, cb,
                    os.path.join(out_dir, f"test_{tag}_NAIVE.png"),
                    title="NAIVE horizontal placement", zoom_region=zoom)

    # ── CORRECTED overlay ─────────────────────────────────────────
    ca2 = np.zeros((canvas_h, canvas_w), np.float32)
    ca2[:tile_h, :tile_w] = img_a
    cb2 = apply_shift_skimage(img_b, dy, nominal_dx + dx, (canvas_h, canvas_w))
    save_rg_overlay(ca2, cb2,
                    os.path.join(out_dir, f"test_{tag}_CORRECTED.png"),
                    title="CORRECTED horizontal placement", zoom_region=zoom)

    # ── Stitched TIFF ──────────────────────────────────────────────
    stitched = stitch_pair_horizontal(img_a, img_b, overlap_x)
    save_tiff(stitched, os.path.join(out_dir, f"test_{tag}_STITCHED.tif"))
    print(f"\n  Outputs written to: {out_dir}")


# ─────────────────────────────────────────────
#  VERTICAL TEST
# ─────────────────────────────────────────────

def _test_vertical(tiles, z, ref_ch,
                   overlap_y, tile_h, tile_w,
                   fudge, upsample, max_shift,
                   out_dir, row_idx, col_idx):

    tag = f"V_c{col_idx}_r{row_idx}-{row_idx+1}_z{z:04d}"
    print(f"\n  TEST — VERTICAL  col={col_idx}, rows {row_idx}↔{row_idx+1}, Z={z}")

    path_a = tiles.get((row_idx,     col_idx, z, ref_ch))
    path_b = tiles.get((row_idx + 1, col_idx, z, ref_ch))
    if path_a is None or path_b is None:
        print("  Error: one or both test tiles are missing.")
        return

    img_a = load_tile(path_a)
    img_b = load_tile(path_b)
    print(f"  Tile A: {os.path.basename(path_a)}  {img_a.shape}")
    print(f"  Tile B: {os.path.basename(path_b)}  {img_b.shape}")

    dy, dx = estimate_shift_vertical(
        img_a, img_b, overlap_y,
        fudge=fudge, upsample=upsample, max_shift=max_shift,
    )
    nominal_dy = tile_h - overlap_y
    print(f"  Nominal dy={nominal_dy}  PCC correction: dy={dy:+.2f}, dx={dx:+.2f}")

    # ── Canvas size ────────────────────────────────────────────────
    canvas_h = tile_h + nominal_dy + abs(int(dy)) + 20
    canvas_w = tile_w + abs(int(dx)) + 20

    # ── Zoom region (centred on the seam) ─────────────────────────
    zm = 300
    zoom = (
        max(0, tile_h - zm), min(canvas_h, tile_h + zm),
        max(0, canvas_w // 2 - zm), min(canvas_w, canvas_w // 2 + zm),
    )

    # ── NAIVE overlay ─────────────────────────────────────────────
    ca = np.zeros((canvas_h, canvas_w), np.float32)
    cb = np.zeros((canvas_h, canvas_w), np.float32)
    ca[:tile_h, :tile_w] = img_a
    y1 = min(nominal_dy + tile_h, canvas_h)
    cb[nominal_dy:y1, :tile_w] = img_b[:y1 - nominal_dy, :]
    save_rg_overlay(ca, cb,
                    os.path.join(out_dir, f"test_{tag}_NAIVE.png"),
                    title="NAIVE vertical placement", zoom_region=zoom)

    # ── CORRECTED overlay ─────────────────────────────────────────
    ca2 = np.zeros((canvas_h, canvas_w), np.float32)
    ca2[:tile_h, :tile_w] = img_a
    cb2 = apply_shift_skimage(img_b, nominal_dy + dy, dx, (canvas_h, canvas_w))
    save_rg_overlay(ca2, cb2,
                    os.path.join(out_dir, f"test_{tag}_CORRECTED.png"),
                    title="CORRECTED vertical placement", zoom_region=zoom)

    # ── Stitched TIFF ──────────────────────────────────────────────
    stitched = stitch_pair_vertical(img_a, img_b, overlap_y)
    save_tiff(stitched, os.path.join(out_dir, f"test_{tag}_STITCHED.tif"))
    print(f"\n  Outputs written to: {out_dir}")


# ─────────────────────────────────────────────
#  PUBLIC ENTRY POINT
# ─────────────────────────────────────────────

def run_test(tiles, z, ref_ch,
             overlap_x, overlap_y,
             tile_h, tile_w,
             fudge, upsample, max_shift,
             out_dir,
             row_idx=0, col_idx=0,
             orientation="horizontal"):
    """
    Dispatch to the horizontal or vertical test helper.

    Called by main.py when --mode test is active.
    """
    print("\n" + "=" * 60)
    if orientation == "horizontal":
        _test_horizontal(tiles, z, ref_ch,
                         overlap_x, tile_h, tile_w,
                         fudge, upsample, max_shift,
                         out_dir, row_idx, col_idx)
    else:
        _test_vertical(tiles, z, ref_ch,
                       overlap_y, tile_h, tile_w,
                       fudge, upsample, max_shift,
                       out_dir, row_idx, col_idx)
    print("=" * 60)
    print("\nTest done. Review the PNGs, then re-run with --mode real.")
