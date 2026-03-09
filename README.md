# Monje Lab 2D and 3D Image Stitching Script

## Overview

This script automatically stitches OME-TIFF image tiles into full 2D images per Z-slice and optionally stacks them into a single 3D image. It is designed for high-content microscopy datasets with overlapping tiles and multiple Z-slices.

The workflow is as follows:

1. Detect all tiles in the input folder.
2. Parse their filenames to extract grid position, channel, Z-slice, and overlap fraction.
3. Stitch each row of tiles horizontally using overlap blending (feathered ramp).
4. Stitch rows vertically using independent vertical blending.
5. Save each stitched Z-slice individually.
6. Optionally stack all stitched Z-slices into a single 3D TIFF file.

---

## Assumptions

- Tiles are saved as OME-TIFF (`*.ome.tif`) images.
- Filenames follow this pattern:

```
PREFIX[row x col]_C[channel]_z[ZSLICE]_[OL]ol.ome.tif
```

Example:

```
260128_UltraII_5300148-2R_AF_HNACy3_cfos_2x_thickness3d5_width60_20ol_10umstep[00 x 00]_C00_z0100.ome.tif
```

Where:

| Part          | Meaning                                    |
| ------------- | ------------------------------------------ |
| `PREFIX`      | Any string describing the dataset          |
| `[row x col]` | Tile row and column (zero-indexed)         |
| `C[channel]`  | Channel number (integer)                   |
| `z[ZSLICE]`   | Z-slice number (integer)                   |
| `[OL]ol`      | Overlap percentage (optional, default 20%) |

- All tiles for the same Z-slice and channel share the same `PREFIX` and overlap fraction.
- Tiles form a regular rectangular grid (all rows have the same number of tiles, all columns have the same number of tiles).

---

## Inputs

- `--input_dir`: Folder containing OME-TIFF tiles.
- `--method` (optional): Overlap blending method for stitching overlaps. Options:
  - `weighted` (default) — linear ramp blending using the **exact detected overlap** in pixels
  - `average` — simple average
  - `majority` — take maximum intensity
- `--output` (optional): Output path for the final stitched 3D image. Individual Z-slices are also saved in the same folder.

---

## Outputs

- One stitched 2D TIFF per Z-slice (saved as `stitched_z####.tif`).
- One combined 3D TIFF containing all Z-slices (saved at `--output` path).
- Console prints showing:
  - Detected grid size (rows × columns)
  - Filename prefix, Z-slice, and channel
  - Overlap fraction and blending method
  - Which files are being stitched together

---

## How It Works

1. **Tile Detection & Parsing**
   - The script reads all files in the input folder ending with `.ome.tif`.
   - Filenames are parsed using a regex to extract:
     - Tile row and column
     - Channel number
     - Z-slice
     - Overlap fraction (optional)
   - Tiles are organized in a dictionary by `(row, col)` for each Z-slice.

2. **Row Stitching (Horizontal)**
   - Each row of tiles is stitched horizontally.
   - Overlapping regions between adjacent tiles are blended using the selected method.
   - For `weighted`, the blending ramp matches the **exact overlap width in pixels**.

3. **Column Stitching (Vertical)**
   - Stitched rows are stitched vertically.
   - Vertical overlaps are blended independently using a vertical ramp of **exact overlap height in pixels**.

4. **Z-slice Handling**
   - All Z-slices are processed independently.
   - Each stitched Z-slice is saved individually as a 2D TIFF.

5. **3D Stacking**
   - All stitched Z-slices are stacked along the Z-axis to form a 3D image.
   - The final 3D image is saved at the `--output` path.

---

## Example Usage

```bash
# Stitch images using weighted blending and save output
python stitch_3D.py \
    --input_dir "/Users/spaltahill/test_images" \
    --method weighted \
    --output "/Users/spaltahill/test_images/stitched_output_3D.tif"
```

- Individual stitched Z-slices will be saved in the same folder as:

```
stitched_z0000.tif
stitched_z0001.tif
stitched_z0002.tif
...
```

- The final 3D TIFF is saved at `/Users/spaltahill/test_images/stitched_output_3D.tif`.

---

## Notes / Tips

- The script assumes all tiles are the same size.
- Overlap fractions are interpreted as a percentage of tile width/height.
- If the filename pattern does not match, the tile is ignored.
- Weighted feathering is now applied **precisely** using the overlap pixels, producing smoother, seam-free stitching.
- You can choose different blending methods depending on signal quality:
  - `weighted` usually preserves smooth transitions
  - `average` is faster but can dim intensity
  - `majority` works well for sparse, bright features

---

## Dependencies

- Python 3.8+
- numpy
- Pillow (`pip install Pillow`)
- tifffile (`pip install tifffile`)

---

## Troubleshooting

- **"No matching OME-TIFF tiles found"** Ensure your filenames match the expected pattern. Adjust the regex in `parse_filename()` if needed.
- **Seams visible**: Make sure `weighted` method is used; older `average` or `majority` methods will produce visible seams.
- **Out-of-memory errors**: Reduce image size, process subsets of tiles, or increase system RAM.

---

## Contact

For questions or issues, please contact the Monje Lab.

