import numpy as np
import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.patches as mpatches


def save_grid_overlay(pos, tile_h, tile_w,
                      n_rows, n_cols,
                      z, out_path):

    p = pos.copy()

    # shift to positive coordinates
    p[:, :, 0] -= p[:, :, 0].min()
    p[:, :, 1] -= p[:, :, 1].min()

    H = int(np.ceil(p[:, :, 0].max())) + tile_h
    W = int(np.ceil(p[:, :, 1].max())) + tile_w

    fig, ax = plt.subplots(
        figsize=(max(6, W // 200),
                 max(4, H // 200))
    )

    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)

    ax.set_aspect("equal")

    ax.set_title(f"Tile grid overlay — Z {z:04d}")

    ax.set_xlabel("x (px)")
    ax.set_ylabel("y (px)")

    cmap = matplotlib.colormaps["tab10"].resampled(n_rows)

    for r in range(n_rows):
        for c in range(n_cols):

            y0 = p[r, c, 0]
            x0 = p[r, c, 1]

            rect = mpatches.Rectangle(
                (x0, y0),
                tile_w,
                tile_h,
                linewidth=1.0,
                edgecolor=cmap(r),
                facecolor=(*cmap(r)[:3], 0.08),
            )

            ax.add_patch(rect)

            ax.text(
                x0 + tile_w / 2,
                y0 + tile_h / 2,
                f"({r},{c})",
                ha="center",
                va="center",
                fontsize=6,
                color=cmap(r),
            )

    plt.tight_layout()

    fig.savefig(out_path, dpi=150)

    plt.close(fig)

    print(f"  Grid overlay saved: {out_path}")