# Monje Lab Stitcher

A command-line tool for stitching multi-tile fluorescence microscopy images acquired as overlapping OME-TIFF grids. It uses **phase-cross-correlation (PCC)** for sub-pixel registration and **average blending** in the overlap zone.

---

## Table of Contents

1. [Requirements](#requirements)
2. [File Overview](#file-overview)
3. [Input Format](#input-format)
4. [How It Works](#how-it-works)
5. [Usage](#usage)
6. [Parameters](#parameters)
7. [Output Structure](#output-structure)
8. [Tips & Troubleshooting](#tips--troubleshooting)

---

## Requirements

```bash
pip install tifffile scikit-image numpy matplotlib
```

Python 3.9+ recommended.

---

## File Overview

| File | Purpose |
|---|---|
| `main.py` | Entry point — argument parsing, orchestration |
| `io_utils.py` | Filename parsing, tile discovery, TIFF I/O |
| `registration.py` | PCC shift estimation (`estimate_shift_horizontal`, `estimate_shift_vertical`) |
| `blending.py` | Unified `stitch_pair(img_a, img_b, overlap_px, axis)` function |
| `stitching.py` | Row and full-slice stitching using the incremental two-image approach |
| `test_mode.py` | Single-pair diagnostic: naive/corrected overlays + stitched TIFF |
| `visualization.py` | Grid-overlay PNG for inspecting nominal tile positions |

---

## Input Format

Tiles must follow this exact naming convention:

```
<prefix>[ROW x COL]_C<CH>_z<Z>.ome.tif
```

Examples:
```
sample_[00 x 00]_C0_z0000.ome.tif
sample_[00 x 01]_C0_z0000.ome.tif
sample_[01 x 00]_C1_z0005.ome.tif
```

- `ROW` and `COL` are zero-based integer indices.
- `CH` is the channel index (0-based).
- `Z` is the Z-slice index (zero-padded to 4 digits is conventional but any integer works).
- All tiles must be 2-D greyscale (extra leading dimensions like a singleton Z axis are automatically collapsed on load).

---

## How It Works

### Registration

At every tile join, the stitcher calls **phase cross-correlation** (PCC) on the overlapping strip between the accumulated image so far and the next incoming tile. This is always a two-image problem:

- **Horizontal join**: the rightmost `overlap_px + fudge` columns of the left image are compared to the leftmost `overlap_px` columns of the right image.
- **Vertical join**: the bottom `overlap_px + fudge` rows of the top image are compared to the top `overlap_px` rows of the bottom image.

The `fudge` margin lets PCC find shifts that fall slightly outside the exact nominal overlap boundary.

The returned `(dy, dx)` shift is decomposed:
- The **perpendicular** component (e.g. `dy` for a horizontal join) is applied as **zero-padding** to align the images before blending.
- The **parallel** component (e.g. `dx` for a horizontal join) adjusts the effective overlap width passed to the blender, so the seam moves to where the content actually aligns.

If either shift component exceeds `--max_shift`, the correction is discarded and nominal placement is used instead.

### Incremental stitching

The core insight is that the stitching problem never needs to be framed as a global grid optimisation. It is always *"join two images"*:

```
Row stitching (left → right):
  accum = tile[r, 0]
  accum = stitch(accum, tile[r, 1])   ← register accum against tile 1
  accum = stitch(accum, tile[r, 2])   ← register accum against tile 2
  …

Slice stitching (top → bottom):
  canvas = row[0]
  canvas = stitch(canvas, row[1])     ← register canvas against row 1
  canvas = stitch(canvas, row[2])     ← register canvas against row 2
  …
```

Because registration is always done against the current accumulated image (not against individual tiles compared to one another), drift accumulates correctly and no global coordinate solving is needed.

### Blending

The overlap zone is blended with a simple **50/50 average** by default. A sinusoidal (raised-cosine) kernel is also available in `blending.py` if you want a smoother transition — swap `blend="average"` for `blend="sinusoidal"` in the `stitch_pair` calls inside `stitching.py`.

---

## Usage

### Test mode — inspect a single tile pair

Use this before running a full stitch to verify that registration looks correct for your data.

```bash
# Horizontal pair: row 0, col 0 ↔ col 1, first Z slice
python main.py --input_dir /path/to/tiles --overlap 10 --mode test

# Vertical pair: col 1, row 2 ↔ row 3, Z slice 7
python main.py --input_dir /path/to/tiles --overlap 10 --mode test \
               --orientation vertical --row_idx 2 --col_idx 1 --z_slice 7
```

Produces in `<output_dir>/<prefix>_registered/`:
- `test_H_r0_c0-1_z0000_NAIVE.png` — tile B placed at nominal position
- `test_H_r0_c0-1_z0000_CORRECTED.png` — tile B placed after PCC correction
- `test_H_r0_c0-1_z0000_STITCHED.tif` — blended stitch of the pair

Each PNG has three panels: a false-colour composite (red=A, green=B, yellow=overlap), a signed difference map (zero = perfect alignment), and a zoomed crop of the seam.

### Real mode — full stitch

```bash
# All Z slices, all channels:
python main.py --input_dir /path/to/tiles --overlap 10 --mode real

# Only Z slice 5:
python main.py --input_dir /path/to/tiles --overlap 10 --mode real --z_slice 5

# With grid overlay visualisations:
python main.py --input_dir /path/to/tiles --overlap 10 --mode real --visualize
```

---

## Parameters

| Flag | Default | Description |
|---|---|---|
| `--input_dir` | *(required)* | Folder containing `.ome.tif` tiles |
| `--output_dir` | same as input | Root folder for all outputs |
| `--overlap` | *(required)* | Nominal overlap as % of tile size (e.g. `10` = 10%) |
| `--mode` | `real` | `test` = single pair diagnostics, `real` = full stitch |
| `--ref_channel` | first found | Channel used for registration (all channels are stitched using the transforms computed from this one) |
| `--z_slice` | all | Pin to a single Z index; omit to process every Z |
| `--max_shift` | `50` | Any PCC shift larger than this (px) is discarded and replaced with 0 |
| `--fudge` | `10` | Extra pixels added to the reference strip width/height so PCC can find shifts slightly outside the nominal overlap |
| `--upsample` | `10` | PCC upsample factor — sub-pixel accuracy = 1/upsample px |
| `--orientation` | `horizontal` | Test mode only: `horizontal` or `vertical` |
| `--row_idx` | `0` | Test mode: row of the anchor tile |
| `--col_idx` | `0` | Test mode: column of the anchor tile |
| `--visualize` | off | Real mode: save a `grid_overlays/` folder with nominal grid PNGs |

### Tuning guidance

- **`--overlap`**: set this to match the actual acquisition overlap. If in doubt, inspect two adjacent raw tiles and measure the visible overlap.
- **`--max_shift`**: set to the largest realistic misalignment between adjacent tiles. Too high → bad PCC results get applied; too low → real corrections get discarded.
- **`--fudge`**: increase if tiles sometimes miss because the actual overlap is noticeably smaller than nominal. Keep it under `overlap_px / 2` to avoid confusing the PCC.
- **`--upsample`**: higher = finer sub-pixel accuracy but slower. 10 (0.1 px accuracy) is a good default.

---

## Output Structure

```
<output_dir>/
└── <prefix>_registered/
    ├── Channel_00/
    │   ├── stitched_z0000_C00_CORRECTED.tif
    │   ├── stitched_z0001_C00_CORRECTED.tif
    │   └── …
    ├── Channel_00_NAIVE/
    │   ├── stitched_z0000_C00_NAIVE.tif
    │   └── …
    ├── Channel_01/
    │   └── …
    ├── grid_overlays/          (only with --visualize)
    │   ├── grid_z0000.png
    │   └── …
    └── test_*/                 (only in test mode)
        ├── test_H_r0_c0-1_z0000_NAIVE.png
        ├── test_H_r0_c0-1_z0000_CORRECTED.png
        └── test_H_r0_c0-1_z0000_STITCHED.tif
```

All stitched TIFFs are written as **16-bit greyscale** (normalised from float32 min/max). The NAIVE outputs use nominal overlap only; the CORRECTED outputs include PCC registration.

---

## Tips & Troubleshooting

**The NAIVE and CORRECTED stitches look the same.**
PCC returned a near-zero correction. This can happen when: (a) the overlap region has very little texture/signal — try a different tile pair with `--row_idx`/`--col_idx`; (b) the actual overlap matches the nominal perfectly; or (c) `--max_shift` is too small and the real shift is being discarded (check the printed PCC output).

**Ghosting / double edges in the stitched output.**
The effective overlap being used is wrong. Try adjusting `--overlap` by ±2–3% and re-running in test mode to see which value gives yellow (clean overlap) rather than red+green (misaligned).

**PCC detections are noisy / jumping around.**
Lower `--upsample` (try 5) or increase `--max_shift` and check whether the clamping warning fires. If most tile pairs are fine but a few are bad, `--max_shift` can be lowered to ignore the outliers.

**Memory errors on large volumes.**
Process one Z slice at a time with `--z_slice N`. The stitcher loads all tiles for a single Z into RAM at once; a large grid at high bit-depth can be several GB.

**Tiles are out of order or skipped.**
Check filenames match `<prefix>[ROW x COL]_C<CH>_z<Z>.ome.tif` exactly — the brackets, spaces around `x`, and extensions are all significant.
