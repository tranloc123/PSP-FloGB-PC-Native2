from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_5_4.py <ppsspp_repo>")

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
    "DrawSCBDTransparentTop5List",
    "DrawSCBDRankAvatar",
    "GetSCBDCharacterPortraitAtlas",
    "character_portraits_atlas.png",
    "Approved Top Character layout",
):
    if marker not in s:
        raise SystemExit(f"V0.5.3 prerequisite missing: {marker}")

frame_helper = r'''static Draw::Texture *g_scbdRankFrameAtlas = nullptr;
static bool g_scbdRankFrameAtlasAttempted = false;

static int SCBDRankFrameTierIndex(int rank) {
    if (rank <= 1) return 0;
    if (rank == 2) return 1;
    if (rank == 3) return 2;
    if (rank <= 10) return 3;
    if (rank <= 30) return 4;
    if (rank <= 70) return 5;
    return 6;
}

static Draw::Texture *GetSCBDRankFrameAtlas(UIContext *ctx) {
    if (!g_scbdRankFrameAtlas && !g_scbdRankFrameAtlasAttempted) {
        g_scbdRankFrameAtlasAttempted = true;
        g_scbdRankFrameAtlas = CreateTextureFromFile(
            ctx->GetDrawContext(),
            "scbd/rank_frames/rank_frames_atlas.png",
            ImageFileType::PNG,
            false,
            2048,
            512
        );
    }
    return g_scbdRankFrameAtlas;
}

static float SCBDRankFrameSize(float avatarRadius, int rank) {
    if (rank == 1) return avatarRadius * 3.40f;
    if (rank == 2) return avatarRadius * 3.25f;
    if (rank == 3) return avatarRadius * 3.15f;
    return avatarRadius * 3.00f;
}

static void DrawSCBDRankFrame(
    UIContext *ctx,
    int rank,
    float cx,
    float cy,
    float avatarRadius
) {
    Draw::Texture *atlas = GetSCBDRankFrameAtlas(ctx);
    if (!atlas)
        return;

    constexpr int kTierCount = 7;
    const int tier = SCBDRankFrameTierIndex(rank);
    const float u1 = static_cast<float>(tier) / static_cast<float>(kTierCount);
    const float u2 = static_cast<float>(tier + 1) / static_cast<float>(kTierCount);
    const float size = SCBDRankFrameSize(avatarRadius, rank);

    ctx->Flush();
    ctx->Begin();
    ctx->GetDrawContext()->BindTexture(0, atlas);
    ctx->Draw()->DrawTexRect(
        cx - size * 0.5f,
        cy - size * 0.5f,
        cx + size * 0.5f,
        cy + size * 0.5f,
        u1, 0.0f, u2, 1.0f,
        0xFFFFFFFF
    );
    ctx->Flush();
    ctx->RebindTexture();
    ctx->BindFontTexture();
}

'''

anchor = "static void DrawSCBDTransparentTop5List(\n"
if s.count(anchor) != 1:
    raise SystemExit(f"V0.5.4 Top5 anchor count = {s.count(anchor)}")
s = s.replace(anchor, frame_helper + anchor, 1)

battle_anchor = '''    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();

    for (int i = 0; i < SCBD_TOP5_LIMIT; ++i) {
'''
battle_new = '''    ctx->Flush();
    for (int i = 0; i < SCBD_TOP5_LIMIT; ++i) {
        const float cy = y + rowH * i + rowH * 0.5f;
        const float radius = avatarSize * 0.5f;
        DrawSCBDRankFrame(ctx, i + 1, avatarX, cy, radius);
    }

    ctx->Begin();
    ctx->BindFontTexture();

    for (int i = 0; i < SCBD_TOP5_LIMIT; ++i) {
'''
s = replace_once(s, battle_anchor, battle_new, "add tier frames to battle Top5")

old_top_color = '''static uint32_t SCBDTopRankColor(int rank) {
    if (rank == 1) return 0xFFFFD86A;
    if (rank == 2) return 0xFFD9E2EA;
    if (rank == 3) return 0xFFE3A472;
    return 0xFFFFFFFF;
}
'''
new_top_color = '''static uint32_t SCBDTopRankColor(int rank) {
    if (rank == 1) return 0xFFFFD86A;
    if (rank == 2) return 0xFFE6F1FF;
    if (rank == 3) return 0xFFFF9D72;
    if (rank <= 10) return 0xFFC69BFF;
    return 0xFFFFFFFF;
}
'''
s = replace_once(s, old_top_color, new_top_color, "battle Top5 tier rank colors")

old_avatar = r'''static void DrawSCBDRankAvatar(
    UIContext *ctx,
    FontID font,
    const SCBDRankAvatarMock &user,
    float cx,
    float cy,
    float radius
) {
    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->FillCircle(cx, cy, radius + 2.0f, 28, 0xCC000000);
    ctx->Draw()->FillCircle(cx, cy, radius + 1.0f, 28, 0xFFE8C86A);
    ctx->Draw()->FillCircle(cx, cy, radius, 28, user.color);
    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();
    ctx->Draw()->SetFontScale(radius <= 10.0f ? 0.24f : 0.28f, radius <= 10.0f ? 0.24f : 0.28f);
    ctx->Draw()->DrawText(font, user.initial, cx, cy, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
}
'''
new_avatar = r'''static void DrawSCBDRankAvatar(
    UIContext *ctx,
    FontID font,
    const SCBDRankAvatarMock &user,
    float cx,
    float cy,
    float radius,
    int rank
) {
    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->FillCircle(cx, cy, radius + 1.0f, 28, 0xD0101218);
    ctx->Draw()->FillCircle(cx, cy, radius, 28, user.color);
    ctx->Flush();

    DrawSCBDRankFrame(ctx, rank, cx, cy, radius);

    ctx->Begin();
    ctx->BindFontTexture();
    ctx->Draw()->SetFontScale(radius <= 10.0f ? 0.24f : 0.28f, radius <= 10.0f ? 0.24f : 0.28f);
    ctx->Draw()->DrawText(font, user.initial, cx, cy, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
}
'''
s = replace_once(s, old_avatar, new_avatar, "replace generic avatar ring with tier frame")

s = replace_once(
    s,
    "                    DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 10.5f);\n",
    "                    DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 10.5f, slot + 1);\n",
    "Top Character premium viewer frames",
)

s = replace_once(
    s,
    "                DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 11.0f);\n",
    "                DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 11.0f, i + 1);\n",
    "global ranking tier frames",
)

old_rank_color = '''static uint32_t SCBDRankNumberColor(int rank) {
    if (rank == 1) return 0xFFFFD86A;
    if (rank == 2) return 0xFFD9E2EA;
    if (rank == 3) return 0xFFE3A472;
    return 0xFFFFFFFF;
}
'''
new_rank_color = '''static uint32_t SCBDRankNumberColor(int rank) {
    if (rank == 1) return 0xFFFFD86A;
    if (rank == 2) return 0xFFE6F1FF;
    if (rank == 3) return 0xFFFF9D72;
    if (rank <= 10) return 0xFFC69BFF;
    if (rank <= 30) return 0xFF83BFFF;
    if (rank <= 70) return 0xFF74DDD4;
    return 0xFFD3B9A4;
}
'''
s = replace_once(s, old_rank_color, new_rank_color, "global tier rank-number colors")

for required in (
    "SCBDRankFrameTierIndex",
    "rank_frames_atlas.png",
    "if (rank <= 10) return 3;",
    "if (rank <= 30) return 4;",
    "if (rank <= 70) return 5;",
    "DrawSCBDRankFrame(ctx, i + 1, avatarX, cy, radius);",
    "DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 10.5f, slot + 1);",
    "DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 11.0f, i + 1);",
):
    if required not in s:
        raise SystemExit(f"V0.5.4 generated source missing: {required}")

debug.write_text(s, encoding="utf-8")

with info.open("a", encoding="utf-8") as f:
    f.write(
        "\nPSP Live FloGB V0.5.4 Tier Rank Avatar Frames\n"
        "Tier frames: Top1 / Top2 / Top3 / Top4-10 / Top11-30 / Top31-70 / Top71-100\n"
        "Top1/2/3 each use a unique premium rendered frame\n"
        "Grouped ranks share exactly one rendered frame per tier\n"
        "Battle Top5: ranks 1/2/3 premium; ranks 4/5 use Top4-10 frame\n"
        "Top Character: three viewer columns use premium Top1/Top2/Top3 frames\n"
        "Week/Month/Win: all ranks 1..100 map to the seven-frame system\n"
        "Viewer avatar content remains mock-only; frame placement is live-ready\n"
    )

print("PSP Live FloGB V0.5.4 Tier Rank Frames patch applied successfully.")
