from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_5_5.py <ppsspp_repo>")

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

def replace_between(text, start, end, replacement, label):
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"{label}: start marker missing")
    b = text.find(end, a + len(start))
    if b < 0:
        raise SystemExit(f"{label}: end marker missing")
    return text[:a] + replacement + text[b:]

debug = require("UI/DebugOverlay.cpp")
info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")
s = debug.read_text(encoding="utf-8")

for marker in (
    "SCBDRankFrameTierIndex",
    "DrawSCBDRankFrame",
    "DrawSCBDTransparentTop5List",
    "DrawSCBDCharacterPortraitSlot",
    "DrawSCBDRankAvatar",
    "Approved Top Character layout",
    "rank_frames_atlas.png",
):
    if marker not in s:
        raise SystemExit(f"V0.5.4a prerequisite missing: {marker}")

# A) Battle Top5: remove tier frames completely.
battle_frame_block = '''    ctx->Flush();
    for (int i = 0; i < SCBD_TOP5_LIMIT; ++i) {
        const float cy = y + rowH * i + rowH * 0.5f;
        const float radius = avatarSize * 0.5f;
        DrawSCBDRankFrame(ctx, i + 1, avatarX, cy, radius);
    }

    ctx->Begin();
    ctx->BindFontTexture();

'''
battle_plain = '''    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();

'''
s = replace_once(s, battle_frame_block, battle_plain, "remove battle Top5 rank frames")

# B) Per-tier optical alignment correction measured from the current atlas.
new_frame_section = r'''struct SCBDRankFrameTuning {
    float scale;
    float offsetXNorm;
    float offsetYNorm;
};

static const SCBDRankFrameTuning kSCBDRankFrameTuning[7] = {
    {3.25f, -0.0679f, 0.0444f},  // Top 1
    {3.12f, -0.0415f, 0.0444f},  // Top 2
    {3.04f, -0.0193f, 0.0440f},  // Top 3
    {2.92f,  0.0062f, 0.0458f},  // Top 4-10
    {2.88f,  0.0119f, 0.0127f},  // Top 11-30
    {2.84f,  0.0262f, 0.0427f},  // Top 31-70
    {2.80f,  0.0214f, 0.0135f},  // Top 71-100
};

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
    const SCBDRankFrameTuning &tuning = kSCBDRankFrameTuning[tier];
    const float size = avatarRadius * tuning.scale;
    const float frameCX = cx + tuning.offsetXNorm * size;
    const float frameCY = cy + tuning.offsetYNorm * size;
    const float u1 = static_cast<float>(tier) / static_cast<float>(kTierCount);
    const float u2 = static_cast<float>(tier + 1) / static_cast<float>(kTierCount);

    ctx->Flush();
    ctx->Begin();
    ctx->GetDrawContext()->BindTexture(0, atlas);
    ctx->Draw()->DrawTexRect(
        frameCX - size * 0.5f,
        frameCY - size * 0.5f,
        frameCX + size * 0.5f,
        frameCY + size * 0.5f,
        u1, 0.0f, u2, 1.0f,
        0xFFFFFFFF
    );
    ctx->Flush();
    ctx->RebindTexture();
    ctx->BindFontTexture();
}

'''

s = replace_between(
    s,
    "static float SCBDRankFrameSize(float avatarRadius, int rank) {\n",
    "static void DrawSCBDTransparentTop5List(\n",
    new_frame_section,
    "replace frame size logic with optical alignment tuning",
)

# C) Selective frames by panel.
old_avatar = r'''static void DrawSCBDRankAvatar(
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
new_avatar = r'''static void DrawSCBDRankAvatar(
    UIContext *ctx,
    FontID font,
    const SCBDRankAvatarMock &user,
    float cx,
    float cy,
    float radius,
    int rank,
    bool showTierFrame
) {
    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->FillCircle(cx, cy, radius + 1.0f, 32, 0xD0101218);
    ctx->Draw()->FillCircle(cx, cy, radius, 32, user.color);
    ctx->Flush();

    if (showTierFrame)
        DrawSCBDRankFrame(ctx, rank, cx, cy, radius);

    ctx->Begin();
    ctx->BindFontTexture();
    ctx->Draw()->SetFontScale(
        radius <= 10.0f ? 0.24f : 0.28f,
        radius <= 10.0f ? 0.24f : 0.28f
    );
    ctx->Draw()->DrawText(
        font,
        user.initial,
        cx,
        cy,
        0xFFFFFFFF,
        ALIGN_CENTER | FLAG_DYNAMIC_ASCII
    );
}
'''
s = replace_once(s, old_avatar, new_avatar, "selective-frame avatar renderer")

s = replace_once(
    s,
    "                    DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 10.5f, slot + 1);\n",
    "                    DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 10.5f, slot + 1, true);\n",
    "Top Character frames enabled",
)

s = replace_once(
    s,
    "                DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 11.0f, i + 1);\n",
    "                DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 11.0f, i + 1, active != 3);\n",
    "Week Month frame enabled and Win frame disabled",
)

# D) Character portrait renderer: no decorative border and crop away baked cell border.
new_portrait = r'''static void DrawSCBDCharacterPortraitSlot(
    UIContext *ctx,
    FontID font,
    const char *character,
    int index,
    float x,
    float y,
    float w,
    float h
) {
    Draw::Texture *atlas = GetSCBDCharacterPortraitAtlas(ctx);
    if (atlas) {
        constexpr int kCols = 7;
        constexpr int kRows = 4;
        constexpr float kInsetUPx = 6.0f;
        constexpr float kInsetVPx = 4.0f;
        constexpr float kAtlasW = 1260.0f;
        constexpr float kAtlasH = 480.0f;

        const int safeIndex = std::clamp(index, 0, 27);
        const int col = safeIndex % kCols;
        const int row = safeIndex / kCols;

        const float u1 = static_cast<float>(col) / static_cast<float>(kCols) + kInsetUPx / kAtlasW;
        const float v1 = static_cast<float>(row) / static_cast<float>(kRows) + kInsetVPx / kAtlasH;
        const float u2 = static_cast<float>(col + 1) / static_cast<float>(kCols) - kInsetUPx / kAtlasW;
        const float v2 = static_cast<float>(row + 1) / static_cast<float>(kRows) - kInsetVPx / kAtlasH;

        ctx->Flush();
        ctx->Begin();
        ctx->GetDrawContext()->BindTexture(0, atlas);
        ctx->Draw()->DrawTexRect(
            x, y, x + w, y + h,
            u1, v1, u2, v2,
            0xFFFFFFFF
        );
        ctx->Flush();
        ctx->RebindTexture();
        ctx->BindFontTexture();
        return;
    }

    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->Rect(x, y, w, h, kSCBDCharacterColors[index % 28]);
    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();
    char shortName[3] = {
        character[0],
        character[1] ? character[1] : '\0',
        '\0'
    };
    ctx->Draw()->SetFontScale(0.30f, 0.30f);
    ctx->Draw()->DrawText(
        font,
        shortName,
        x + w * 0.5f,
        y + h * 0.5f,
        0xFFFFFFFF,
        ALIGN_CENTER | FLAG_DYNAMIC_ASCII
    );
}

'''
s = replace_between(
    s,
    "static void DrawSCBDCharacterPortraitSlot(\n",
    "static void DrawSCBDInGameLayer(",
    new_portrait,
    "replace portrait renderer with borderless renderer",
)

# E) Character layout tuned toward the approved reference.
replacements = [
    ("                const float portraitX = list.x + 46.0f;\n",
     "                const float portraitX = list.x + 43.0f;\n",
     "portrait X"),
    ("                const float portraitW = 56.0f;\n",
     "                const float portraitW = 62.0f;\n",
     "portrait width"),
    ("                const float portraitH = rowH - 4.0f;\n",
     "                const float portraitH = rowH - 1.0f;\n",
     "portrait height"),
    ("                DrawSCBDCharacterPortraitSlot(ctx, font, chars[i], i, portraitX, y + 2.0f, portraitW, portraitH);\n",
     "                DrawSCBDCharacterPortraitSlot(ctx, font, chars[i], i, portraitX, y + 0.5f, portraitW, portraitH);\n",
     "portrait vertical placement"),
    ("                ctx->Draw()->DrawText(font, chars[i], portraitX + portraitW + 10.0f, cy, 0xFFFFFFFF, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);\n",
     "                ctx->Draw()->DrawText(font, chars[i], portraitX + portraitW + 12.0f, cy, 0xFFFFFFFF, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);\n",
     "character name spacing"),
    ("                const float usersStart = list.x + std::min(275.0f, list.w * 0.34f);\n",
     "                const float usersStart = list.x + std::min(292.0f, list.w * 0.36f);\n",
     "viewer columns start"),
    ("                    const float avatarX = colX + 13.0f;\n",
     "                    const float avatarX = colX + 15.0f;\n",
     "viewer avatar X"),
    ("                        colX + 29.0f,\n",
     "                        colX + 34.0f,\n",
     "viewer name X"),
    ("                        userColumnW - 32.0f,\n",
     "                        userColumnW - 37.0f,\n",
     "viewer name width"),
]
for old, new, label in replacements:
    s = replace_once(s, old, new, label)

# F) Dedicated rendered number atlas shared by all ranking tabs.
rank_number_helper = r'''static Draw::Texture *g_scbdRankNumberAtlas = nullptr;
static bool g_scbdRankNumberAtlasAttempted = false;

static Draw::Texture *GetSCBDRankNumberAtlas(UIContext *ctx) {
    if (!g_scbdRankNumberAtlas && !g_scbdRankNumberAtlasAttempted) {
        g_scbdRankNumberAtlasAttempted = true;
        g_scbdRankNumberAtlas = CreateTextureFromFile(
            ctx->GetDrawContext(),
            "scbd/rank_numbers/rank_numbers_atlas.png",
            ImageFileType::PNG,
            false,
            1024,
            256
        );
    }
    return g_scbdRankNumberAtlas;
}

static void DrawSCBDRankNumber(
    UIContext *ctx,
    int rank,
    float leftX,
    float centerY,
    float digitH,
    uint32_t color
) {
    Draw::Texture *atlas = GetSCBDRankNumberAtlas(ctx);
    if (!atlas)
        return;

    char text[8];
    std::snprintf(text, sizeof(text), "%d", rank);
    const int len = static_cast<int>(std::strlen(text));
    const float digitW = digitH * 0.53f;
    constexpr int kDigitCount = 10;

    ctx->Flush();
    ctx->Begin();
    ctx->GetDrawContext()->BindTexture(0, atlas);

    for (int pass = 0; pass < 2; ++pass) {
        const float dx = pass == 0 ? 1.1f : 0.0f;
        const float dy = pass == 0 ? 1.2f : 0.0f;
        const uint32_t drawColor = pass == 0 ? 0xB0000000 : color;

        for (int i = 0; i < len; ++i) {
            const int digit = text[i] - '0';
            if (digit < 0 || digit > 9)
                continue;

            const float u1 = static_cast<float>(digit) / static_cast<float>(kDigitCount);
            const float u2 = static_cast<float>(digit + 1) / static_cast<float>(kDigitCount);
            const float x = leftX + i * digitW + dx;
            const float y = centerY - digitH * 0.5f + dy;

            ctx->Draw()->DrawTexRect(
                x, y,
                x + digitW, y + digitH,
                u1, 0.0f, u2, 1.0f,
                drawColor
            );
        }
    }

    ctx->Flush();
    ctx->RebindTexture();
    ctx->BindFontTexture();
}

'''
anchor = "static void DrawSCBDInGameLayer("
if s.count(anchor) != 1:
    raise SystemExit(f"rank-number helper anchor count = {s.count(anchor)}")
s = s.replace(anchor, rank_number_helper + anchor, 1)

old_rank_text = '''            char rankText[12];
            std::snprintf(rankText, sizeof(rankText), "%d", i + 1);
            ctx->Draw()->SetFontScale(0.36f, 0.36f);
            ctx->Draw()->DrawText(font, rankText, list.x + 12.0f, cy, SCBDRankNumberColor(i + 1), ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);

'''
new_rank_text = '''            DrawSCBDRankNumber(
                ctx,
                i + 1,
                list.x + 10.0f,
                cy,
                active == 2 ? 21.0f : 18.0f,
                0xFFFFD86A
            );

'''
s = replace_once(s, old_rank_text, new_rank_text, "rendered rank numbers")

for required in (
    "kSCBDRankFrameTuning[7]",
    "active != 3",
    "slot + 1, true",
    "rank_numbers_atlas.png",
    "DrawSCBDRankNumber",
    "const float portraitW = 62.0f;",
    "kInsetUPx = 6.0f",
):
    if required not in s:
        raise SystemExit(f"V0.5.5 generated source missing: {required}")

if "DrawSCBDRankFrame(ctx, i + 1, avatarX, cy, radius);" in s:
    raise SystemExit("V0.5.5 battle frame draw survived")

debug.write_text(s, encoding="utf-8")

with info.open("a", encoding="utf-8") as f:
    f.write(
        "\nPSP Live FloGB V0.5.5 Character Ranking Visual Match\n"
        "Battle Top5: NO tier frames\n"
        "Win Streak: NO tier frames\n"
        "Week/Month: tier frames enabled\n"
        "Top Character: viewer Top1/Top2/Top3 tier frames enabled\n"
        "Tier frames: measured per-tier optical-center correction\n"
        "Character portraits: larger and borderless\n"
        "Rank numbers: dedicated rendered numeral atlas for all ranking tabs\n"
    )

print("PSP Live FloGB V0.5.5 patch applied successfully.")
