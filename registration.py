"""
registration.py — Monje Lab Stitcher
======================================
Phase-cross-correlation shift estimation and per-join correction extraction.

Key design decisions
---------------------
* The PCC search strip is widened by *fudge* pixels beyond the nominal
  overlap region so that genuine mis-registrations slightly outside the
  expected overlap are still found.  Only the strip taken from the
  *reference* tile is widened; the moving strip stays at overlap_px so
  both arrays remain the same size (equal-size PCC avoids the artificial
  DC component that arises from zero-padding one side).

* normalization=None throughout — avoids amplifying noise in low-signal
  (near-blank) regions that the "phase" normalisation causes.

* max_shift is enforced: if |detected shift| exceeds max_shift in either
  component, both components are zeroed and a warning is printed, which
  prevents one bad PCC result from accumulating into a large positional
  error.

Fudge convention
----------------
  estimate_shift_horizontal:
      ref strip  = rightmost (overlap_px + fudge) columns of tile A
      moving strip = leftmost  overlap_px            columns of tile B
      → ref is wider; the extra fudge columns give PCC room to find
        a sub-nominal overlap.  The resulting dx correction already
        accounts for this — a positive fudge shift moves B left.

  estimate_shift_vertical (symmetric):
      ref strip  = bottom (overlap_px + fudge) rows of tile A
      moving strip = top   overlap_px             rows of tile B
"""

import warnings
import numpy as np

from skimage.registration import phase_cross_correlation
from skimage.transform import AffineTransform, warp
from io_utils import load_tile


# ─────────────────────────────────────────────
#  INTERNAL PCC WRAPPER
# ─────────────────────────────────────────────

def _pcc(ref, moving, upsample):
    """
    Run phase_cross_correlation(ref, moving) with normalization=None.

    Pads *moving* to match *ref* shape when they differ (fudge case).
    Returns (dy, dx, error).
    """
    if ref.shape != moving.shape:
        # Pad moving to ref shape (bottom / right zero-padding only)
        pad_h = ref.shape[0] - moving.shape[0]
        pad_w = ref.shape[1] - moving.shape[1]
        moving = np.pad(moving,
                        ((0, max(pad_h, 0)), (0, max(pad_w, 0))),
                        constant_values=0)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        shift, error, _ = phase_cross_correlation(
            ref, moving,
            upsample_factor=upsample,
            normalization=None,
        )
    return float(shift[0]), float(shift[1]), float(error)


# ─────────────────────────────────────────────
#  SHIFT ESTIMATION
# ─────────────────────────────────────────────

def estimate_shift_horizontal(img_a, img_b, overlap_px,
                               fudge=100, upsample=10, max_shift=50):
    """
    Estimate (dy, dx) to align tile B's left edge with tile A's right edge.

    ref    = rightmost (overlap_px + fudge) columns of tile A
    moving = leftmost   overlap_px          columns of tile B

    The ref strip is wider by *fudge* pixels, giving PCC search room
    beyond the exact nominal overlap boundary.

    Returns
    -------
    dy, dx : float
        Shift to apply to tile B to align it with tile A.
        Positive dy → tile B sits lower than expected.
        Positive dx → tile B sits further right than expected.
    """
    h_a, w_a = img_a.shape
    h_b, w_b = img_b.shape

    ref_cols    = min(overlap_px + fudge, w_a)
    moving_cols = min(overlap_px, w_b)
    rows        = min(h_a, h_b)

    ref_strip    = img_a[:rows, -ref_cols:]    # right edge of A (wider)
    moving_strip = img_b[:rows, :moving_cols]  # left  edge of B

    if ref_strip.std() < 1e-3 or moving_strip.std() < 1e-3:
        print("    Warning: blank strip — using (dy=0, dx=0).")
        return 0.0, 0.0

    dy, dx, error = _pcc(ref_strip, moving_strip, upsample)

    # If fudge widened the ref, the raw dx is measured relative to the
    # wider ref origin.  Subtract fudge to bring it back to overlap_px coords.
    dx -= (ref_cols - moving_cols)

    print(f"    PCC horizontal: dy={dy:+.2f}, dx={dx:+.2f}, error={error:.4f}  "
          f"[overlap={overlap_px}, fudge={fudge}]")

    dy, dx = _clamp_shift(dy, dx, max_shift, "horizontal")
    return dy, dx


def estimate_shift_vertical(img_a, img_b, overlap_px,
                              fudge=100, upsample=10, max_shift=50):
    """
    Estimate (dy, dx) to align tile B's top edge with tile A's bottom edge.

    ref    = bottom (overlap_px + fudge) rows of tile A
    moving = top     overlap_px          rows of tile B

    Returns
    -------
    dy, dx : float
        Shift to apply to tile B to align it with tile A.
        Positive dy → tile B sits lower than expected.
        Positive dx → tile B drifts right of expected.
    """
    h_a, w_a = img_a.shape
    h_b, w_b = img_b.shape

    ref_rows    = min(overlap_px + fudge, h_a)
    moving_rows = min(overlap_px, h_b)
    cols        = min(w_a, w_b)

    ref_strip    = img_a[-ref_rows:, :cols]    # bottom edge of A (wider)
    moving_strip = img_b[:moving_rows, :cols]  # top    edge of B

    if ref_strip.std() < 1e-3 or moving_strip.std() < 1e-3:
        print("    Warning: blank strip — using (dy=0, dx=0).")
        return 0.0, 0.0

    dy, dx, error = _pcc(ref_strip, moving_strip, upsample)

    # Correct for fudge offset in the vertical direction
    dy -= (ref_rows - moving_rows)

    print(f"    PCC vertical:   dy={dy:+.2f}, dx={dx:+.2f}, error={error:.4f}  "
          f"[overlap={overlap_px}, fudge={fudge}]")

    dy, dx = _clamp_shift(dy, dx, max_shift, "vertical")
    return dy, dx


def _clamp_shift(dy, dx, max_shift, label):
    """
    If either component exceeds max_shift, zero both and warn.
    """
    if abs(dy) > max_shift or abs(dx) > max_shift:
        print(
            f"    WARNING [{label}]: shift (dy={dy:+.1f}, dx={dx:+.1f}) "
            f"exceeds max_shift={max_shift} — correction set to (0, 0)."
        )
        return 0, 0
    return dy, dx


# ─────────────────────────────────────────────
#  WARP
# ─────────────────────────────────────────────

def apply_shift_skimage(img, dy, dx, output_shape):
    """
    Pure-translation warp via skimage AffineTransform.

    skimage convention: translation=(x_shift, y_shift) = (dx, dy).
    Used only by test_mode diagnostics (not the main stitching path).
    """
    tform = AffineTransform(translation=(dx, dy))
    warped = warp(
        img,
        inverse_map=tform.inverse,
        output_shape=output_shape,
        order=1,
        mode="constant",
        cval=0.0,
        preserve_range=True,
    )
    return warped.astype(np.float32)
