# Monje Lab — Image Stitching & Registration Pipeline

> Tools for automatic OME-TIFF tile stitching and phase-correlation-based image registration for high-content fluorescence microscopy

---

## Table of Contents

1. [Overview](#overview)
2. [When to Use Which Script](#when-to-use-which-script)
3. [Shared Filename Format](#shared-filename-format)
4. [Script 1: `stitching.py` — Basic Overlap Stitching](#script-1-stitchingpy--basic-overlap-stitching)
5. [Script 2: `registration.py` — Phase-Correlation Registration](#script-2-registrationpy--phase-correlation-registration)
6. [Dependencies](#dependencies)
7. [Troubleshooting](#troubleshooting)

---

## Overview

This pipeline contains two complementary scripts for assembling large mosaic fluorescence microscopy images from overlapping tile grids:

**`stitching.py`** is a straightforward stitcher. It places tiles on a canvas using their known grid positions and blends the overlapping edges using one of four ramp functions. It does not attempt to correct for any mechanical error in stage positioning — it trusts the nominal overlap value you supply. This makes it fast, simple, and appropriate when your microscope stage is well-calibrated or when you just need a quick, clean result.

**`registration.py`** adds an active correction step on top of stitching. Before placing each tile, it uses phase cross-correlation (PCC) to measure the actual pixel-level offset between adjacent tile edges and adjusts the placement accordingly. This corrects for small systematic or random errors in stage movement and produces sharper, artefact-free seams — especially important for high-magnification acquisitions or stitching across large grids where positional drift accumulates.

Both scripts handle multiple Z-slices and multiple fluorescence channels automatically, and organize their output into per-channel subfolders.

---

## When to Use Which Script

| Situation | Recommended script |
|-----------|--------------------|
| Well-calibrated stage, fast turnaround needed | `stitching.py` |
| Visible seams or misalignment in stitched output | `registration.py` |
| Large tile grids where drift accumulates | `registration.py` |
| High magnification (small field of view, large overlap error relative to tile size) | `registration.py` |
| Sparse or low-contrast images (little texture for cross-correlation) | `stitching.py` |
| First pass / exploratory stitching | `stitching.py` |
| Final publication-quality output | `registration.py` |

---

## Shared Filename Format

Both scripts require tiles to be named using the following suffix convention:

```
<PREFIX>[RR x CC]_C<CHANNEL>_z<ZSLICE>.ome.tif
```

| Component | Meaning |
|-----------|---------|
| `PREFIX` | Any string before `[`. Captured and used to name the output folder. |
| `[RR x CC]` | Tile row and column, zero-indexed (e.g. `[02 x 05]`) |
| `C<CHANNEL>` | Channel number (integer, e.g. `C00`, `C01`) |
| `z<ZSLICE>` | Z-slice number (integer, e.g. `z0100`) |

**Example filename:**
```
260128_UltraII_5300148-2R_HNACy3[02 x 05]_C01_z0100.ome.tif
```

Files that do not match this pattern are silently ignored.

---

## Script 1: `stitching.py` — Basic Overlap Stitching

### What It Does

`stitching.py` reads all `.ome.tif` tiles in your input folder, determines the grid layout (rows, columns, channels, Z-slices) from the filenames, and stitches them into a single 2D image per Z-slice per channel. The stitching is done purely by position: tiles are placed at their nominal grid coordinates, and the overlapping region is blended using one of four blending functions.

### Workflow

1. Parse all filenames to detect grid size, channels, and Z-slices.
2. For each Z-slice and each channel, load tiles row by row.
3. Stitch each row horizontally (left to right) by blending the overlap region.
4. Stitch completed rows together vertically (top to bottom) by blending vertical overlaps.
5. Save each stitched 2D image as a uint16 TIFF.

### Usage

```bash
python stitching.py \
    --input_dir  "/path/to/tiles" \
    --output_dir "/path/to/output" \
    --overlap 20 \
    --method sinusoidal
```

### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--input_dir` | Yes | — | Path to the folder containing `.ome.tif` tile files. |
| `--output_dir` | No | Same as `input_dir` | Root folder for stitched output. A subfolder named after the filename prefix is created automatically. |
| `--overlap` | Yes | — | Tile overlap as an integer percentage of tile size (e.g. `20` for 20%). |
| `--method` | No | `weighted` | Blending method for the overlap region. Options: `weighted`, `sinusoidal`, `average`, `majority`. See [Blending Methods](#blending-methods) below. |

### Output Structure

```
output_dir/
  260128_UltraII_5300148-2R/       ← named from filename prefix
    Channel 0/
      stitched_z0100_C00.tif
      stitched_z0101_C00.tif
      ...
    Channel 1/
      stitched_z0100_C01.tif
      ...
```

### Blending Methods

The blending method controls how the pixel values in the overlapping region between two adjacent tiles are combined. All methods apply the same overlap width (derived from the `--overlap` percentage) — they differ only in the shape of the interpolation curve.

#### `weighted` — Linear ramp
The weight of the left (or top) tile decreases linearly from 1 to 0 across the overlap zone, while the right (or bottom) tile increases from 0 to 1. Fast and general-purpose. Can leave faint brightness kinks at the very edge of the seam if the tiles have uneven illumination (e.g. from objective vignetting), because the ramp has a constant non-zero slope all the way to the boundary.

#### `sinusoidal` — Raised-cosine ramp *(Recommended)*
Uses the function `w(t) = 0.5 × (1 + cos(π·t))` for t ∈ [0, 1]. This S-shaped curve goes from 1 to 0 with **zero slope at both endpoints**, meaning the brightness transition is imperceptible at the seam boundary. This suppresses the faint grid artefacts that appear when tiles have illumination gradients, making it the best general-purpose choice for fluorescence microscopy data.

#### `average` — Flat 50/50 mix
Each pixel in the overlap zone is simply the mean of the two tiles. Produces no ramp and can create a visible band of reduced intensity at seams if the two tiles differ in brightness.

#### `majority` — Maximum value
Takes the brighter of the two pixel values at each position. Best suited for sparse, bright-on-dark images (e.g. binary masks or segmentation maps) where you want to preserve signal rather than average it down.

---

## Script 2: `registration.py` — Phase-Correlation Registration

### What It Does

`registration.py` builds on simple stitching by actively estimating the real alignment between adjacent tiles using **phase cross-correlation (PCC)** — a Fourier-domain method that finds the translation that maximizes pixel-level agreement between two overlapping image strips. These estimated shifts are used to place each tile at its corrected canvas position rather than its nominal position. The final compositing step uses a raised-cosine feather mask for smooth blending.

This approach is particularly valuable in fluorescence microscopy because:
- Piezoelectric and stepper stages introduce small, accumulated position errors across large grids.
- High-magnification tiles cover small areas, so even a few microns of drift translates to tens of pixels of misalignment.
- Fluorescence images often have non-uniform illumination (vignetting), making visible seams more likely without active correction.

### Workflow

1. Parse all filenames to detect grid, channels, and Z-slices.
2. Load a representative tile to determine dimensions and compute overlap in pixels.
3. For each Z-slice, solve the full grid of canvas positions by walking left-to-right and top-to-bottom, estimating PCC shifts at each tile boundary using the reference channel.
4. Use those positions (shared across all channels) to composite each channel with feathered blending.
5. Save each stitched 2D image as a uint16 TIFF.

### Two Operating Modes

#### `--mode test` (Start Here)
Processes only the first two tiles in the grid (row 2, columns 0 and 1 of the reference channel at Z-slice 0 by default in the current code) and saves diagnostic PNG overlays so you can visually verify alignment quality before committing to a full run. Outputs:

- `test_NAIVE_<method>.png` — the two tiles placed at their nominal positions with no PCC correction (shows how bad raw misalignment is)
- `test_CORRECTED_<method>.png` — the same tiles after applying the PCC-estimated shift (shows how well the correction works)

Each overlay shows three panels: a red/green false-colour composite (yellow = overlap = good alignment), a difference map, and a zoomed view of the seam region.

#### `--mode real`
Processes all tiles, all Z-slices, and all channels. Produces the full stitched output TIFFs.

### Two Warp Methods

#### `--method skimage`
Applies the estimated shift using scikit-image's `AffineTransform` + `warp`. This is the standard path and is recommended for most users.

#### `--method diy`
Assembles the 3×3 affine transformation matrix by hand using numpy, then applies it via OpenCV (`cv2.warpAffine`) if available, or falls back to scikit-image. The matrix is a pure translation (rotation = 0, shear = 0, scale = 1), but its explicit construction makes it easy to extend with custom rotation or shear corrections later. Both methods produce identical results for pure translation; `diy` exists mainly for transparency and extensibility.

### Usage

**Step 1 — Test alignment on two tiles first:**
```bash
python registration.py \
    --input_dir  "/path/to/tiles" \
    --overlap 10 \
    --method skimage \
    --mode test
```

Review the generated PNG overlays. Look for yellow in the overlap zone (alignment) and minimal red/green fringes (misalignment). If the corrected overlay looks better than the naive one, proceed to the full run.

**Step 2 — Full registration and stitching:**
```bash
python registration.py \
    --input_dir  "/path/to/tiles" \
    --output_dir "/path/to/output" \
    --overlap 10 \
    --method skimage \
    --mode real
```

### Arguments

| Argument | Required | Default | Description |
|----------|----------|---------|-------------|
| `--input_dir` | Yes | — | Folder containing `.ome.tif` tile files. |
| `--output_dir` | No | Same as `input_dir` | Root folder for output. A subfolder named `<prefix>_registered_v3` is created automatically. |
| `--overlap` | Yes | — | Nominal tile overlap as a percentage of tile size (e.g. `10` for 10%). |
| `--method` | No | `skimage` | Warp method: `skimage` (AffineTransform) or `diy` (hand-built matrix). |
| `--mode` | No | `real` | `test` = diagnostic overlays for first two tiles only; `real` = full stitch. |
| `--max_shift` | No | `20` | Maximum allowed PCC correction in pixels. Shifts larger than this are clamped, preventing a bad correlation from sending tiles flying. |
| `--fudge` | No | `500` | Extra pixels added to the overlap strip before cross-correlation. Wider strips give the correlator more image texture to work with and tolerate slightly inaccurate nominal overlap values. |
| `--ref_channel` | No | Lowest channel | Channel number used to estimate shifts. The same shifts are then applied to all other channels. Choose the channel with the highest signal-to-noise ratio. |
| `--upsample` | No | `1` | Sub-pixel upsampling factor for PCC. A value of `10` gives 0.1 px accuracy; `20` gives 0.05 px accuracy. Higher values are slower. For most microscopy data, `1` (integer-pixel accuracy) is sufficient. |
| `--visualize` | No | Off | (Real mode only) Save a grid-overlay PNG per Z-slice showing each tile's bounding box on the canvas. Useful for inspecting the solved positions. |

### How Phase Cross-Correlation Works

Phase cross-correlation finds the translation between two images by working in the frequency domain. Given two overlapping strips — one from the right edge of tile A and one from the left edge of tile B — PCC computes the normalized cross-power spectrum and takes its inverse Fourier transform. The peak of the resulting correlation surface corresponds to the shift that best aligns the two strips.

Key properties that make PCC well-suited for microscopy:
- **Sub-pixel accuracy** (when `--upsample > 1`): the correlation surface is upsampled around its peak to localize it more precisely than integer pixels.
- **Illumination robustness**: the normalization step ("phase-only" correlation) downweights the DC component and broad illumination gradients, focusing correlation on fine texture.
- **Speed**: the FFT-based computation is fast even on large overlap strips.

The `--fudge` parameter extends the strip beyond the nominal overlap to give the correlator more texture to match against, which improves reliability when the nominal overlap is uncertain or when tiles have low-contrast edges.

### Position Solving Strategy

The grid positions are solved in two passes:

1. **Horizontal pass (left → right):** For each row, each tile's horizontal position is computed relative to its left neighbour using the PCC-estimated `dx` shift on top of the nominal offset.
2. **Vertical pass (top → bottom):** For each column, each tile's vertical position is computed relative to its upper neighbour using the PCC-estimated `dy` shift on top of the nominal offset.

The positions accumulate additively across the grid. This means errors in early tiles propagate to later ones — the `--max_shift` clamp limits how far any single bad estimate can throw off the solution.

### Output Structure

```
output_dir/
  260128_UltraII_5300148-2R_registered_v3/
    Channel_00/
      registered_z0100_C00.tif
      registered_z0101_C00.tif
      ...
    Channel_01/
      registered_z0100_C01.tif
      ...
    grid_overlays/              ← only if --visualize is set
      grid_z0100.png
      ...
    test_NAIVE_skimage.png      ← only in test mode
    test_CORRECTED_skimage.png  ← only in test mode
```

---

## Dependencies

### `stitching.py`

| Package | Install |
|---------|---------|
| Python 3.8+ | — |
| `numpy` | `pip install numpy` |
| `Pillow` | `pip install Pillow` |
| `tifffile` *(recommended)* | `pip install tifffile` |

If `tifffile` is not installed, the script falls back to Pillow for image I/O. Pillow may not correctly handle all OME-TIFF metadata, so `tifffile` is strongly recommended.

### `registration.py`

| Package | Install | Notes |
|---------|---------|-------|
| Python 3.8+ | — | — |
| `numpy` | `pip install numpy` | — |
| `tifffile` | `pip install tifffile` | Required |
| `scikit-image >= 0.19` | `pip install scikit-image` | Required for PCC |
| `scipy` | `pip install scipy` | Required by scikit-image |
| `matplotlib` | `pip install matplotlib` | Required for diagnostic overlays |
| `Pillow` | `pip install Pillow` | Required |
| `opencv-python` | `pip install opencv-python` | Optional; accelerates `--method diy` warping |

**Install everything at once:**
```bash
pip install numpy tifffile scipy scikit-image Pillow matplotlib opencv-python
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| `"No matching OME-TIFF tiles found"` | Filenames don't match expected pattern | Verify filenames contain `[RR x CC]_C<ch>_z<zzzz>.ome.tif` |
| Visible seams in `stitching.py` output | Linear blending with uneven illumination | Switch to `--method sinusoidal` |
| Tiles appear misaligned after registration | PCC pulled toward a spurious correlation peak | Try reducing `--max_shift`, adjusting `--fudge`, or switching `--ref_channel` to a brighter channel |
| `--mode test` overlay shows red/green fringes even after correction | Overlap percentage is incorrect | Adjust `--overlap` up or down by a few percent and re-test |
| Out-of-memory errors | Large tile grid or high Z-slice count | Process a subset of Z-slices, reduce tile size upstream, or increase system RAM |
| `OSError: N requested and 0 written` | Output disk full or on a throttled network drive | Free disk space or redirect output to a local drive with `--output_dir` |
| `Missing: pip install scikit-image>=0.19` | Old or missing scikit-image | Run `pip install --upgrade scikit-image` |
| `--method diy` is slow | OpenCV not installed | `pip install opencv-python` to enable the fast warpAffine path |

---

## Contact

For questions or issues, please contact the Monje Lab.