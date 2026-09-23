from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_4_6.py <ppsspp_repo>")

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
    count = text.count(start)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 start marker, found {count}")
    a = text.find(start)
    b = text.find(end, a + len(start))
    if b < 0:
        raise SystemExit(f"{label}: end marker missing")
    return text[:a] + replacement + text[b:]


# V0.4.5 must already be applied.  We deliberately keep every tracker path.
debug = require("UI/DebugOverlay.cpp")
debug_text = debug.read_text(encoding="utf-8")
for marker in (
    "DrawSCBDTeamHUD",
    "HUD V0.4.5",
    "DrawSCBDTestAvatar",
    "PickSCBDRefinedHead",
):
    if marker not in debug_text:
        raise SystemExit(f"V0.4.5 prerequisite missing in DebugOverlay.cpp: {marker}")

emu = require("UI/EmuScreen.cpp")
emu_text = emu.read_text(encoding="utf-8")
for marker in (
    "g_scbdHUDButton",
    '"HUD ON/OFF"',
    "SCBDHUDState::Toggle",
    "AVATAR ON/OFF",
):
    if marker not in emu_text:
        raise SystemExit(f"V0.4.5 prerequisite missing in EmuScreen.cpp: {marker}")

# ================================================================
# 1) Shared state for the popup ranking panel and its test controls
# ================================================================
scbd_dir = repo / "SCBD"
rank_state_h = r'''#pragma once

#include <atomic>

namespace SCBDRankPanelState {

enum class Tab : int {
    BATTLE_P1 = 0,
    BATTLE_P2 = 1,
    WEEK = 2,
    MONTH = 3,
    CHARACTER = 4,
    COUNT = 5,
};

inline std::atomic<bool> &OpenAtomic() {
    static std::atomic<bool> open{false};
    return open;
}

inline std::atomic<bool> &TestDataAtomic() {
    static std::atomic<bool> enabled{false};
    return enabled;
}

inline std::atomic<int> &TabAtomic() {
    static std::atomic<int> tab{static_cast<int>(Tab::BATTLE_P1)};
    return tab;
}

inline bool Open() {
    return OpenAtomic().load(std::memory_order_relaxed);
}

inline void SetOpen(bool open) {
    OpenAtomic().store(open, std::memory_order_relaxed);
}

inline bool ToggleOpen() {
    const bool after = !Open();
    SetOpen(after);
    return after;
}

inline bool TestDataEnabled() {
    return TestDataAtomic().load(std::memory_order_relaxed);
}

inline bool ToggleTestData() {
    const bool before = TestDataEnabled();
    const bool after = !before;
    TestDataAtomic().store(after, std::memory_order_relaxed);
    if (after)
        SetOpen(true);
    return after;
}

inline Tab CurrentTab() {
    int value = TabAtomic().load(std::memory_order_relaxed);
    if (value < 0 || value >= static_cast<int>(Tab::COUNT))
        value = 0;
    return static_cast<Tab>(value);
}

inline Tab NextTab() {
    int value = TabAtomic().load(std::memory_order_relaxed);
    value = (value + 1) % static_cast<int>(Tab::COUNT);
    TabAtomic().store(value, std::memory_order_relaxed);
    return static_cast<Tab>(value);
}

inline const char *TabName(Tab tab) {
    switch (tab) {
    case Tab::BATTLE_P1: return "TRAN P1";
    case Tab::BATTLE_P2: return "TRAN P2";
    case Tab::WEEK: return "TOP TUAN";
    case Tab::MONTH: return "TOP THANG";
    case Tab::CHARACTER: return "TOP NHAN VAT";
    default: return "TRAN P1";
    }
}

}  // namespace SCBDRankPanelState
'''
(scbd_dir / "SCBDRankPanelState.h").write_text(rank_state_h, encoding="utf-8")

# ================================================================
# 2) Replace V0.4.5 HUD button with popup controls
#    Main panel is hidden by default. TEST HIEN THI exists specifically
#    so layout/avatar slots can be checked before any live TikTok wiring.
# ================================================================
s = emu_text

include_anchor = '#include "SCBD/SCBDHUDState.h"\n'
s = replace_once(
    s,
    include_anchor,
    include_anchor + '#include "SCBD/SCBDRankPanelState.h"\n',
    "EmuScreen rank state include",
)

globals_anchor = 'static UI::Button *g_scbdHUDButton = nullptr;\n'
s = replace_once(
    s,
    globals_anchor,
    globals_anchor
    + 'static UI::Button *g_scbdRankTestButton = nullptr;\n'
    + 'static UI::Button *g_scbdRankNextTabButton = nullptr;\n',
    "EmuScreen popup button globals",
)

reset_anchor = '''    g_scbdAvatarButton = nullptr;
    g_scbdHUDButton = nullptr;
    g_scbdInspectorPanel = nullptr;
'''
s = replace_once(
    s,
    reset_anchor,
    '''    g_scbdAvatarButton = nullptr;
    g_scbdHUDButton = nullptr;
    g_scbdRankTestButton = nullptr;
    g_scbdRankNextTabButton = nullptr;
    g_scbdInspectorPanel = nullptr;
''',
    "EmuScreen popup button reset",
)

old_hud_block = r'''        g_scbdHUDButton = root_->Add(
            new Button(
                "HUD ON/OFF",
                new AnchorLayoutParams(150, 50, NONE, 10, 170, NONE)
            )
        );
        g_scbdHUDButton->SetScale(0.62f);
        g_scbdHUDButton->OnClick.Add([](UI::EventParams &) {
            const bool enabled = SCBDHUDState::Toggle();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                enabled ? "Dual Team HUD ON" : "Dual Team HUD OFF",
                1.5f,
                "scbd_hud_toggle"
            );
        });

'''
new_hud_block = r'''        g_scbdHUDButton = root_->Add(
            new Button(
                "RANK PANEL",
                new AnchorLayoutParams(150, 50, NONE, 10, 170, NONE)
            )
        );
        g_scbdHUDButton->SetScale(0.62f);
        g_scbdHUDButton->OnClick.Add([](UI::EventParams &) {
            const bool open = SCBDRankPanelState::ToggleOpen();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                open ? "Bang xep hang OPEN" : "Bang xep hang CLOSED",
                1.5f,
                "scbd_rank_panel_toggle"
            );
        });

        g_scbdRankTestButton = root_->Add(
            new Button(
                "TEST HIEN THI",
                new AnchorLayoutParams(150, 50, NONE, 10, 230, NONE)
            )
        );
        g_scbdRankTestButton->SetScale(0.62f);
        g_scbdRankTestButton->OnClick.Add([](UI::EventParams &) {
            const bool enabled = SCBDRankPanelState::ToggleTestData();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                enabled ? "Mock ranking data ON" : "Mock ranking data OFF",
                1.5f,
                "scbd_rank_test_toggle"
            );
        });

        g_scbdRankNextTabButton = root_->Add(
            new Button(
                "TAB >",
                new AnchorLayoutParams(150, 50, NONE, 10, 290, NONE)
            )
        );
        g_scbdRankNextTabButton->SetScale(0.62f);
        g_scbdRankNextTabButton->OnClick.Add([](UI::EventParams &) {
            const auto tab = SCBDRankPanelState::NextTab();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                SCBDRankPanelState::TabName(tab),
                1.2f,
                "scbd_rank_next_tab"
            );
        });

'''
s = replace_once(
    s,
    old_hud_block,
    new_hud_block,
    "replace persistent HUD button with popup controls",
)

old_visibility = '''    if (g_scbdHUDButton) {
        g_scbdHUDButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

'''
new_visibility = old_visibility + '''    if (g_scbdRankTestButton) {
        g_scbdRankTestButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

    if (g_scbdRankNextTabButton) {
        g_scbdRankNextTabButton->SetVisibility(
            (scbdTarget && SCBDRankPanelState::Open()) ? UI::V_VISIBLE : UI::V_GONE
        );
    }

'''
s = replace_once(
    s,
    old_visibility,
    new_visibility,
    "popup controls visibility",
)

emu.write_text(s, encoding="utf-8")

# ================================================================
# 3) Replace always-visible dual-team HUD with a centered modal popup.
#    Avatar placeholders intentionally reserve real texture space for the
#    next live-avatar phase.  No tracker/camera/fighter logic is touched.
# ================================================================
s = debug_text

include_anchor = '#include "SCBD/SCBDHUDState.h"\n'
s = replace_once(
    s,
    include_anchor,
    include_anchor + '#include "SCBD/SCBDRankPanelState.h"\n',
    "DebugOverlay rank state include",
)

popup_helpers = r'''struct SCBDRankMockRow {
    const char *avatar;
    const char *name;
    const char *score;
};

static void DrawSCBDRankingPopup(
    UIContext *ctx,
    FontID font,
    const Bounds &bounds
) {
    using namespace SCBDRankPanelState;

    if (!Open())
        return;

    const float panelW = std::min(bounds.w * 0.78f, 760.0f);
    const float panelH = std::min(bounds.h * 0.78f, 430.0f);
    const float panelX = bounds.x + (bounds.w - panelW) * 0.5f;
    const float panelY = bounds.y + (bounds.h - panelH) * 0.5f;
    const float headerH = 52.0f;
    const float tabsH = 36.0f;
    const float rowH = 53.0f;
    const float avatarSize = 40.0f;

    const Tab tab = CurrentTab();
    const int activeTab = static_cast<int>(tab);

    const SCBDRankMockRow p1Rows[] = {
        {"A1", "TINA_TOP1", "5,000"},
        {"A2", "CHI_DUOT", "4,000"},
        {"A3", "VIEWER_P1_03", "3,500"},
        {"A4", "VERY_LONG_VIEWER_NAME", "2,250"},
        {"A5", "P1_SUPPORTER", "1,750"},
    };
    const SCBDRankMockRow p2Rows[] = {
        {"B1", "EHBUDDEN", "6,000"},
        {"B2", "VIEWER_P2_02", "2,500"},
        {"B3", "VIEWER_P2_03", "1,700"},
        {"B4", "P2_SUPPORTER_LONG", "1,250"},
        {"B5", "PLAYER_FIVE", "850"},
    };
    const SCBDRankMockRow weekRows[] = {
        {"W1", "WEEK_TOP_ONE", "125,000"},
        {"W2", "WEEK_TOP_TWO", "110,500"},
        {"W3", "WEEK_TOP_THREE", "98,250"},
        {"W4", "WEEK_VIEWER_04", "76,800"},
        {"W5", "WEEK_VIEWER_05", "65,100"},
    };
    const SCBDRankMockRow monthRows[] = {
        {"M1", "MONTH_CHAMPION", "1,250,000"},
        {"M2", "MONTH_SECOND", "985,400"},
        {"M3", "MONTH_THIRD", "802,150"},
        {"M4", "MONTH_VIEWER_04", "615,900"},
        {"M5", "MONTH_VIEWER_05", "501,300"},
    };
    const SCBDRankMockRow characterRows[] = {
        {"C1", "NIGHTMARE", "142 WINS"},
        {"C2", "KRATOS", "128 WINS"},
        {"C3", "AMY", "117 WINS"},
        {"C4", "YOSHIMITSU", "105 WINS"},
        {"C5", "DAMPierre", "91 WINS"},
    };

    const SCBDRankMockRow *rows = p1Rows;
    const char *title = "BXH TRAN DAU - TEAM P1";
    const char *total = "TONG DIEM: 12,500";
    uint32_t accent = 0xFF66FF88;

    switch (tab) {
    case Tab::BATTLE_P1:
        rows = p1Rows;
        title = "BXH TRAN DAU - TEAM P1";
        total = "TONG DIEM: 12,500";
        accent = 0xFF66FF88;
        break;
    case Tab::BATTLE_P2:
        rows = p2Rows;
        title = "BXH TRAN DAU - TEAM P2";
        total = "TONG DIEM: 10,200";
        accent = 0xFFFF8877;
        break;
    case Tab::WEEK:
        rows = weekRows;
        title = "TOP TUAN";
        total = "RESET: MOCK WEEK";
        accent = 0xFFFFCC66;
        break;
    case Tab::MONTH:
        rows = monthRows;
        title = "TOP THANG";
        total = "RESET: MOCK MONTH";
        accent = 0xFFFF99DD;
        break;
    case Tab::CHARACTER:
        rows = characterRows;
        title = "TOP NHAN VAT";
        total = "THONG KE NHAN VAT";
        accent = 0xFF88CCFF;
        break;
    default:
        break;
    }

    // Draw the popup as a real overlay layer: dim game -> border -> panel.
    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->Rect(bounds.x, bounds.y, bounds.w, bounds.h, 0x88000000);
    ctx->Draw()->Rect(panelX - 4.0f, panelY - 4.0f, panelW + 8.0f, panelH + 8.0f, accent);
    ctx->Draw()->Rect(panelX, panelY, panelW, panelH, 0xF2181822);
    ctx->Draw()->Rect(panelX, panelY, panelW, headerH, 0xF52A2A38);
    ctx->Draw()->Rect(panelX, panelY + headerH, panelW, tabsH, 0xEE20202B);

    const float tabW = panelW / 5.0f;
    for (int i = 0; i < 5; ++i) {
        if (i == activeTab) {
            ctx->Draw()->Rect(
                panelX + i * tabW + 2.0f,
                panelY + headerH + tabsH - 4.0f,
                tabW - 4.0f,
                4.0f,
                accent
            );
        }
    }

    if (TestDataEnabled()) {
        const float rowsY = panelY + headerH + tabsH + 8.0f;
        for (int i = 0; i < 5; ++i) {
            const float y = rowsY + i * rowH;
            const uint32_t rowColor = (i % 2 == 0) ? 0xB92B2B36 : 0xA622222D;
            ctx->Draw()->Rect(panelX + 14.0f, y, panelW - 28.0f, rowH - 4.0f, rowColor);

            const float avatarX = panelX + 23.0f;
            const float avatarY = y + (rowH - avatarSize) * 0.5f - 2.0f;
            ctx->Draw()->Rect(avatarX - 2.0f, avatarY - 2.0f, avatarSize + 4.0f, avatarSize + 4.0f, accent);
            ctx->Draw()->Rect(avatarX, avatarY, avatarSize, avatarSize, 0xFF30303D);
        }
    }

    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();

    ctx->Draw()->SetFontScale(0.64f, 0.64f);
    ctx->Draw()->DrawText(
        font,
        title,
        panelX + 18.0f,
        panelY + 16.0f,
        0xFFFFFFFF,
        FLAG_DYNAMIC_ASCII
    );
    ctx->Draw()->SetFontScale(0.42f, 0.42f);
    ctx->Draw()->DrawText(
        font,
        total,
        panelX + panelW - 18.0f,
        panelY + 19.0f,
        accent,
        ALIGN_RIGHT | FLAG_DYNAMIC_ASCII
    );

    const char *tabLabels[] = {
        "TRAN P1", "TRAN P2", "TOP TUAN", "TOP THANG", "NHAN VAT"
    };
    ctx->Draw()->SetFontScale(0.36f, 0.36f);
    for (int i = 0; i < 5; ++i) {
        ctx->Draw()->DrawText(
            font,
            tabLabels[i],
            panelX + tabW * (i + 0.5f),
            panelY + headerH + 11.0f,
            i == activeTab ? accent : 0xFFB8B8C8,
            ALIGN_HCENTER | FLAG_DYNAMIC_ASCII
        );
    }

    if (!TestDataEnabled()) {
        ctx->Draw()->SetFontScale(0.52f, 0.52f);
        ctx->Draw()->DrawText(
            font,
            "CHUA CO DU LIEU - BAM TEST HIEN THI",
            panelX + panelW * 0.5f,
            panelY + panelH * 0.53f,
            0xFFFFFFFF,
            ALIGN_CENTER | FLAG_DYNAMIC_ASCII
        );
        ctx->Draw()->SetFontScale(0.34f, 0.34f);
        ctx->Draw()->DrawText(
            font,
            "TEST se mo mock Top 5 + o avatar viewer de kiem tra layout",
            panelX + panelW * 0.5f,
            panelY + panelH * 0.62f,
            0xFFB8B8C8,
            ALIGN_CENTER | FLAG_DYNAMIC_ASCII
        );
    } else {
        const float rowsY = panelY + headerH + tabsH + 8.0f;
        for (int i = 0; i < 5; ++i) {
            const float y = rowsY + i * rowH;
            const float avatarX = panelX + 23.0f;
            const float avatarY = y + (rowH - avatarSize) * 0.5f - 2.0f;

            char rankText[8];
            std::snprintf(rankText, sizeof(rankText), "#%d", i + 1);

            ctx->Draw()->SetFontScale(0.34f, 0.34f);
            ctx->Draw()->DrawText(
                font,
                rows[i].avatar,
                avatarX + avatarSize * 0.5f,
                avatarY + avatarSize * 0.5f,
                0xFFFFFFFF,
                ALIGN_CENTER | FLAG_DYNAMIC_ASCII
            );

            ctx->Draw()->SetFontScale(0.40f, 0.40f);
            ctx->Draw()->DrawText(
                font,
                rankText,
                avatarX + avatarSize + 14.0f,
                y + 15.0f,
                accent,
                FLAG_DYNAMIC_ASCII
            );

            ctx->Draw()->SetFontScale(0.43f, 0.43f);
            ctx->Draw()->DrawTextRect(
                font,
                rows[i].name,
                avatarX + avatarSize + 55.0f,
                y + 8.0f,
                panelW * 0.48f,
                rowH - 12.0f,
                0xFFFFFFFF,
                FLAG_DYNAMIC_ASCII
            );

            ctx->Draw()->SetFontScale(0.43f, 0.43f);
            ctx->Draw()->DrawText(
                font,
                rows[i].score,
                panelX + panelW - 26.0f,
                y + 15.0f,
                0xFFFFFFFF,
                ALIGN_RIGHT | FLAG_DYNAMIC_ASCII
            );
        }
    }

    ctx->Draw()->SetFontScale(0.31f, 0.31f);
    ctx->Draw()->DrawText(
        font,
        TestDataEnabled()
            ? "V0.4.6 TEST DATA | TAB > de xem 5 muc | RANK PANEL de dong"
            : "RANK POPUP V0.4.6 | RANK PANEL de dong",
        panelX + panelW * 0.5f,
        panelY + panelH - 18.0f,
        0xFFB8B8C8,
        ALIGN_HCENTER | FLAG_DYNAMIC_ASCII
    );

    ctx->Draw()->SetFontScale(1.0f, 1.0f);
    ctx->Flush();
    ctx->RebindTexture();
}

'''

s = replace_between(
    s,
    "static void DrawSCBDTeamHUD(",
    "static void DrawSCBDBoneMapper(",
    popup_helpers,
    "replace V0.4.5 persistent HUD with ranking popup",
)

# Remove the old always-visible HUD call inside the mapper.
s = replace_once(
    s,
    "    DrawSCBDTeamHUD(ctx, ubuntu24, bounds);\n\n",
    "",
    "remove V0.4.5 always-visible HUD call",
)

# Keep the runtime diagnostic but update the version label.
s = replace_once(
    s,
    '"HUD V0.4.5 | AVATAR:%s | CAM:%s F:%u | "',
    '"RANK V0.4.6 | AVATAR:%s | CAM:%s F:%u | "',
    "V0.4.6 runtime diagnostic label",
)

# Draw popup at the very end of the mapper so it sits above avatar/debug text.
mapper_start = s.find("static void DrawSCBDBoneMapper(")
mapper_end = s.find("\n}  // namespace\n", mapper_start)
if mapper_start < 0 or mapper_end < 0:
    raise SystemExit("V0.4.6 mapper bounds not found")
mapper = s[mapper_start:mapper_end]
tail_anchor = "    ctx->Draw()->SetFontScale(1.0f, 1.0f);\n    ctx->Flush();\n    ctx->RebindTexture();\n}"
if mapper.count(tail_anchor) != 1:
    raise SystemExit(f"V0.4.6 mapper tail anchor count = {mapper.count(tail_anchor)}")
mapper = mapper.replace(
    tail_anchor,
    "    ctx->Draw()->SetFontScale(1.0f, 1.0f);\n"
    "    ctx->Flush();\n"
    "    ctx->RebindTexture();\n\n"
    "    DrawSCBDRankingPopup(ctx, ubuntu24, bounds);\n"
    "}",
    1,
)
s = s[:mapper_start] + mapper + s[mapper_end:]

debug.write_text(s, encoding="utf-8")

# ================================================================
# 4) Build marker
# ================================================================
info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")
info.write_text(
    "PSP Live FloGB V0.4.6 Rank Popup Test\\n"
    "Target: Soulcalibur Broken Destiny ULUS-10457\\n"
    "Package: com.scbd.vieweremulator\\n"
    "Base: V0.4.5 preserved, tracker/avatar unchanged\\n"
    "Change: persistent P1/P2 leaderboard removed from gameplay\\n"
    "Popup: one centered ranking layer, hidden by default\\n"
    "Tabs: Battle P1 / Battle P2 / Week / Month / Character\\n"
    "Avatar: reserved 40x40 viewer-avatar slots in every ranking row\\n"
    "TEST HIEN THI: toggles deterministic mock Top 5 data and auto-opens popup\\n"
    "TAB >: cycles all five popup views for layout testing\\n"
    "Next after PASS: replace avatar slots + mock rows with live TikTok data\\n",
    encoding="utf-8",
)

print("PSP Live FloGB V0.4.6 Rank Popup Test patch applied successfully.")
