"""
3D Image Stitching Script — Monje Lab
======================================
Loops over all Z slices, calls 2D_stitching.py's core logic for each
plane, then stacks the results into a single 3D OME-TIFF.

REQUIRES: 2D_stitching.py must be in the same folder as this script.

USAGE:
  python 3D_stitching.py
"""

# =============================================================================
# CONFIGURATION
# =============================================================================

# All Z slices to stitch (will become the Z axis of the output stack)
Z_SLICES = [100, 101, 102]

# Output file — saved as a 3D OME-TIFF (Z, H, W)
OUTPUT_PATH = "/Users/spaltahill/Monje Lab/stitched_3d_output.tif"

# All other settings (INPUT_DIR, N_ROWS, N_COLS, CHANNEL, OVERLAP_FRACTION,
# FILENAME_PREFIX) are read directly from 2D_stitching.py — edit them there.

# =============================================================================
# END OF CONFIGURATION
# =============================================================================

import sys
import os
import importlib
import numpy as np

try:
    import tifffile as tf
except ImportError:
    sys.exit("tifffile is required: pip install tifffile")

# ---------------------------------------------------------------------------
# Import the 2D script as a module.
# Both scripts must live in the same directory.
# ---------------------------------------------------------------------------
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

try:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "stitch_2d", os.path.join(script_dir, "2D_stitching.py")
    )
    stitch_2d = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(stitch_2d)
except FileNotFoundError:
    sys.exit("ERROR: 2D_stitching.py not found. Make sure it's in the same folder as this script.")


def stitch_plane(z: int, overlap_x: int, overlap_y: int) -> np.ndarray:
    """Stitch one Z plane by calling 2D_stitching's core functions."""
    row_images = []
    for r in range(stitch_2d.N_ROWS):
        row_img = stitch_2d.load_tile(r, 0, z) if _load_takes_z() else _load_tile_at_z(r, 0, z)
        for c in range(1, stitch_2d.N_COLS):
            tile = stitch_2d.load_tile(r, c, z) if _load_takes_z() else _load_tile_at_z(r, c, z)
            row_img = stitch_2d.stitch_horizontal(row_img, tile, overlap_x)
        row_images.append(row_img)

    plane = row_images[0]
    for r in range(1, stitch_2d.N_ROWS):
        plane = stitch_2d.stitch_vertical(plane, row_images[r], overlap_y)
    return plane


def _load_takes_z() -> bool:
    """Check whether 2D_stitching.load_tile accepts a z argument."""
    import inspect
    sig = inspect.signature(stitch_2d.load_tile)
    return 'z' in sig.parameters


def _load_tile_at_z(row: int, col: int, z: int) -> np.ndarray:
    """
    Fallback: temporarily patch Z_SLICE in the 2D module so load_tile
    picks up the right slice, then restore it.
    """
    original = stitch_2d.Z_SLICE
    stitch_2d.Z_SLICE = z
    arr = stitch_2d.load_tile(row, col)
    stitch_2d.Z_SLICE = original
    return arr


def main():
    print(f"Z slices  : {Z_SLICES}  ({len(Z_SLICES)} planes)")
    print(f"Output    : {OUTPUT_PATH}")
    print(f"(Grid, overlap, channel etc. come from 2D_stitching.py)")
    print()

    # Compute overlap in pixels from a sample tile
    sample = _load_tile_at_z(0, 0, Z_SLICES[0])
    tile_h, tile_w = sample.shape[:2]
    overlap_y = max(1, int(round(stitch_2d.OVERLAP_FRACTION * tile_h)))
    overlap_x = max(1, int(round(stitch_2d.OVERLAP_FRACTION * tile_w)))
    print(f"Tile size : {tile_w} x {tile_h} px")
    print(f"Overlap   : {overlap_x} px (X),  {overlap_y} px (Y)")
    print()

    # Stitch each Z plane
    planes = []
    for i, z in enumerate(Z_SLICES):
        print(f"Stitching Z={z}  ({i+1}/{len(Z_SLICES)}) ...", end="  ", flush=True)
        plane = stitch_plane(z, overlap_x, overlap_y)
        planes.append(plane)
        print(f"-> {plane.shape[1]} x {plane.shape[0]} px")

    # Stack into 3D (Z, H, W) and normalise to uint16
    stack = np.stack(planes, axis=0)
    vmin, vmax = stack.min(), stack.max()
    if vmax > vmin:
        stack_out = ((stack - vmin) / (vmax - vmin) * 65535).astype(np.uint16)
    else:
        stack_out = np.zeros_like(stack, dtype=np.uint16)

    # Save as 3D OME-TIFF (opens as Z-stack in Fiji/ImageJ automatically)
    tf.imwrite(
        OUTPUT_PATH,
        stack_out,
        photometric='minisblack',
        imagej=True,
        metadata={'axes': 'ZYX'}
    )

    print(f"\nSaved: {OUTPUT_PATH}")
    print(f"  Shape : Z={stack_out.shape[0]},  {stack_out.shape[2]} x {stack_out.shape[1]} px")
    print(f"  Dtype : {stack_out.dtype}")


if __name__ == "__main__":
    main()