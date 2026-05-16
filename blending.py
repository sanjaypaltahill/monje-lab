"""
blending.py — Monje Lab Stitcher
==================================
Blending primitives for tile stitching.

Public API
----------
stitch_pair(img_a, img_b, overlap_px, axis)
    Stitch two images along the given axis using average blending.
    axis="h" → horizontal join (img_a left, img_b right)
    axis="v" → vertical   join (img_a top,  img_b bottom)

All internal helpers (padding, blend kernels) are private.
"""

import numpy as np


# ─────────────────────────────────────────────
#  BLEND KERNELS
# ─────────────────────────────────────────────

def _blend_average(strip_a, strip_b):
    """Simple 50/50 average of two equal-shaped strips."""
    return 0.5 * (strip_a + strip_b)


def _blend_sinusoidal(strip_a, strip_b, axis):
    """
    Raised-cosine blend: weight goes 1→0 across the overlap (a→b).

    Zero-pixel mask: if one tile contributes zero at a pixel, full
    weight is given to the other tile — prevents seam darkening at
    padded edges.

    axis : "h" → ramp along columns (horizontal seam)
           "v" → ramp along rows    (vertical seam)
    """
    n = strip_a.shape[1] if axis == "h" else strip_a.shape[0]
    t = np.linspace(0.0, 1.0, n, dtype=np.float32)  # 0→1
    w = 0.5 * (1.0 + np.cos(np.pi * t))              # 1→0

    if axis == "h":
        ramp = np.broadcast_to(w, strip_a.shape).copy()
    else:
        ramp = np.broadcast_to(w[:, None], strip_a.shape).copy()

    ramp[strip_a == 0] = 0.0
    ramp[strip_b == 0] = 1.0
    return ramp * strip_a + (1.0 - ramp) * strip_b


# ─────────────────────────────────────────────
#  PADDING HELPERS
# ─────────────────────────────────────────────

def _pad_to_same_height(img_a, img_b):
    """Bottom-pad the shorter image so both have the same row count."""
    ha, hb = img_a.shape[0], img_b.shape[0]
    if ha == hb:
        return img_a, img_b
    target = max(ha, hb)
    if ha < target:
        img_a = np.pad(img_a, ((0, target - ha), (0, 0)), constant_values=0)
    else:
        img_b = np.pad(img_b, ((0, target - hb), (0, 0)), constant_values=0)
    return img_a, img_b


def _pad_to_same_width(img_a, img_b):
    """Right-pad the narrower image so both have the same column count."""
    wa, wb = img_a.shape[1], img_b.shape[1]
    if wa == wb:
        return img_a, img_b
    target = max(wa, wb)
    if wa < target:
        img_a = np.pad(img_a, ((0, 0), (0, target - wa)), constant_values=0)
    else:
        img_b = np.pad(img_b, ((0, 0), (0, target - wb)), constant_values=0)
    return img_a, img_b


# ─────────────────────────────────────────────
#  UNIFIED STITCH PRIMITIVE
# ─────────────────────────────────────────────

def stitch_pair(img_a, img_b, overlap_px, axis, blend="average"):
    """
    Stitch two images along *axis* with blending in the overlap zone.

    Parameters
    ----------
    img_a : 2-D float32 array
        The "anchor" image — left tile (axis="h") or top tile (axis="v").
    img_b : 2-D float32 array
        The "incoming" image — right tile (axis="h") or bottom tile (axis="v").
    overlap_px : int
        Width/height of the overlap region in pixels.
    axis : "h" | "v"
        "h" → horizontal join  (img_a left,  img_b right)
        "v" → vertical   join  (img_a top,   img_b bottom)
    blend : "average" | "sinusoidal"
        Blend kernel to apply inside the overlap zone.

    Returns
    -------
    result : 2-D float32 array — the stitched image.
    """
    if axis == "h":
        # Match heights before joining
        img_a, img_b = _pad_to_same_height(img_a, img_b)
        overlap_px = min(overlap_px, img_a.shape[1], img_b.shape[1])

        body_a  = img_a[:,  :-overlap_px]
        strip_a = img_a[:,  -overlap_px:]
        strip_b = img_b[:, :overlap_px]
        body_b  = img_b[:, overlap_px:]

        if blend == "sinusoidal":
            blended = _blend_sinusoidal(strip_a, strip_b, axis="h")
        else:
            blended = _blend_average(strip_a, strip_b)

        result = np.concatenate([body_a, blended, body_b], axis=1)

    elif axis == "v":
        # Match widths before joining
        img_a, img_b = _pad_to_same_width(img_a, img_b)
        overlap_px = min(overlap_px, img_a.shape[0], img_b.shape[0])

        body_a  = img_a[:-overlap_px, :]
        strip_a = img_a[-overlap_px:, :]
        strip_b = img_b[:overlap_px,  :]
        body_b  = img_b[overlap_px:,  :]

        if blend == "sinusoidal":
            blended = _blend_sinusoidal(strip_a, strip_b, axis="v")
        else:
            blended = _blend_average(strip_a, strip_b)

        result = np.concatenate([body_a, blended, body_b], axis=0)

    else:
        raise ValueError(f"axis must be 'h' or 'v', got {axis!r}")

    print(f"      stitch_{axis}: {img_a.shape} + {img_b.shape}, "
          f"overlap={overlap_px} → {result.shape}")
    return result
