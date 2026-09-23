from pathlib import Path
from PIL import Image
import sys

if len(sys.argv) != 3:
    raise SystemExit(
        "Usage: build_scbd_character_atlas_v053.py "
        "<source_sheet.png> <output_atlas.png>"
    )

src = Path(sys.argv[1])
dst = Path(sys.argv[2])
img = Image.open(src).convert("RGBA")
cols, rows = 7, 4

if img.width % cols != 0 or img.height % rows != 0:
    raise SystemExit(
        f"Unexpected sheet size {img.width}x{img.height}; must divide exactly into 7x4 cells"
    )

cell_w = img.width // cols
cell_h = img.height // rows
tile_w, tile_h = 180, 120
atlas = Image.new("RGBA", (tile_w * cols, tile_h * rows), (0, 0, 0, 0))

for row in range(rows):
    for col in range(cols):
        x0 = col * cell_w
        y0 = row * cell_h
        inner_left = x0 + 4
        inner_right = x0 + cell_w - 4
        inner_width = inner_right - inner_left
        crop_h = round(inner_width * 2 / 3)
        top = y0 + 6
        bottom = min(y0 + cell_h - 42, top + crop_h)
        if bottom - top < crop_h:
            top = max(y0 + 4, bottom - crop_h)
        portrait = img.crop((inner_left, top, inner_right, bottom))
        portrait = portrait.resize((tile_w, tile_h), Image.Resampling.LANCZOS)
        atlas.alpha_composite(portrait, (col * tile_w, row * tile_h))

dst.parent.mkdir(parents=True, exist_ok=True)
atlas.save(dst, optimize=True)
print(f"SCBD V0.5.3 atlas created: {dst} {atlas.width}x{atlas.height}, 28 portraits")
