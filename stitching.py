"""
Automatic 3D Image Stitching — Monje Lab
========================================
Detects tile grid, channels, and Z slices from OME-TIFF filenames,
stitches each Z slice into a 2D image per channel, and saves individually.
Filename suffix format expected: ...[RR x CC]_C<ch>_z<zzzz>.ome.tif
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


def blend_sinusoidal_x(left_ol, right_ol):
    """Raised-cosine (sinusoidal) blend along the horizontal axis.

    Uses w(t) = 0.5 * (1 + cos(π·t)) for t ∈ [0, 1], which gives a smooth
    S-curve with zero derivatives at both endpoints. This avoids the
    brightness kinks that linear ('weighted') blending can leave at seam
    boundaries, making it a better choice for tiles with significant
    illumination variation across the overlap region.
    """
    n = left_ol.shape[1]
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)[None, :]
    ramp = 0.5 * (1.0 + np.cos(np.pi * t))   # 1 → 0, smooth
    return ramp * left_ol + (1.0 - ramp) * right_ol


def blend_sinusoidal_y(top_ol, bot_ol):
    """Raised-cosine (sinusoidal) blend along the vertical axis.

    See blend_sinusoidal_x for a full description of the weighting curve.
    """
    n = top_ol.shape[0]
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    ramp = 0.5 * (1.0 + np.cos(np.pi * t))
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
    elif method == "sinusoidal":
        blended = blend_sinusoidal_x(left_ol, right_ol)
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
    elif method == "sinusoidal":
        blended = blend_sinusoidal_y(top_ol, bottom_ol)
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
    print(f"  Saved: {path} ({norm.shape[1]} x {norm.shape[0]} px)")


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
    Extract row, col, channel, z, and filename prefix.

    Only the suffix is matched — the prefix before '[RR x CC]' can be anything.
    Expected suffix format: [RR x CC]_C<ch>_z<zzzz>.ome.tif
    Example: 260128_anything_prefix[00 x 00]_C00_z0100.ome.tif

    Returns:
        (row, col, channel, z, prefix) or None if the filename doesn't match.
    """
    pattern = re.compile(
        r"^(.*?)\[(\d+) x (\d+)\]_C(\d+)_z(\d+)\.ome\.tif$"
    )
    m = pattern.match(fname)
    if not m:
        return None
    prefix_raw = m.group(1)
    row, col, channel, z = map(int, m.groups()[1:])
    # Strip trailing underscores/spaces so the folder name is clean
    prefix = prefix_raw.rstrip("_ ") or "stitched"
    return row, col, channel, z, prefix


# -------------------
# Main
# -------------------
def main():
    parser = argparse.ArgumentParser(description="Automatic 3D stitching of OME-TIFF tiles")
    parser.add_argument("--input_dir", required=True,
                        help="Folder containing tiles")
    parser.add_argument("--output_dir", default=None,
                        help="Root folder for stitched output. A sub-folder named after the "
                             "filename prefix is created here. Defaults to input_dir if not set.")
    parser.add_argument("--overlap", type=int, required=True,
                        help="Tile overlap as an integer percentage (e.g. 20 for 20%%)")
    parser.add_argument("--method", choices=["weighted", "sinusoidal", "average", "majority"],
                        default="weighted",
                        help=(
                            "Overlap blending method. "
                            "'weighted': linear ramp (fast, slight edge artefacts). "
                            "'sinusoidal': raised-cosine ramp (smoother seams, recommended for uneven illumination). "
                            "'average': equal 50/50 mix. "
                            "'majority': max-value (bright-field / binary masks)."
                        ))
    args = parser.parse_args()

    overlap_fraction = args.overlap / 100.0
    root_out = args.output_dir if args.output_dir else args.input_dir

    files = [f for f in os.listdir(args.input_dir) if f.endswith(".ome.tif")]
    tiles = {}
    z_slices, channels = set(), set()
    detected_prefix = None

    # Parse all files
    for f in files:
        parsed = parse_filename(f)
        if parsed:
            row, col, channel, z, prefix = parsed
            tiles[(row, col, z, channel)] = os.path.join(args.input_dir, f)
            z_slices.add(z)
            channels.add(channel)
            if detected_prefix is None:
                detected_prefix = prefix  # capture prefix from the first matched file

    if not tiles:
        sys.exit("No matching OME-TIFF tiles found.")

    z_slices = sorted(z_slices)
    channels = sorted(channels)

    # Build parent output folder:  <root_out>/<prefix>/
    parent_dir = os.path.join(root_out, detected_prefix)
    os.makedirs(parent_dir, exist_ok=True)

    print(f"Detected Z slices : {z_slices}")
    print(f"Detected channels : {channels}")
    print(f"Detected prefix   : {detected_prefix}")
    print(f"Overlap           : {args.overlap}%")
    print(f"Blend method      : {args.method}")
    print(f"Output parent dir : {parent_dir}")

    # Create one output folder per channel inside the parent folder
    channel_dirs = {}
    for ch in channels:
        ch_dir = os.path.join(parent_dir, f"Channel {ch}")
        os.makedirs(ch_dir, exist_ok=True)
        channel_dirs[ch] = ch_dir
    print(f"\nCreated channel folders: {list(channel_dirs.values())}")

    for z in z_slices:
        print(f"\n--- Z slice {z:04d} ---")

        rows_at_z = [r for r, c, z_, ch in tiles if z_ == z]
        cols_at_z = [c for r, c, z_, ch in tiles if z_ == z]
        n_rows, n_cols = max(rows_at_z) + 1, max(cols_at_z) + 1
        print(f"  Grid: {n_rows} rows x {n_cols} cols")

        # Compute overlap in pixels from one representative tile
        sample_path = tiles[(0, 0, z, channels[0])]
        sample_tile = load_tile(sample_path)
        tile_h, tile_w = sample_tile.shape
        overlap_x = max(1, int(round(overlap_fraction * tile_w)))
        overlap_y = max(1, int(round(overlap_fraction * tile_h)))

        for ch in channels:
            print(f"  Channel {ch} ...")

            # Stitch each row horizontally
            rows_stitched = []
            for r in range(n_rows):
                row_img = load_tile(tiles[(r, 0, z, ch)])
                for c in range(1, n_cols):
                    row_img = stitch_horizontal(
                        row_img, load_tile(tiles[(r, c, z, ch)]), overlap_x, args.method
                    )
                rows_stitched.append(row_img)

            # Stitch rows vertically
            final_img_2D = rows_stitched[0]
            for r_img in rows_stitched[1:]:
                final_img_2D = stitch_vertical(final_img_2D, r_img, overlap_y, args.method)

            # Save 2D tif into the channel's subfolder
            out_name = f"stitched_z{z:04d}_C{ch:02d}.tif"
            out_path = os.path.join(channel_dirs[ch], out_name)
            save_image(final_img_2D, out_path)

    print("\nDone.")


if __name__ == "__main__":
    main()