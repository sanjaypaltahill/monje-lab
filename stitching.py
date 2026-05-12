"""
stitching.py — Monje Lab Stitcher
===================================
Row, column, and full-slice stitching routines.

Corrections come from registration.extract_corrections() and are applied
as zero-padding before each join so that the sinusoidal blender in
blending.py always sees properly aligned strips.

Correction sign conventions
----------------------------
dy_per_col[(r, c)]  — vertical drift for the horizontal join left of column c
                       in row r.
    dy > 0 : tile B (right tile) sits *below* the running accumulator
             → pad accumulator bottom + tile B top
    dy < 0 : tile B sits *above* the running accumulator
             → pad accumulator top + tile B bottom

dx_per_row_col[(r, c)] — lateral drift for the vertical join above row r
                          in column c.
    dx > 0 : the incoming row image sits *to the right* of the running canvas
             → pad canvas right + row image left
    dx < 0 : the incoming row image sits *to the left*
             → pad canvas left + row image right
"""

import numpy as np
from io_utils import load_tile
from blending import stitch_pair_horizontal, stitch_pair_vertical


# ─────────────────────────────────────────────
#  ROW STITCHING  (horizontal, left → right)
# ─────────────────────────────────────────────

def stitch_row(tiles, z, ch, row_idx, n_cols, overlap_x,
               dy_corrections=None):
    """
    Stitch all columns of *row_idx* horizontally.

    dy_corrections : {col: int}
        Vertical drift correction for the join just left of *col*.
        Positive dy → right tile is lower; negative → right tile is higher.
    """
    if dy_corrections is None:
        dy_corrections = {}

    path = tiles.get((row_idx, 0, z, ch))
    if path is None:
        raise ValueError(f"Missing tile ({row_idx}, 0, z={z}, ch={ch})")
    row_img = load_tile(path)

    for c in range(1, n_cols):
        path_b = tiles.get((row_idx, c, z, ch))
        if path_b is None:
            print(f"    Warning: missing ({row_idx},{c}) — skipped")
            continue

        img_b = load_tile(path_b)
        dy = dy_corrections.get(c, 0)

        if dy != 0:
            abs_dy = abs(int(dy))
            if dy > 0:
                # right tile is lower → pad right tile top + accumulator bottom
                img_b   = np.pad(img_b,   ((abs_dy, 0), (0, 0)), constant_values=0)
                row_img = np.pad(row_img, ((0, abs_dy), (0, 0)), constant_values=0)
            else:
                # right tile is higher → pad right tile bottom + accumulator top
                img_b   = np.pad(img_b,   ((0, abs_dy), (0, 0)), constant_values=0)
                row_img = np.pad(row_img, ((abs_dy, 0), (0, 0)), constant_values=0)
            print(f"    dy={dy:+d} pad at col {c}: "
                  f"acc→{row_img.shape}, tile→{img_b.shape}")

        row_img = stitch_pair_horizontal(row_img, img_b, overlap_x)

    return row_img


# ─────────────────────────────────────────────
#  FULL-SLICE STITCHING
# ─────────────────────────────────────────────

def stitch_full_slice(tiles, z, ch, n_rows, n_cols,
                      overlap_x, overlap_y,
                      dy_per_col=None, dx_per_row_col=None):
    """
    Stitch the complete 2-D slice for one *ch* and one *z*.

    Steps
    -----
    1. Stitch each row horizontally (applying dy_per_col corrections).
    2. Stack row images vertically, applying dx_per_row_col lateral
       drift corrections before each vertical join.

    Parameters
    ----------
    dy_per_col     : {(row, col): int}  — from extract_corrections()
    dx_per_row_col : {(row, col): int}  — from extract_corrections()
    """
    if dy_per_col     is None: dy_per_col     = {}
    if dx_per_row_col is None: dx_per_row_col = {}

    # ── Step 1: stitch each row ────────────────────────────────────
    print(f"\n  Building rows for ch={ch}, z={z} …")
    row_images = []
    for r in range(n_rows):
        print(f"    Row {r}:")
        dy_corr = {c: dy_per_col.get((r, c), 0) for c in range(1, n_cols)}
        row_img = stitch_row(tiles, z, ch, r, n_cols, overlap_x, dy_corr)
        row_images.append(row_img)
        print(f"    Row {r} done → {row_img.shape}")

    # ── Step 2: stack rows vertically with lateral drift correction ─
    print(f"\n  Stacking rows for ch={ch}, z={z} …")
    canvas = row_images[0]

    for r in range(1, n_rows):
        incoming = row_images[r]
        dx = dx_per_row_col.get((r, 0), 0)   # use col-0 lateral drift as row representative

        if dx != 0:
            abs_dx = abs(dx)
            if dx > 0:
                # incoming row is to the right → pad canvas right + incoming left
                canvas   = np.pad(canvas,   ((0, 0), (0, abs_dx)), constant_values=0)
                incoming = np.pad(incoming, ((0, 0), (abs_dx, 0)), constant_values=0)
            else:
                # incoming row is to the left → pad canvas left + incoming right
                canvas   = np.pad(canvas,   ((0, 0), (abs_dx, 0)), constant_values=0)
                incoming = np.pad(incoming, ((0, 0), (0, abs_dx)), constant_values=0)
            print(f"    dx={dx:+d} lateral pad before row {r}: "
                  f"canvas→{canvas.shape}, incoming→{incoming.shape}")

        print(f"    Joining row {r-1} + row {r}:")
        canvas = stitch_pair_vertical(canvas, incoming, overlap_y)

    return canvas


def stitch_full_slice_naive(tiles, z, ch, n_rows, n_cols, overlap_x, overlap_y):
    """
    Stitch the full slice with *no* registration corrections (nominal placement only).
    Useful as a before/after reference.
    """
    print(f"\n  Building rows (NAIVE) for ch={ch}, z={z} …")
    row_images = []
    for r in range(n_rows):
        print(f"    Row {r}:")
        row_img = stitch_row(tiles, z, ch, r, n_cols, overlap_x)
        row_images.append(row_img)
        print(f"    Row {r} done → {row_img.shape}")

    print(f"\n  Stacking rows (NAIVE) for ch={ch}, z={z} …")
    canvas = row_images[0]
    for r in range(1, n_rows):
        print(f"    Joining row {r-1} + row {r}:")
        canvas = stitch_pair_vertical(canvas, row_images[r], overlap_y)

    return canvas
