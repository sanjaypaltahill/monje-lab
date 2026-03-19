# Monje Lab — 2D Image Stitching Script

> Automatic OME-TIFF tile stitching for high-content fluorescence microscopy

---

## Overview

This script automatically stitches OME-TIFF image tiles into full 2D images per Z-slice and channel. It is designed for high-content microscopy datasets with overlapping tiles, multiple channels, and multiple Z-slices.

The workflow proceeds as follows:

1. Detect all tiles in the input folder.
2. Parse filenames to extract grid position, channel, and Z-slice.
3. Stitch each row of tiles horizontally using overlap blending (feathered ramp).
4. Stitch rows vertically using independent vertical blending.
5. Save one stitched 2D TIFF per Z-slice per channel, organized into per-channel subfolders.

---

## Assumptions

- Tiles are saved as OME-TIFF (`*.ome.tif`) images.
- Filenames must contain this suffix:

```
[RR x CC]_C[channel]_z[ZSLICE].ome.tif
```

The prefix before `[RR x CC]` can be anything and is captured to name the output folder. Example:

```
260128_UltraII_5300148-2R_AF_HNACy3_cfos_2x_thickness3d5_width60_20ol_10umstep[00 x 00]_C00_z0100.ome.tif
```

| Part | Meaning |
|------|---------|
| `PREFIX` | Any string — captured and used to name the output parent folder |
| `[row x col]` | Tile row and column (zero-indexed) |
| `C[channel]` | Channel number (integer) |
| `z[ZSLICE]` | Z-slice number (integer) |

- All tiles for the same Z-slice and channel form a regular rectangular grid.
- Overlap is provided by the user as a CLI argument (not inferred from the filename).

---

## Inputs

| Argument | Required | Description |
|----------|----------|-------------|
| `--input_dir` | Yes | Folder containing OME-TIFF tiles |
| `--output_dir` | No | Root folder for stitched output. A sub-folder named after the filename prefix is created here. Defaults to `input_dir` if not set. |
| `--overlap` | Yes | Tile overlap as an integer percentage (e.g. `20` for 20%) |
| `--method` | No (default: `weighted`) | Overlap blending method: `weighted`, `sinusoidal`, `average`, or `majority` |

---

## Outputs

One stitched 2D TIFF is saved per Z-slice per channel. Output files are organized into per-channel subfolders inside a parent folder named after the filename prefix:

```
output_dir/
  260128_UltraII_5300148/        ← named from filename prefix
    Channel 0/
      stitched_z0100_C00.tif
      stitched_z0101_C00.tif
      ...
    Channel 1/
      stitched_z0100_C01.tif
      stitched_z0101_C01.tif
      ...
```

The console will also print detected grid size, Z-slices, channels, prefix, overlap, and blend method.

---

## Example Usage

```bash
python stitch_3d.py \
    --input_dir  "/Users/spaltahill/test_images" \
    --output_dir "/Users/spaltahill/stitched_output" \
    --overlap 20 \
    --method sinusoidal
```

---

## How It Works

### 1. Tile Detection & Parsing
- The script reads all files in the input folder ending with `.ome.tif`.
- Filenames are parsed using a regex anchored to the suffix `[RR x CC]_C<ch>_z<zzzz>.ome.tif`.
- The prefix (everything before `[RR x CC]`) is captured, stripped of trailing underscores/spaces, and used to name the parent output folder.
- Tiles are organized in a dictionary keyed by `(row, col, z, channel)`.

### 2. Row Stitching (Horizontal)
- Each row of tiles is stitched horizontally.
- Overlapping regions between adjacent tiles are blended using the selected method.
- For `weighted` and `sinusoidal`, the blending ramp matches the exact overlap width in pixels.

### 3. Column Stitching (Vertical)
- Stitched rows are then stitched vertically.
- Vertical overlaps are blended independently using a vertical ramp of exact overlap height in pixels.

### 4. Z-slice and Channel Handling
- All Z-slices are processed independently.
- For each Z-slice, every channel is stitched and saved as its own 2D TIFF inside its channel subfolder.

---

## Blending Methods

| Method | Ramp Shape | Best For |
|--------|------------|----------|
| `weighted` | Linear | Fast, general-purpose; slight brightness kink at seam edges |
| `sinusoidal` | Raised cosine (S-curve) | **Recommended.** Smooth seams with zero-slope endpoints; best for tiles with uneven illumination or vignetting |
| `average` | Flat 50/50 | Faster but can reduce intensity at seams |
| `majority` | Max value | Sparse bright features, binary masks |

### Sinusoidal Blending — Detail

The `sinusoidal` method uses a **raised-cosine ramp**:

```
w(t) = 0.5 × (1 + cos(π·t)),   t ∈ [0, 1]
```

This S-curve transitions from 1 to 0 with **zero slope at both endpoints**, unlike the linear `weighted` ramp which has a constant non-zero slope all the way to the edge. The zero-slope boundaries mean brightness changes are imperceptible at seam edges, suppressing the faint grid artefacts that can appear when tiles have illumination gradients (e.g. objective vignetting).

---

## Notes / Tips

- The script assumes all tiles are the same size.
- Overlap is interpreted as a percentage of tile width/height.
- If the filename suffix does not match `[RR x CC]_C<ch>_z<zzzz>.ome.tif`, the tile is silently ignored.
- `sinusoidal` blending is recommended as the default for fluorescence microscopy data.
- Channel subfolders (`Channel 0`, `Channel 1`, etc.) are created automatically inside the prefix-named parent folder; no manual setup needed.

---

## Dependencies

- Python 3.8+
- `numpy`
- `Pillow` — `pip install Pillow`
- `tifffile` — `pip install tifffile`

---

## Troubleshooting

| Error / Symptom | Fix |
|-----------------|-----|
| `"No matching OME-TIFF tiles found"` | Verify filenames contain the expected suffix `[RR x CC]_C<ch>_z<zzzz>.ome.tif` |
| Seams visible in output | Switch to `sinusoidal` for smoothest transitions; `average` and `majority` may produce visible seams |
| Out-of-memory errors | Reduce image size, process subsets of Z-slices, or increase system RAM |
| `OSError: N requested and 0 written` | Output disk is full or target folder is on a throttled network/cloud-synced drive. Free up space or redirect output to a local directory with `--output_dir` |

---

## Contact

For questions or issues, please contact the Monje Lab.