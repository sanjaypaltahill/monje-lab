"""
Automatic 3D Image Stitching — Monje Lab
========================================
Detects tile grid, prefix, channel, Z slices, and overlap from OME-TIFF filenames,
stitches each Z slice into a 2D image, and then stacks all Z slices into a 3D TIFF
using precise weighted feathering in the overlapping regions.
"""

import os
import sys
import re
import argparse
import numpy as np

try:
    from PIL import Image
except ImportError:
    sys.exit("Please install Pillow: pip install Pillow")

try:
    import tifffile
    USE_TIFFFILE = True
except ImportError:
    USE_TIFFFILE = False
    print("tifffile not found; falling back to Pillow.")


# -------------------
# Overlap blending
# -------------------
def blend_weighted_x(left_ol, right_ol):
    n = left_ol.shape[1]
    ramp = np.linspace(1.0, 0.0, n, dtype=np.float32)[None, :]
    return ramp * left_ol + (1.0 - ramp) * right_ol


def blend_weighted_y(top_ol, bot_ol):
    n = top_ol.shape[0]
    ramp = np.linspace(1.0, 0.0, n, dtype=np.float32)[:, None]
    return ramp * top_ol + (1.0 - ramp) * bot_ol


def blend_average(left, right):
    return 0.5 * (left + right)


def blend_majority(left, right):
    return np.maximum(left, right)


def stitch_horizontal(left, right, overlap_px, method):
    left_body, left_ol = left[:, :-overlap_px], left[:, -overlap_px:]
    right_ol, right_body = right[:, :overlap_px], right[:, overlap_px:]

    if method == "weighted":
        blended = blend_weighted_x(left_ol, right_ol)
    elif method == "average":
        blended = blend_average(left_ol, right_ol)
    elif method == "majority":
        blended = blend_majority(left_ol, right_ol)
    else:
        raise ValueError(f"Unknown method: {method}")

    return np.concatenate([left_body, blended, right_body], axis=1)


def stitch_vertical(top, bottom, overlap_px, method):
    top_body, top_ol = top[:-overlap_px, :], top[-overlap_px:, :]
    bottom_ol, bottom_body = bottom[:overlap_px, :], bottom[overlap_px:, :]

    if method == "weighted":
        blended = blend_weighted_y(top_ol, bottom_ol)
    elif method == "average":
        blended = blend_average(top_ol, bottom_ol)
    elif method == "majority":
        blended = blend_majority(top_ol, bottom_ol)
    else:
        raise ValueError(f"Unknown method: {method}")

    return np.concatenate([top_body, blended, bottom_body], axis=0)


# -------------------
# Image I/O
# -------------------
def save_image(img, path):
    vmin, vmax = img.min(), img.max()
    norm = ((img - vmin) / (vmax - vmin) * 65535).astype(np.uint16) if vmax > vmin else np.zeros_like(img, np.uint16)
    if USE_TIFFFILE:
        tifffile.imwrite(path, norm, photometric='minisblack')
    else:
        Image.fromarray(norm).save(path)
    print(f"\nSaved image: {path} ({norm.shape[1]} x {norm.shape[0]} px)")


def load_tile(path):
    if USE_TIFFFILE:
        img = tifffile.imread(path).astype(np.float32)
    else:
        img = np.array(Image.open(path)).astype(np.float32)
    while img.ndim > 2:
        img = img[0]
    return img


def parse_filename(fname):
    """
    Extract prefix, row, col, channel, z, and overlap fraction from filename
    Example:
    260128_..._20ol_10umstep[00 x 00]_C00_z0100.ome.tif
    """
    pattern = re.compile(
        r"(.*?)(?:_(\d+)ol)?(?:_[^_]+)*\[(\d+) x (\d+)\]_C(\d+)_z(\d+).*\.ome\.tif$"
    )
    m = pattern.match(fname)
    if not m:
        return None
    prefix, ol, row, col, channel, z = m.groups()
    row, col, channel, z = map(int, (row, col, channel, z))
    overlap = int(ol)/100 if ol else 0.2
    return prefix, row, col, channel, z, overlap


# -------------------
# Main
# -------------------
def main():
    parser = argparse.ArgumentParser(description="Automatic 3D stitching of OME-TIFF tiles")
    parser.add_argument("--input_dir", required=True, help="Folder containing tiles")
    parser.add_argument("--method", choices=["weighted", "average", "majority"], default="weighted")
    parser.add_argument("--output", default="./stitched_3D_output.tif")
    args = parser.parse_args()

    files = [f for f in os.listdir(args.input_dir) if f.endswith(".ome.tif")]
    tiles = {}
    prefixes, z_slices, channels = set(), set(), set()
    overlap = None

    # Parse all files
    for f in files:
        parsed = parse_filename(f)
        if parsed:
            prefix, row, col, channel, z, ol = parsed
            tiles[(row, col, z, channel)] = os.path.join(args.input_dir, f)
            prefixes.add(prefix)
            z_slices.add(z)
            channels.add(channel)
            if overlap is None:
                overlap = ol

    if not tiles:
        sys.exit("No matching OME-TIFF tiles found.")

    prefix = list(prefixes)[0]
    print(f"Detected prefix: {prefix}")
    print(f"Detected Z slices: {sorted(z_slices)}, Channels: {sorted(channels)}")
    print(f"Detected overlap: {overlap*100:.0f}%, Method: {args.method}")

    z_slices = sorted(z_slices)
    channels = sorted(channels)

    stitched_planes = []

    for z in z_slices:
        print(f"\n--- Stitching Z slice {z} ---")
        rows = [r for r, c, z_, ch in tiles.keys() if z_ == z]
        cols = [c for r, c, z_, ch in tiles.keys() if z_ == z]
        n_rows, n_cols = max(rows)+1, max(cols)+1
        print(f"Grid: {n_rows} rows x {n_cols} cols")

        sample_tile = load_tile(tiles[(0, 0, z, channels[0])])
        tile_h, tile_w = sample_tile.shape
        overlap_x = max(1, int(round(overlap * tile_w)))
        overlap_y = max(1, int(round(overlap * tile_h)))

        # Stitch rows
        rows_stitched = []
        for r in range(n_rows):
            row_img = load_tile(tiles[(r, 0, z, channels[0])])
            for c in range(1, n_cols):
                row_img = stitch_horizontal(row_img, load_tile(tiles[(r, c, z, channels[0])]), overlap_x, args.method)
            rows_stitched.append(row_img)

        # Stitch rows vertically
        final_img_2D = rows_stitched[0]
        for r_idx, r_img in enumerate(rows_stitched[1:], start=1):
            final_img_2D = stitch_vertical(final_img_2D, r_img, overlap_y, args.method)

        # Save each Z slice individually
        z_filename = os.path.join(args.input_dir, f"stitched_z{z:04d}.tif")
        save_image(final_img_2D, z_filename)
        stitched_planes.append(final_img_2D)

    # Stack all Z slices into 3D
    stacked_3D = np.stack(stitched_planes, axis=0)
    save_image(stacked_3D, args.output)
    print(f"\n3D stacked image saved: {args.output} ({stacked_3D.shape[2]} x {stacked_3D.shape[1]} x {stacked_3D.shape[0]} px)")


if __name__ == "__main__":
    main()