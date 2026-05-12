"""
main.py — Monje Lab Stitcher  (entry point)
=============================================
Two modes only:

  test  — Inspect a single tile pair.  Produces three diagnostic outputs:
           <tag>_NAIVE.png, <tag>_CORRECTED.png, <tag>_STITCHED.tif
           Use --orientation horizontal|vertical to select the join axis.
           Use --row_idx / --col_idx to pick the tile pair.
           Use --z_slice to pin a specific Z (defaults to first available).

  real  — Full stitch of every channel.
           With --z_slice N : only that Z slice.
           Without --z_slice: every Z slice (full 3-D volume).
           Outputs go to:
             <output_dir>/<prefix>_registered/Channel_<ch>/   (corrected)
             <output_dir>/<prefix>_registered/Channel_<ch>_NAIVE/

Usage examples
--------------
  # Test horizontal pair at row 5, col 3, Z 0:
  python main.py --input_dir /data --overlap 10 --mode test \\
                 --row_idx 5 --col_idx 3 --orientation horizontal

  # Test vertical pair at row 2, col 1, Z 7:
  python main.py --input_dir /data --overlap 10 --mode test \\
                 --row_idx 2 --col_idx 1 --orientation vertical --z_slice 7

  # Full volume stitch:
  python main.py --input_dir /data --overlap 10 --mode real

  # Single Z slice stitch:
  python main.py --input_dir /data --overlap 10 --mode real --z_slice 5
"""

import os
import sys
import argparse

from io_utils import discover_tiles, grid_dims, load_tile, save_tiff
from registration import compute_positions, extract_corrections
from stitching import stitch_full_slice, stitch_full_slice_naive
from test_mode import run_test
from visualization import save_grid_overlay

# ─────────────────────────────────────────────
#  ARG PARSING
# ─────────────────────────────────────────────

def build_parser():
    p = argparse.ArgumentParser(
        description="Monje Lab tile stitcher — phase-correlation registration + sinusoidal blending",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--input_dir",  required=True,
                   help="Folder containing OME-TIFF tile files")
    p.add_argument("--output_dir", default=None,
                   help="Root output folder (defaults to input_dir)")
    p.add_argument("--overlap",    type=int, required=True,
                   help="Nominal tile overlap as %% of tile size (e.g. 10)")
    p.add_argument("--mode",       choices=["test", "real"], default="real",
                   help="'test': inspect one tile pair | 'real': full stitch")
    p.add_argument(
        "--visualize",
        action="store_true",
        help="Save grid-overlay PNGs during real mode",
    )

    # Registration parameters
    p.add_argument("--max_shift",  type=int, default=50,
                   help="Maximum plausible shift (px). "
                        "Detections exceeding this are zeroed (default: 50)")
    p.add_argument("--fudge",      type=int, default=10,
                   help="Search margin beyond the nominal overlap region (px, default: 10)")
    p.add_argument("--ref_channel", type=int, default=None,
                   help="Channel index used for registration (default: first channel found)")
    p.add_argument("--upsample",   type=int, default=10,
                   help="PCC upsample factor → sub-pixel accuracy = 1/upsample (default: 10)")

    # Tile/slice selection
    p.add_argument("--row_idx",    type=int, default=0,
                   help="Row index for test mode (default: 0)")
    p.add_argument("--col_idx",    type=int, default=0,
                   help="Column index for test mode (default: 0)")
    p.add_argument("--z_slice",    type=int, default=None,
                   help="Pin to a specific Z index. "
                        "In 'real' mode: omit to process all Z slices.")
    p.add_argument("--orientation", choices=["horizontal", "vertical"],
                   default="horizontal",
                   help="Test mode only: which join to inspect (default: horizontal)")
    return p


# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────

def main():
    args = build_parser().parse_args()

    root_out     = args.output_dir or args.input_dir
    frac         = args.overlap / 100.0

    # ── Discover tiles ──────────────────────────────────────────────
    tiles, zs, chs, prefix = discover_tiles(args.input_dir)
    ref_ch = args.ref_channel if args.ref_channel is not None else chs[0]

    # ── Resolve Z scope ─────────────────────────────────────────────
    if args.z_slice is not None:
        if args.z_slice not in zs:
            sys.exit(f"--z_slice {args.z_slice} not found. Available: {zs}")
        work_z  = args.z_slice
        work_zs = [args.z_slice]
    else:
        work_z  = zs[0]
        work_zs = zs

    # ── Sample tile dimensions ──────────────────────────────────────
    sample_path = next(
        (v for (r, c, z_, ch), v in tiles.items() if z_ == work_z and ch == ref_ch),
        None,
    )
    if sample_path is None:
        sys.exit(f"No tile found for ref_channel={ref_ch} at Z={work_z}.")

    sample = load_tile(sample_path)
    tile_h, tile_w = sample.shape
    ov_x = max(1, int(round(frac * tile_w)))
    ov_y = max(1, int(round(frac * tile_h)))

    # ── Print summary ───────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  Monje Lab — Image Registration & Stitching")
    print("=" * 60)
    print(f"  Mode        : {args.mode}")
    print(f"  Input dir   : {args.input_dir}")
    print(f"  All Z       : {zs}")
    if args.z_slice is not None:
        print(f"  Working Z   : {work_z}  (pinned)")
    elif args.mode == "real":
        print(f"  Working Z   : all {len(zs)} slices")
    else:
        print(f"  Working Z   : {work_z}  (first available)")
    print(f"  Channels    : {chs}  (ref={ref_ch})")
    print(f"  Overlap     : {args.overlap}% → x={ov_x} px, y={ov_y} px")
    print(f"  Tile size   : {tile_h}×{tile_w} px")
    print(f"  Max shift   : ±{args.max_shift} px (corrections beyond this → zeroed)")
    print(f"  Fudge       : +{args.fudge} px search margin")
    print(f"  Upsample    : {args.upsample}× → {1/args.upsample:.2f} px accuracy")
    if args.mode == "test":
        print(f"  Orientation : {args.orientation}")
        print(f"  Row / Col   : {args.row_idx} / {args.col_idx}")
    print()

    # ── Output directory ────────────────────────────────────────────
    out_dir = os.path.join(root_out, (prefix or "output") + "_registered")
    os.makedirs(out_dir, exist_ok=True)

    viz_dir = None

    if args.visualize:
        viz_dir = os.path.join(out_dir, "grid_overlays")
        os.makedirs(viz_dir, exist_ok=True)

    # ── TEST MODE ───────────────────────────────────────────────────
    if args.mode == "test":
        run_test(
            tiles    = tiles,
            z        = work_z,
            ref_ch   = ref_ch,
            overlap_x = ov_x,
            overlap_y = ov_y,
            tile_h   = tile_h,
            tile_w   = tile_w,
            fudge    = args.fudge,
            upsample = args.upsample,
            max_shift = args.max_shift,
            out_dir  = out_dir,
            row_idx  = args.row_idx,
            col_idx  = args.col_idx,
            orientation = args.orientation,
        )
        return

    # ── REAL MODE ───────────────────────────────────────────────────
    # Create per-channel output folders
    ch_dirs       = {}
    ch_dirs_naive = {}
    for ch in chs:
        d = os.path.join(out_dir, f"Channel_{ch:02d}")
        os.makedirs(d, exist_ok=True)
        ch_dirs[ch] = d

        d_naive = os.path.join(out_dir, f"Channel_{ch:02d}_NAIVE")
        os.makedirs(d_naive, exist_ok=True)
        ch_dirs_naive[ch] = d_naive

    for z in work_zs:
        print(f"\n{'='*60}")
        print(f"  Z = {z:04d}")
        print(f"{'='*60}")

        keys = [(r, c) for (r, c, z_, ch) in tiles if z_ == z]
        if not keys:
            print("  No tiles for this Z — skipping.")
            continue

        n_rows, n_cols = grid_dims(tiles, z)
        print(f"  Grid: {n_rows} rows × {n_cols} cols")

        # Recompute overlap in px from a live tile at this Z (handles Z-varying dims)
        sp = next(v for (r, c, z_, ch), v in tiles.items() if z_ == z and ch == ref_ch)
        th, tw = load_tile(sp).shape
        ov_x_z = max(1, int(round(frac * tw)))
        ov_y_z = max(1, int(round(frac * th)))

        # Solve registration
        pos = compute_positions(
            tiles, z, n_rows, n_cols,
            ov_x_z, ov_y_z, th, tw,
            args.max_shift, args.fudge, ref_ch, args.upsample,
        )
        dy_per_col, dx_per_row_col = extract_corrections(
            pos, th, tw, ov_x_z, ov_y_z,
        )

        if args.visualize:
            save_grid_overlay(
                pos,
                th,
                tw,
                n_rows,
                n_cols,
                z,
                os.path.join(viz_dir, f"grid_z{z:04d}.png"),
            )

        for ch in chs:
            # NAIVE
            print(f"\n  Channel {ch} — NAIVE …")
            img_naive = stitch_full_slice_naive(
                tiles, z, ch, n_rows, n_cols, ov_x_z, ov_y_z,
            )
            save_tiff(img_naive,
                      os.path.join(ch_dirs_naive[ch],
                                   f"stitched_z{z:04d}_C{ch:02d}_NAIVE.tif"))

            # CORRECTED
            print(f"\n  Channel {ch} — CORRECTED …")
            img_corr = stitch_full_slice(
                tiles, z, ch, n_rows, n_cols, ov_x_z, ov_y_z,
                dy_per_col=dy_per_col,
                dx_per_row_col=dx_per_row_col,
            )
            save_tiff(img_corr,
                      os.path.join(ch_dirs[ch],
                                   f"stitched_z{z:04d}_C{ch:02d}_CORRECTED.tif"))

    print("\nAll done!")


if __name__ == "__main__":
    main()
