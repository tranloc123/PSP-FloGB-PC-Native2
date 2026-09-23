
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_5_6.py <ppsspp_repo>")

repo = Path(sys.argv[1]).resolve()

def require(rel):
    p = repo / rel
    if not p.exists():
        raise SystemExit(f"Missing expected path: {rel}")
    return p

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 occurrence, found {count}")
    return text.replace(old, new, 1)

debug = require("UI/DebugOverlay.cpp")
info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")
s = debug.read_text(encoding="utf-8")

for marker in (
    "kSCBDRankFrameTuning[7]",
    "avatarDrawRadius",
    "SCBDPreviewRankColor" if "SCBDPreviewRankColor" in s else "DrawSCBDRankNumber",
    "active != 3",
    "slot + 1, true",
):
    if marker not in s:
        raise SystemExit(f"V0.5.5 prerequisite missing: {marker}")

old_tuning = """static const SCBDRankFrameTuning kSCBDRankFrameTuning[7] = {
    {3.25f, -0.0679f, 0.0444f},  // Top 1
    {3.12f, -0.0415f, 0.0444f},  // Top 2
    {3.04f, -0.0193f, 0.0440f},  // Top 3
    {2.92f,  0.0062f, 0.0458f},  // Top 4-10
    {2.88f,  0.0119f, 0.0127f},  // Top 11-30
    {2.84f,  0.0262f, 0.0427f},  // Top 31-70
    {2.80f,  0.0214f, 0.0135f},  // Top 71-100
};
"""
new_tuning = """static const SCBDRankFrameTuning kSCBDRankFrameTuning[7] = {
    {3.35f, 0.0f, 0.0f},  // Top 1
    {3.28f, 0.0f, 0.0f},  // Top 2
    {3.22f, 0.0f, 0.0f},  // Top 3
    {3.12f, 0.0f, 0.0f},  // Top 4-10
    {3.08f, 0.0f, 0.0f},  // Top 11-30
    {3.04f, 0.0f, 0.0f},  // Top 31-70
    {3.00f, 0.0f, 0.0f},  // Top 71-100
};
"""
s = replace_once(s, old_tuning, new_tuning, "clean centered tier-frame tuning")

old_radius = "    const float avatarDrawRadius = showTierFrame ? radius * 0.80f : radius;\n"
if old_radius not in s:
    old_radius = "    const float avatarDrawRadius = showTierFrame ? radius * 0.80f : radius;\n"
s = replace_once(
    s,
    old_radius,
    "    const float avatarDrawRadius = showTierFrame ? radius * 0.78f : radius;\n",
    "avatar inset for new ornate frames",
)

# Add preview-like Top1/2/3 colors if not already present.
if "static uint32_t SCBDPreviewRankColor" not in s:
    anchor = "static void DrawSCBDRankNumber(\n"
    helper = """static uint32_t SCBDPreviewRankColor(int rank) {
    if (rank == 1) return 0xFF55C8FF;
    if (rank == 2) return 0xFFF2ECE4;
    if (rank == 3) return 0xFF5A91D8;
    return 0xFFFFF2E8;
}

static uint32_t SCBDPreviewRowColor(int rank, int rowIndex) {
    if (rank == 1) return 0x30234B68;
    if (rank == 2) return 0x302F343A;
    if (rank == 3) return 0x302D2521;
    return (rowIndex % 2) ? 0x8C1D2430 : 0xA8252C38;
}

"""
    s = replace_once(s, anchor, helper + anchor, "insert preview highlight helpers")

old_row = "            const uint32_t rowColor = (i % 2) ? 0x8C1D2430 : 0xA8252C38;\n"
if old_row in s:
    s = replace_once(
        s,
        old_row,
        "            const uint32_t rowColor = SCBDPreviewRowColor(i + 1, i);\n",
        "highlight Top1-3 rows",
    )

old_num = """                active == 2 ? 21.0f : 18.0f,
                0xFFFFD86A
            );
"""
if old_num in s:
    new_num = """                active == 2 ? 21.0f : 18.0f,
                SCBDPreviewRankColor(i + 1)
            );
"""
    s = replace_once(s, old_num, new_num, "highlight Top1-3 rank numbers")

for req in (
    "{3.35f, 0.0f, 0.0f}",
    "radius * 0.78f",
    "active != 3",
    "slot + 1, true",
):
    if req not in s:
        raise SystemExit(f"V0.5.6 missing marker: {req}")

if "DrawSCBDRankFrame(ctx, i + 1, avatarX, cy, radius);" in s:
    raise SystemExit("Regression: battle Top5 frame came back")

debug.write_text(s, encoding="utf-8")

with info.open("a", encoding="utf-8") as f:
    f.write(
        "\nPSP Live FloGB V0.5.6 Clean Rank Frames Preview Match\n"
        "New rank-frame atlas uses native RGBA transparency; no background-removal step\n"
        "All 7 frame openings are recentered before atlas packing\n"
        "Transparent gutter prevents texture bleeding between atlas cells\n"
        "Top1/Top2/Top3 preview-style highlight preserved\n"
        "Battle Top5 and Win Streak remain frame-free\n"
    )

print("PSP Live FloGB V0.5.6 patch applied successfully.")
