# Monje Lab 2D Image Stitching Script

## Overview

This script automatically stitches OME-TIFF image tiles into full 2D images per Z-slice and channel. It is designed for high-content microscopy datasets with overlapping tiles, multiple channels, and multiple Z-slices.

The workflow is as follows:

1. Detect all tiles in the input folder.
2. Parse their filenames to extract grid position, channel, and Z-slice.
3. Stitch each row of tiles horizontally using overlap blending (feathered ramp).
4. Stitch rows vertically using independent vertical blending.
5. Save one stitched 2D TIFF per Z-slice per channel.

---

## Assumptions

- Tiles are saved as OME-TIFF (`*.ome.tif`) images.
- Filenames must contain this suffix:

```
[RR x CC]_C[channel]_z[ZSLICE].ome.tif
```

The prefix before `[RR x CC]` can be anything and is ignored. Example:

```
260128_UltraII_5300148-2R_AF_HNACy3_cfos_2x_thickness3d5_width60_20ol_10umstep[00 x 00]_C00_z0100.ome.tif
```

Where:

| Part          | Meaning                             |
| ------------- | ----------------------------------- |
| `PREFIX`      | Any string — not parsed or required |
| `[row x col]` | Tile row and column (zero-indexed)  |
| `C[channel]`  | Channel number (integer)            |
| `z[ZSLICE]`   | Z-slice number (integer)            |

- All tiles for the same Z-slice and channel form a regular rectangular grid.
- Overlap is provided by the user as a CLI argument (not inferred from the filename).

---

## Inputs

| Argument      | Required              | Description                                                                                      |
| ------------- | --------------------- | ------------------------------------------------------------------------------------------------ |
| `--input_dir` | Yes                   | Folder containing OME-TIFF tiles                                                                 |
| `--overlap`   | Yes                   | Tile overlap as an integer percentage (e.g. `20` for 20%)                                        |
| `--method`    | No (default: `weighted`) | Overlap blending method: `weighted`, `sinusoidal`, `average`, or `majority`                   |

---

## Outputs

- One stitched 2D TIFF per Z-slice per channel, saved in `--input_dir` as:

```
stitched_z0100_C00.tif
stitched_z0100_C01.tif
stitched_z0100_C02.tif
stitched_z0101_C00.tif
...
```

- Console prints showing detected grid size, Z-slices, channels, overlap, and blend method.

---

## How It Works

1. **Tile Detection & Parsing**
   - The script reads all files in the input folder ending with `.ome.tif`.
   - Filenames are parsed using a regex anchored to the suffix `[RR x CC]_C<ch>_z<zzzz>.ome.tif`. The prefix is ignored entirely.
   - Tiles are organized in a dictionary keyed by `(row, col, z, channel)`.

2. **Row Stitching (Horizontal)**
   - Each row of tiles is stitched horizontally.
   - Overlapping regions between adjacent tiles are blended using the selected method.
   - For `weighted` and `sinusoidal`, the blending ramp matches the exact overlap width in pixels.

3. **Column Stitching (Vertical)**
   - Stitched rows are then stitched vertically.
   - Vertical overlaps are blended independently using a vertical ramp of exact overlap height in pixels.

4. **Z-slice and Channel Handling**
   - All Z-slices are processed independently.
   - For each Z-slice, every channel is stitched and saved as its own 2D TIFF.

---

## Example Usage

```bash
python stitch_3d.py \
    --input_dir "/Users/spaltahill/test_images" \
    --overlap 20 \
    --method sinusoidal
```

Output files saved in the same folder:

```
stitched_z0100_C00.tif
stitched_z0100_C01.tif
stitched_z0101_C00.tif
stitched_z0101_C01.tif
...
```

---

## Blending Methods

| Method        | Ramp Shape          | Best For                                                                 |
| ------------- | ------------------- | ------------------------------------------------------------------------ |
| `weighted`    | Linear              | Fast, general-purpose; slight brightness kink at seam edges              |
| `sinusoidal`  | Raised cosine (S-curve) | **Recommended.** Smooth seams with zero-slope endpoints; best for tiles with uneven illumination or vignetting |
| `average`     | Flat 50/50          | Faster but can reduce intensity at seams                                 |
| `majority`    | Max value           | Sparse bright features, binary masks                                     |

### Sinusoidal blending detail

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

---

## Dependencies

- Python 3.8+
- numpy
- Pillow (`pip install Pillow`)
- tifffile (`pip install tifffile`)

---

## Troubleshooting

- **"No matching OME-TIFF tiles found"** — Verify your filenames contain the expected suffix `[RR x CC]_C<ch>_z<zzzz>.ome.tif`.
- **Seams visible** — Switch to `sinusoidal` for the smoothest transitions; `average` and `majority` may produce visible seams.
- **Out-of-memory errors** — Reduce image size, process subsets of Z-slices, or increase system RAM.

---

## Contact

For questions or issues, please contact the Monje Lab.
