"""
2D Image Stitching Script — Monje Lab
======================================
Reads a grid of overlapping OME-TIFF tiles at a single Z slice,
then stitches into a single 2D output image with feathered blending
in the overlap zones.

USAGE:
  python stitch_2d.py

Edit the CONFIGURATION section below before running.
"""

# =============================================================================
# CONFIGURATION
# =============================================================================

INPUT_DIR = "/Users/spaltahill/Monje Lab"   # folder containing the tiles

# Grid dimensions (from filename pattern [row x col])
N_ROWS = 4   # rows 00–03
N_COLS = 3   # cols 00–02

# Which Z slice to stitch (z0100, z0101, or z0102 → use 100, 101, or 102)
Z_SLICE = 100

# Channel to stitch (C00 = 0)
CHANNEL = 0

# Overlap fraction (20ol in filename = 20%)
OVERLAP_FRACTION = 0.20

# Output file
OUTPUT_PATH = "/Users/spaltahill/Monje Lab/stitched_output.tif"

# Filename prefix — shouldn't need to change this
FILENAME_PREFIX = "260128_UltraII_5300148-2R_AF_HNACy3_cfos_2x_thickness3d5_width60_20ol_10umstep"

# =============================================================================
# END OF CONFIGURATION
# =============================================================================

import sys
import os
import numpy as np

# Import Image from Pillow (Python imaging library)
try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

# Import tiffifle
try:
    import tifffile
    USE_TIFFFILE = True
except ImportError:
    USE_TIFFFILE = False
    print("Note: tifffile not found, falling back to Pillow. "
          "For best OME-TIFF support:  pip install tifffile")


def build_filename(row: int, col: int, channel: int, z: int) -> str:
    # Construct the expected tile filename from row/col position,
    # channel number, and z-slice using the microscope naming pattern.
    # Pads numbers with zeros (e.g., 2 -> 02, 100 -> 0100).
    return (
        f"{FILENAME_PREFIX}"
        f"[{str(row).zfill(2)} x {str(col).zfill(2)}]"
        f"_C{str(channel).zfill(2)}"
        f"_z{str(z).zfill(4)}.ome.tif"
    )


def load_tile(row: int, col: int) -> np.ndarray:
    # Load a single image tile from disk at the configured row/col.
    # Builds the filename, verifies the file exists, then reads it
    # using tifffile (preferred) or Pillow as fallback.
    # Converts to float32 and collapses multi-dimensional arrays
    # to a single 2D image if needed.
    """Load a single tile at the configured Z slice."""
    fname = build_filename(row, col, CHANNEL, Z_SLICE)
    fpath = os.path.join(INPUT_DIR, fname)

    if not os.path.exists(fpath):
        sys.exit(
            f"ERROR: File not found:\n  {fpath}\n"
            f"Check INPUT_DIR, FILENAME_PREFIX, and Z_SLICE in the config."
        )

    if USE_TIFFFILE:
        import tifffile as tf
        arr = tf.imread(fpath).astype(np.float32)
    else:
        arr = np.array(Image.open(fpath)).astype(np.float32)

    # If tifffile returns a multi-dim array, take the first 2D plane
    while arr.ndim > 2:
        arr = arr[0]

    return arr


def blend_overlap_x(left_ol: np.ndarray, right_ol: np.ndarray) -> np.ndarray:
    # Blend two vertical overlap regions between neighboring tiles.
    # Creates a left→right linear ramp so the left tile fades out
    # while the right tile fades in, reducing visible seams.
    """Feathered blend of two vertical overlap strips."""
    n = left_ol.shape[1]
    ramp = np.linspace(1.0, 0.0, n, dtype=np.float32)[np.newaxis, :]
    return ramp * left_ol + (1.0 - ramp) * right_ol


def blend_overlap_y(top_ol: np.ndarray, bot_ol: np.ndarray) -> np.ndarray:
    # Blend two horizontal overlap regions between stacked tiles.
    # Uses a top→bottom linear ramp so the top tile fades out
    # while the bottom tile fades in.
    """Feathered blend of two horizontal overlap strips."""
    n = top_ol.shape[0]
    ramp = np.linspace(1.0, 0.0, n, dtype=np.float32)[:, np.newaxis]
    return ramp * top_ol + (1.0 - ramp) * bot_ol


def stitch_horizontal(left: np.ndarray, right: np.ndarray, overlap_px: int) -> np.ndarray:
    left_body  = left[:, :-overlap_px]
    left_ol    = left[:, -overlap_px:]
    right_ol   = right[:, :overlap_px]
    right_body = right[:, overlap_px:]
    blended    = blend_overlap_x(left_ol, right_ol)
    # Stitch two tiles side-by-side.
    # Splits each tile into body and overlap regions,
    # blends the overlapping strip, then concatenates:
    # [left body | blended overlap | right body].
    return np.concatenate([left_body, blended, right_body], axis=1)


def stitch_vertical(top: np.ndarray, bot: np.ndarray, overlap_px: int) -> np.ndarray:
    top_body   = top[:-overlap_px, :]
    top_ol     = top[-overlap_px:, :]
    bot_ol     = bot[:overlap_px, :]
    bot_body   = bot[overlap_px:, :]
    blended    = blend_overlap_y(top_ol, bot_ol)
    # Stitch two tiles vertically.
    # Splits tiles into body and overlap regions,
    # blends the horizontal overlap, then concatenates:
    # [top body / blended overlap / bottom body].
    return np.concatenate([top_body, blended, bot_body], axis=0)


def save_image(array: np.ndarray, path: str) -> None:
    # Normalize stitched image to full 16-bit range (uint16)
    # so intensity is preserved for microscopy visualization.
    # Saves the image as a TIFF using tifffile if available,
    # otherwise falls back to Pillow.
    vmin, vmax = array.min(), array.max()
    if vmax > vmin:
        norm = ((array - vmin) / (vmax - vmin) * 65535).astype(np.uint16)
    else:
        norm = np.zeros_like(array, dtype=np.uint16)

    if USE_TIFFFILE:
        import tifffile as tf
        tf.imwrite(path, norm, photometric='minisblack')
    else:
        Image.fromarray(norm).save(path)

    print(f"\nSaved: {path}")
    print(f"  Shape : {norm.shape[1]} x {norm.shape[0]} px")
    print(f"  Dtype : {norm.dtype}")


def main():
    # Main workflow:
    # 1. Print configuration info.
    # 2. Load one tile to determine tile size and overlap in pixels.
    # 3. Stitch each row horizontally.
    # 4. Stitch the resulting rows vertically.
    # 5. Save the final stitched image.
    print(f"Input dir : {INPUT_DIR}")
    print(f"Grid      : {N_ROWS} rows x {N_COLS} cols")
    print(f"Z slice   : {Z_SLICE}")
    print(f"Channel   : {CHANNEL}")
    print(f"Overlap   : {int(OVERLAP_FRACTION * 100)}%")
    print()

    # Load first tile to determine pixel dimensions
    sample = load_tile(0, 0)
    tile_h, tile_w = sample.shape[:2]
    overlap_y = max(1, int(round(OVERLAP_FRACTION * tile_h)))
    overlap_x = max(1, int(round(OVERLAP_FRACTION * tile_w)))
    print(f"Tile size : {tile_w} x {tile_h} px")
    print(f"Overlap   : {overlap_x} px (X),  {overlap_y} px (Y)")
    print()

    # Stitch each row horizontally
    row_images = []
    for r in range(N_ROWS):
        print(f"Loading row {r} ...", end="  ", flush=True)
        row_img = load_tile(r, 0)
        for c in range(1, N_COLS):
            tile = load_tile(r, c)
            row_img = stitch_horizontal(row_img, tile, overlap_x)
        row_images.append(row_img)
        print(f"-> {row_img.shape[1]} x {row_img.shape[0]} px")

    # Stitch rows vertically
    print("\nStitching rows vertically ...")
    final = row_images[0]
    for r in range(1, N_ROWS):
        final = stitch_vertical(final, row_images[r], overlap_y)
        print(f"  After row {r}: {final.shape[1]} x {final.shape[0]} px")

    save_image(final, OUTPUT_PATH)


if __name__ == "__main__":
    main()