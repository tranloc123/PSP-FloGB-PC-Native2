from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_5_1.py <ppsspp_repo>")

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
emu = require("UI/EmuScreen.cpp")
info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")

debug_text = debug.read_text(encoding="utf-8")
emu_text = emu.read_text(encoding="utf-8")

for marker in (
    "DrawSCBDMatchTop10HUD",
    "DrawSCBDLayerButton",
    "DrawSCBDInGameLayer",
    '"TEST AVATAR"',
):
    if marker not in debug_text:
        raise SystemExit(f"V0.5.0 Hotfix5 prerequisite missing in DebugOverlay.cpp: {marker}")

for marker in (
    "HandleSCBDLayerTouch",
    "Panel::AVATAR_TEST",
    "SCBDInGameLayerState::ToggleMenu",
):
    if marker not in emu_text:
        raise SystemExit(f"V0.5.0 Hotfix5 prerequisite missing in EmuScreen.cpp: {marker}")

# -----------------------------------------------------------------------------
# 1) Replace the opaque Top10 battle HUD with transparent dynamic Top5 per team.
#    Score is used only to select/sort Top5. It is intentionally not drawn.
# -----------------------------------------------------------------------------
transparent_top5 = r'''struct SCBDMatchMockRow {
    const char *avatarText;
    const char *name;
    int score;
    uint32_t avatarColor;
};

static constexpr int SCBD_TOP5_LIMIT = 5;

static const SCBDMatchMockRow kSCBDP1MockRows[] = {
    {"T", "TINA",        50000, 0xE04CCF70},
    {"C", "CHI_DUOT",    42000, 0xE06BBF72},
    {"F", "FLO",         36500, 0xE07D91FF},
    {"A", "VIEWER_A",    34000, 0xE0D56A6A},
    {"B", "VIEWER_B",    28000, 0xE0B877D9},
    {"N", "NEW_PLAYER",  45000, 0xE0F0A34A},
    {"C", "VIEWER_C",    22000, 0xE054B5C4},
    {"D", "VIEWER_D",    18000, 0xE08C9AA8},
};

static const SCBDMatchMockRow kSCBDP2MockRows[] = {
    {"E", "EHBUDDEN",     62000, 0xE06B78FF},
    {"K", "PLAYER_K",     47000, 0xE0A56BE8},
    {"M", "PLAYER_M",     38800, 0xE0E47B60},
    {"R", "PLAYER_R",     33000, 0xE05ABDA9},
    {"S", "PLAYER_S",     28900, 0xE0C98A51},
    {"X", "NEW_CHALLENGER",51000, 0xE0E6C04D},
    {"Y", "PLAYER_Y",     24000, 0xE06DA6D8},
    {"Z", "PLAYER_Z",     19500, 0xE09C79C7},
};

static void BuildSCBDTop5(
    const SCBDMatchMockRow *rows,
    int count,
    SCBDMatchMockRow out[SCBD_TOP5_LIMIT]
) {
    for (int i = 0; i < SCBD_TOP5_LIMIT; ++i)
        out[i] = SCBDMatchMockRow{"", "", -2147483647, 0xE0606875};

    for (int i = 0; i < count; ++i) {
        int insertAt = -1;
        for (int j = 0; j < SCBD_TOP5_LIMIT; ++j) {
            if (rows[i].score > out[j].score) {
                insertAt = j;
                break;
            }
        }
        if (insertAt < 0)
            continue;

        for (int j = SCBD_TOP5_LIMIT - 1; j > insertAt; --j)
            out[j] = out[j - 1];
        out[insertAt] = rows[i];
    }
}

static uint32_t SCBDTopRankColor(int rank) {
    if (rank == 1) return 0xFFFFD86A;
    if (rank == 2) return 0xFFD9E2EA;
    if (rank == 3) return 0xFFE3A472;
    return 0xFFFFFFFF;
}

static void DrawSCBDTransparentTop5List(
    UIContext *ctx,
    FontID font,
    const SCBDMatchMockRow rows[SCBD_TOP5_LIMIT],
    float x,
    float y,
    float rowH,
    float avatarSize,
    float fontScale
) {
    const float rankW = 34.0f;
    const float avatarX = x + rankW + avatarSize * 0.5f;
    const float nameX = x + rankW + avatarSize + 10.0f;

    // No panel background by design. Only rank + circular avatar + name.
    ctx->Flush();
    ctx->BeginNoTex();
    for (int i = 0; i < SCBD_TOP5_LIMIT; ++i) {
        const float cy = y + rowH * i + rowH * 0.5f;
        const float radius = avatarSize * 0.5f;
        ctx->Draw()->FillCircle(avatarX, cy, radius + 2.0f, 28, 0xC0000000);
        ctx->Draw()->FillCircle(avatarX, cy, radius, 28, rows[i].avatarColor);
    }

    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();

    for (int i = 0; i < SCBD_TOP5_LIMIT; ++i) {
        const float cy = y + rowH * i + rowH * 0.5f;
        char rankText[8];
        std::snprintf(rankText, sizeof(rankText), "#%d", i + 1);

        ctx->Draw()->SetFontScale(fontScale, fontScale);
        ctx->Draw()->DrawText(font, rankText, x + 1.0f, cy + 1.0f, 0xE0000000, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->DrawText(font, rows[i].name, nameX + 1.0f, cy + 1.0f, 0xE0000000, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->DrawText(font, rankText, x, cy, SCBDTopRankColor(i + 1), ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->DrawText(font, rows[i].name, nameX, cy, 0xFFFFFFFF, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);

        const float avatarFont = std::min(fontScale, 0.32f);
        ctx->Draw()->SetFontScale(avatarFont, avatarFont);
        ctx->Draw()->DrawText(font, rows[i].avatarText, avatarX, cy, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
    }

    ctx->Draw()->SetFontScale(1.0f, 1.0f);
    ctx->Flush();
    ctx->RebindTexture();
}

static void DrawSCBDMatchTop5HUD(
    UIContext *ctx,
    FontID font,
    const Bounds &bounds
) {
    SCBDNativeHUD::EnsureLoaded();
    const auto &cfg = SCBDNativeHUD::Cfg();

    if (!cfg.matchHudVisible)
        return;
    if (cfg.autoHideMatchHudInRankMenu && (SCBDNativeHUD::RankMenuOpen() || SCBDInGameLayerState::Open()))
        return;

    SCBDMatchMockRow p1Top[SCBD_TOP5_LIMIT];
    SCBDMatchMockRow p2Top[SCBD_TOP5_LIMIT];
    BuildSCBDTop5(kSCBDP1MockRows, static_cast<int>(sizeof(kSCBDP1MockRows) / sizeof(kSCBDP1MockRows[0])), p1Top);
    BuildSCBDTop5(kSCBDP2MockRows, static_cast<int>(sizeof(kSCBDP2MockRows) / sizeof(kSCBDP2MockRows[0])), p2Top);

    const float rowH = std::max(26.0f, static_cast<float>(cfg.matchRowHeight));
    const float avatarSize = std::min(rowH - 4.0f, std::max(18.0f, static_cast<float>(cfg.matchAvatarSize)));
    const float fontScale = std::min(0.50f, std::max(0.28f, static_cast<float>(cfg.matchFontPct) / 100.0f));
    const float listW = std::min(280.0f, std::max(200.0f, static_cast<float>(cfg.matchPanelWidth)));
    const float topY = bounds.y + static_cast<float>(cfg.matchY);
    const float leftX = bounds.x + static_cast<float>(cfg.matchMarginX);
    const float rightX = bounds.x + bounds.w - static_cast<float>(cfg.matchMarginX) - listW;

    DrawSCBDTransparentTop5List(ctx, font, p1Top, leftX, topY, rowH, avatarSize, fontScale);
    DrawSCBDTransparentTop5List(ctx, font, p2Top, rightX, topY, rowH, avatarSize, fontScale);
}

'''

debug_text = replace_between(
    debug_text,
    "struct SCBDMatchMockRow {",
    "static void DrawSCBDLayerButton(",
    transparent_top5,
    "replace Match Top10 with transparent dynamic Top5",
)

debug_text = replace_once(
    debug_text,
    "    DrawSCBDMatchTop10HUD(ctx, ubuntu24, bounds);\n",
    "    DrawSCBDMatchTop5HUD(ctx, ubuntu24, bounds);\n",
    "replace match HUD render call",
)

# -----------------------------------------------------------------------------
# 2) Re-purpose TEST AVATAR into TEST AVATAR BXH.
#    Preview exactly the transparent Top5 row layout, not fighter-head placement.
# -----------------------------------------------------------------------------
debug_text = replace_once(
    debug_text,
    'page == Panel::AVATAR_TEST ? "TEST AVATAR" : "SCBD CONTROL"',
    'page == Panel::AVATAR_TEST ? "TEST AVATAR BXH" : "SCBD CONTROL"',
    "rename avatar test title",
)

debug_text = replace_once(
    debug_text,
    '"BXH","DEV","TEST AVATAR",cfg.matchHudVisible ? "MATCH HUD: ON" : "MATCH HUD: OFF"',
    '"BXH","DEV","TEST AVATAR BXH",cfg.matchHudVisible ? "MATCH HUD: ON" : "MATCH HUD: OFF"',
    "rename avatar test menu item",
)

avatar_preview = r'''    if (page == Panel::AVATAR_TEST) {
        auto &cfg = SCBDNativeHUD::Cfg();
        SCBDMatchMockRow p1Top[SCBD_TOP5_LIMIT];
        SCBDMatchMockRow p2Top[SCBD_TOP5_LIMIT];
        BuildSCBDTop5(kSCBDP1MockRows, static_cast<int>(sizeof(kSCBDP1MockRows) / sizeof(kSCBDP1MockRows[0])), p1Top);
        BuildSCBDTop5(kSCBDP2MockRows, static_cast<int>(sizeof(kSCBDP2MockRows) / sizeof(kSCBDP2MockRows[0])), p2Top);

        const float rowH = std::max(26.0f, static_cast<float>(cfg.matchRowHeight));
        const float avatarSize = std::min(rowH - 4.0f, std::max(18.0f, static_cast<float>(cfg.matchAvatarSize)));
        const float fontScale = std::min(0.50f, std::max(0.28f, static_cast<float>(cfg.matchFontPct) / 100.0f));
        const float previewW = std::min(250.0f, panel.w * 0.42f);
        const float previewY = panel.y + 82.0f;
        const float leftPreviewX = panel.x + 24.0f;
        const float rightPreviewX = panel.x + panel.w - previewW - 24.0f;

        DrawSCBDTransparentTop5List(ctx, font, p1Top, leftPreviewX, previewY, rowH, avatarSize, fontScale);
        DrawSCBDTransparentTop5List(ctx, font, p2Top, rightPreviewX, previewY, rowH, avatarSize, fontScale);

        char status[160];
        std::snprintf(
            status,
            sizeof(status),
            "AVATAR:%d  ROW:%d  HUD Y:%d  | diem chi dung de chon Top5, KHONG hien tren HUD",
            cfg.matchAvatarSize,
            cfg.matchRowHeight,
            cfg.matchY
        );
        ctx->Draw()->SetFontScale(0.29f, 0.29f);
        ctx->Draw()->DrawText(
            font,
            status,
            panel.x + panel.w * 0.5f,
            panel.y + panel.h - 184.0f,
            0xFFBFD0E0,
            ALIGN_HCENTER | FLAG_DYNAMIC_ASCII
        );

        const char *controls[6] = {
            "AVATAR -", "AVATAR +",
            "ROW -", "ROW +",
            "HUD Y -", "HUD Y +"
        };
        for (int i = 0; i < 6; ++i)
            DrawSCBDLayerButton(ctx, font, AvatarControlRect(i, sw, sh), controls[i], 0xDD2C3442);
    }
'''

debug_text = replace_between(
    debug_text,
    "    if (page == Panel::AVATAR_TEST) {\n",
    "    ctx->Draw()->SetFontScale(1.0f, 1.0f); ctx->Flush(); ctx->RebindTexture();\n",
    avatar_preview,
    "replace fighter avatar test with leaderboard avatar preview",
)

debug.write_text(debug_text, encoding="utf-8")

# -----------------------------------------------------------------------------
# 3) TEST AVATAR BXH controls update the exact battle-HUD layout settings.
# -----------------------------------------------------------------------------
emu_text = replace_once(
    emu_text,
    '            if (i == 2) { SCBDAvatarState::SetEnabled(true); SetAvatarTestEnabled(true); SetPanel(Panel::AVATAR_TEST); }\n',
    '            if (i == 2) SetPanel(Panel::AVATAR_TEST);\n',
    "avatar test menu no longer toggles fighter avatar",
)

old_touch = '''    if (panel == Panel::AVATAR_TEST) {
        if (AvatarControlRect(0, sw, sh).Contains(touch.x, touch.y)) AdjustAvatarRadius(-2);
        else if (AvatarControlRect(1, sw, sh).Contains(touch.x, touch.y)) AdjustAvatarRadius(+2);
        else if (AvatarControlRect(2, sw, sh).Contains(touch.x, touch.y)) AdjustAvatarYOffset(-4);
        else if (AvatarControlRect(3, sw, sh).Contains(touch.x, touch.y)) AdjustAvatarYOffset(+4);
        else if (AvatarControlRect(4, sw, sh).Contains(touch.x, touch.y)) { if (ToggleAvatarTest()) SCBDAvatarState::SetEnabled(true); }
        else if (AvatarControlRect(5, sw, sh).Contains(touch.x, touch.y)) { ResetAvatarPreview(); SCBDAvatarState::SetEnabled(true); }
        return true;
    }
'''
new_touch = '''    if (panel == Panel::AVATAR_TEST) {
        auto &cfg = SCBDNativeHUD::Cfg();
        bool changed = false;
        if (AvatarControlRect(0, sw, sh).Contains(touch.x, touch.y)) { cfg.matchAvatarSize -= 2; changed = true; }
        else if (AvatarControlRect(1, sw, sh).Contains(touch.x, touch.y)) { cfg.matchAvatarSize += 2; changed = true; }
        else if (AvatarControlRect(2, sw, sh).Contains(touch.x, touch.y)) { cfg.matchRowHeight -= 2; changed = true; }
        else if (AvatarControlRect(3, sw, sh).Contains(touch.x, touch.y)) { cfg.matchRowHeight += 2; changed = true; }
        else if (AvatarControlRect(4, sw, sh).Contains(touch.x, touch.y)) { cfg.matchY -= 10; changed = true; }
        else if (AvatarControlRect(5, sw, sh).Contains(touch.x, touch.y)) { cfg.matchY += 10; changed = true; }
        if (changed) {
            SCBDNativeHUD::ClampConfig();
            SCBDNativeHUD::SaveConfig();
        }
        return true;
    }
'''
emu_text = replace_once(emu_text, old_touch, new_touch, "leaderboard avatar preview controls")
emu.write_text(emu_text, encoding="utf-8")

with info.open("a", encoding="utf-8") as f:
    f.write(
        "\nPSP Live FloGB V0.5.1 Transparent Top5 Battle HUD\n"
        "Battle ranking: dynamic Top5 P1 + Top5 P2 only\n"
        "Rule: score below Top5 is hidden; higher newcomer automatically enters Top5\n"
        "Visual: transparent HUD, no panel background, no score text\n"
        "Visible fields only: rank + circular avatar + username\n"
        "TEST AVATAR BXH: previews exact Top5 placement and edits avatar size / row height / HUD Y\n"
        "All layout changes persist via PSP/SYSTEM/scbd_native_hud.ini\n"
        "Hotfix5 in-game layer / touch blocking retained\n"
    )

print("PSP Live FloGB V0.5.1 Transparent Top5 HUD patch applied successfully.")
