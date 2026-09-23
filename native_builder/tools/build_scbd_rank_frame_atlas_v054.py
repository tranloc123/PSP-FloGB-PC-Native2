from pathlib import Path
from PIL import Image
import numpy as np
import sys

if len(sys.argv) != 3:
    raise SystemExit(
        "Usage: build_scbd_rank_frame_atlas_v054.py "
        "<source_strip.jpg> <output_atlas.png>"
    )

src = Path(sys.argv[1])
dst = Path(sys.argv[2])

img = Image.open(src).convert("RGB")
cols = 7
tile_size = 220
out_h = 220
bounds = [round(i * img.width / cols) for i in range(cols + 1)]

atlas = Image.new("RGBA", (tile_size * cols, out_h), (0, 0, 0, 0))

for i in range(cols):
    tile = img.crop((bounds[i], 0, bounds[i + 1], img.height)).convert("RGBA")
    arr = np.asarray(tile).copy()
    rgb = arr[..., :3].astype(np.float32)

    mx = rgb.max(axis=2)
    mn = rgb.min(axis=2)
    lum = 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]
    sat = mx - mn

    alpha = np.clip((mx - 18.0) * 3.0, 0.0, 255.0)
    alpha *= np.clip((lum - 8.0) / 42.0, 0.0, 1.0)
    alpha = np.maximum(alpha, np.clip((sat - 18.0) * 2.3, 0.0, 220.0))

    h, w = alpha.shape
    yy, xx = np.mgrid[0:h, 0:w]
    cx = w * 0.5
    cy = h * 0.515
    rr = np.sqrt(((xx - cx) / (w * 0.5)) ** 2 + ((yy - cy) / (h * 0.5)) ** 2)

    center_hole = (rr < 0.53) & (yy < h * 0.72)
    alpha[center_hole] = 0.0

    alpha[:, :7] = 0.0
    alpha[:, -7:] = 0.0
    alpha[-8:, :] = 0.0

    arr[..., 3] = np.clip(alpha, 0.0, 255.0).astype(np.uint8)
    rgba = Image.fromarray(arr, "RGBA").resize((tile_size, 206), Image.Resampling.LANCZOS)

    cell = Image.new("RGBA", (tile_size, out_h), (0, 0, 0, 0))
    cell.alpha_composite(rgba, (0, 7))
    atlas.alpha_composite(cell, (i * tile_size, 0))

dst.parent.mkdir(parents=True, exist_ok=True)
atlas.save(dst, optimize=True)

print(
    f"SCBD V0.5.4 tier-frame atlas created: {dst} "
    f"{atlas.width}x{atlas.height}, 7 tiers"
)
