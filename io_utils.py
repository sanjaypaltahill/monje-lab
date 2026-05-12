"""
io_utils.py — Monje Lab Stitcher
=================================
Filename parsing, tile I/O, and TIFF writing.
These helpers are stable and shared across all modules.
"""

import os
import re
import sys
import numpy as np

try:
    import tifffile
except ImportError:
    sys.exit("Missing dependency: pip install tifffile")


# ─────────────────────────────────────────────
#  FILENAME PARSING
# ─────────────────────────────────────────────

def parse_filename(fname):
    """
    Match:  <prefix>[ROW x COL]_C<CH>_z<Z>.ome.tif

    Returns (row, col, channel, z, prefix) or None.
    """
    m = re.match(r"^(.*?)\[(\d+) x (\d+)\]_C(\d+)_z(\d+)\.ome\.tif$", fname)
    if not m:
        return None
    prefix = m.group(1).rstrip("_ ") or "registered"
    row, col, ch, z = map(int, m.groups()[1:])
    return row, col, ch, z, prefix


def discover_tiles(input_dir):
    """
    Scan *input_dir* for OME-TIFF tiles matching the expected filename pattern.

    Returns
    -------
    tiles : dict  {(row, col, z, ch): abs_path}
    zs    : sorted list of Z indices
    chs   : sorted list of channel indices
    prefix: filename prefix string (from first matched file)
    """
    files = [f for f in os.listdir(input_dir) if f.endswith(".ome.tif")]
    tiles = {}
    zs, chs = set(), set()
    prefix = None

    for f in files:
        parsed = parse_filename(f)
        if parsed:
            r, c, ch, z, pfx = parsed
            tiles[(r, c, z, ch)] = os.path.join(input_dir, f)
            zs.add(z)
            chs.add(ch)
            if prefix is None:
                prefix = pfx

    if not tiles:
        sys.exit(
            "No tiles found — filenames must match:\n"
            "  <prefix>[ROW x COL]_C<CH>_z<Z>.ome.tif"
        )

    return tiles, sorted(zs), sorted(chs), prefix


def grid_dims(tiles, z):
    """Return (n_rows, n_cols) for the given Z slice."""
    keys = [(r, c) for (r, c, z_, _) in tiles if z_ == z]
    if not keys:
        raise ValueError(f"No tiles found for Z={z}")
    return max(r for r, c in keys) + 1, max(c for r, c in keys) + 1


# ─────────────────────────────────────────────
#  IMAGE I/O
# ─────────────────────────────────────────────

def load_tile(path):
    """Load a TIFF tile → 2-D float32 array (collapses extra dims)."""
    img = tifffile.imread(path).astype(np.float32)
    while img.ndim > 2:
        img = img[0]
    return img


def save_tiff(img, path):
    """Normalise *img* to uint16 and write a greyscale TIFF."""
    vmin, vmax = img.min(), img.max()
    if vmax > vmin:
        norm = ((img - vmin) / (vmax - vmin) * 65535).astype(np.uint16)
    else:
        norm = np.zeros_like(img, dtype=np.uint16)
    tifffile.imwrite(path, norm, photometric="minisblack")
    print(f"    Saved: {path}  ({norm.shape[1]}×{norm.shape[0]} px)")
