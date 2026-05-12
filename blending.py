"""
blending.py — Monje Lab Stitcher
==================================
Raised-cosine (sinusoidal) blending primitives and zero-padding helpers.
These functions are stable and unlikely to need frequent edits.
"""

import numpy as np


# ─────────────────────────────────────────────
#  PADDING HELPERS
# ─────────────────────────────────────────────

def pad_to_same_width(img_a, img_b):
    """Right-pad the narrower image so both share the same column count."""
    wa, wb = img_a.shape[1], img_b.shape[1]
    if wa == wb:
        return img_a, img_b
    target = max(wa, wb)

    def _pad(img, w):
        return np.pad(img, ((0, 0), (0, target - w)), constant_values=0)

    return _pad(img_a, wa), _pad(img_b, wb)


def pad_to_same_height(img_a, img_b):
    """Bottom-pad the shorter image so both share the same row count."""
    ha, hb = img_a.shape[0], img_b.shape[0]
    if ha == hb:
        return img_a, img_b
    target = max(ha, hb)

    def _pad(img, h):
        return np.pad(img, ((0, target - h), (0, 0)), constant_values=0)

    return _pad(img_a, ha), _pad(img_b, hb)


# ─────────────────────────────────────────────
#  SINUSOIDAL BLENDING
# ─────────────────────────────────────────────

def blend_sinusoidal_x(left_ol, right_ol):
    """
    Raised-cosine blend along the horizontal axis.

    w(t) = 0.5·(1 + cos(π·t)), t ∈ [0,1]  →  weight goes 1→0 (left→right).

    Zero-pixel masks: pixels that are zero in one tile hand their full weight
    to the other tile, preventing the seam from darkening at padded edges.

    Both strips must have the same shape (H, overlap_px).
    """
    h, n = left_ol.shape
    t    = np.linspace(0.0, 1.0, n, dtype=np.float32)
    row  = 0.5 * (1.0 + np.cos(np.pi * t))           # (n,) — 1→0
    ramp = np.broadcast_to(row, (h, n)).copy()         # (H, n) writeable

    ramp[left_ol  == 0] = 0.0
    ramp[right_ol == 0] = 1.0
    return ramp * left_ol + (1.0 - ramp) * right_ol


def blend_sinusoidal_y(top_ol, bot_ol):
    """
    Raised-cosine blend along the vertical axis.

    Same weighting curve as blend_sinusoidal_x, applied row-wise.
    Both strips must have the same shape (overlap_px, W).
    """
    n, w = top_ol.shape
    t    = np.linspace(0.0, 1.0, n, dtype=np.float32)
    col  = 0.5 * (1.0 + np.cos(np.pi * t))            # (n,) — 1→0
    ramp = np.broadcast_to(col[:, None], (n, w)).copy()  # (n, W) writeable

    ramp[top_ol == 0] = 0.0
    ramp[bot_ol == 0] = 1.0
    return ramp * top_ol + (1.0 - ramp) * bot_ol


# ─────────────────────────────────────────────
#  STITCH PRIMITIVES
# ─────────────────────────────────────────────

def stitch_pair_horizontal(left, right, overlap_px):
    """
    Horizontally join *left* and *right* with sinusoidal blending.

    Heights are matched by bottom-padding the shorter image before blending.
    """
    left, right = pad_to_same_height(left, right)
    h, wl = left.shape
    wr = right.shape[1]
    overlap_px = min(overlap_px, wl, wr)

    left_body  = left[:,  :-overlap_px]
    left_ol    = left[:,  -overlap_px:]
    right_ol   = right[:, :overlap_px]
    right_body = right[:, overlap_px:]

    blended = blend_sinusoidal_x(left_ol, right_ol)
    result  = np.concatenate([left_body, blended, right_body], axis=1)
    print(f"      stitch_h: {left.shape} + {right.shape}, "
          f"overlap={overlap_px} → {result.shape}")
    return result


def stitch_pair_vertical(top, bottom, overlap_px):
    """
    Vertically join *top* and *bottom* with sinusoidal blending.

    Widths are matched by right-padding the narrower image before blending.
    """
    top, bottom = pad_to_same_width(top, bottom)
    ht = top.shape[0]
    hb = bottom.shape[0]
    overlap_px = min(overlap_px, ht, hb)

    top_body   = top[:-overlap_px, :]
    top_ol     = top[-overlap_px:, :]
    bottom_ol  = bottom[:overlap_px, :]
    bottom_body = bottom[overlap_px:, :]

    top_ol, bottom_ol = pad_to_same_height(top_ol, bottom_ol)
    blended = blend_sinusoidal_y(top_ol, bottom_ol)
    result  = np.concatenate([top_body, blended, bottom_body], axis=0)
    print(f"      stitch_v: {top.shape} + {bottom.shape}, "
          f"overlap={overlap_px} → {result.shape}")
    return result
