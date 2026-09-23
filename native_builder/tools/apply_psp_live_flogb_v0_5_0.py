from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_5_0.py <ppsspp_repo>")

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


# -----------------------------------------------------------------
# Preconditions: V0.4.6 must be applied. We keep all tracker/avatar
# code untouched and replace only the ranking/HUD experiment layer.
# -----------------------------------------------------------------
debug = require("UI/DebugOverlay.cpp")
debug_text = debug.read_text(encoding="utf-8")
for marker in (
    "DrawSCBDRankingPopup",
    "RANK V0.4.6",
    "DrawSCBDTestAvatar",
    "PickSCBDRefinedHead",
):
    if marker not in debug_text:
        raise SystemExit(f"V0.4.6 prerequisite missing in DebugOverlay.cpp: {marker}")

emu = require("UI/EmuScreen.cpp")
emu_text = emu.read_text(encoding="utf-8")
for marker in (
    '"RANK PANEL"',
    '"TEST HIEN THI"',
    '"TAB >"',
    "SCBDRankPanelState::ToggleOpen",
    '"AVATAR ON/OFF"',
):
    if marker not in emu_text:
        raise SystemExit(f"V0.4.6 prerequisite missing in EmuScreen.cpp: {marker}")

scbd_dir = repo / "SCBD"
scbd_dir.mkdir(exist_ok=True)

# ================================================================
# 1) Runtime config, persistent DEV settings, future event hooks
# ================================================================
config_h = r'''#pragma once

#include <algorithm>
#include <atomic>
#include <string>

#include "Common/Data/Format/IniFile.h"
#include "Core/Util/PathUtil.h"

namespace SCBDNativeHUD {

struct Config {
    bool matchHudVisible = true;
    bool testData = true;
    bool autoHideMatchHudInRankMenu = true;
    bool showCharacterScores = false;

    int matchMarginX = 12;
    int matchY = 170;
    int matchPanelWidth = 310;
    int matchRowHeight = 31;
    int matchAvatarSize = 24;
    int matchPanelOpacity = 184;
    int matchFontPct = 37;

    int rankMenuWidth = 980;
    int rankRowHeight = 42;
    int rankAvatarSize = 36;
    int rankFontPct = 100;
    int rankDimOpacity = 150;

    int mediaX = 50;
    int mediaY = 70;
    int mediaScalePct = 100;
    int mediaDurationMs = 3200;
};

inline Config &Cfg() {
    static Config cfg{};
    return cfg;
}

inline bool &LoadedFlag() {
    static bool loaded = false;
    return loaded;
}

inline std::atomic<bool> &RankMenuOpenAtomic() {
    static std::atomic<bool> open{false};
    return open;
}

inline bool RankMenuOpen() {
    return RankMenuOpenAtomic().load(std::memory_order_relaxed);
}

inline void SetRankMenuOpen(bool open) {
    RankMenuOpenAtomic().store(open, std::memory_order_relaxed);
}

inline Path ConfigPath() {
    return GetSysDirectory(DIRECTORY_SYSTEM) / "scbd_native_hud.ini";
}

inline void ClampConfig() {
    Config &c = Cfg();
    c.matchMarginX = std::clamp(c.matchMarginX, 0, 400);
    c.matchY = std::clamp(c.matchY, 0, 1000);
    c.matchPanelWidth = std::clamp(c.matchPanelWidth, 180, 600);
    c.matchRowHeight = std::clamp(c.matchRowHeight, 20, 72);
    c.matchAvatarSize = std::clamp(c.matchAvatarSize, 12, 64);
    c.matchPanelOpacity = std::clamp(c.matchPanelOpacity, 0, 255);
    c.matchFontPct = std::clamp(c.matchFontPct, 22, 80);
    c.rankMenuWidth = std::clamp(c.rankMenuWidth, 600, 1500);
    c.rankRowHeight = std::clamp(c.rankRowHeight, 28, 80);
    c.rankAvatarSize = std::clamp(c.rankAvatarSize, 20, 72);
    c.rankFontPct = std::clamp(c.rankFontPct, 70, 160);
    c.rankDimOpacity = std::clamp(c.rankDimOpacity, 0, 230);
    c.mediaX = std::clamp(c.mediaX, 0, 100);
    c.mediaY = std::clamp(c.mediaY, 0, 100);
    c.mediaScalePct = std::clamp(c.mediaScalePct, 25, 250);
    c.mediaDurationMs = std::clamp(c.mediaDurationMs, 500, 15000);
}

inline void ResetConfig() {
    Cfg() = Config{};
    ClampConfig();
}

inline void LoadConfig() {
    Config &c = Cfg();
    IniFile ini;
    if (ini.Load(ConfigPath())) {
        if (const Section *s = ini.GetSection("MatchHUD")) {
            s->Get("Visible", &c.matchHudVisible);
            s->Get("AutoHideInRankMenu", &c.autoHideMatchHudInRankMenu);
            s->Get("MarginX", &c.matchMarginX);
            s->Get("Y", &c.matchY);
            s->Get("PanelWidth", &c.matchPanelWidth);
            s->Get("RowHeight", &c.matchRowHeight);
            s->Get("AvatarSize", &c.matchAvatarSize);
            s->Get("PanelOpacity", &c.matchPanelOpacity);
            s->Get("FontPct", &c.matchFontPct);
        }
        if (const Section *s = ini.GetSection("RankMenu")) {
            s->Get("Width", &c.rankMenuWidth);
            s->Get("RowHeight", &c.rankRowHeight);
            s->Get("AvatarSize", &c.rankAvatarSize);
            s->Get("FontPct", &c.rankFontPct);
            s->Get("DimOpacity", &c.rankDimOpacity);
            s->Get("ShowCharacterScores", &c.showCharacterScores);
        }
        if (const Section *s = ini.GetSection("Dev")) {
            s->Get("TestData", &c.testData);
        }
        if (const Section *s = ini.GetSection("FutureMedia")) {
            s->Get("X", &c.mediaX);
            s->Get("Y", &c.mediaY);
            s->Get("ScalePct", &c.mediaScalePct);
            s->Get("DurationMs", &c.mediaDurationMs);
        }
    }
    ClampConfig();
    LoadedFlag() = true;
}

inline void EnsureLoaded() {
    if (!LoadedFlag())
        LoadConfig();
}

inline void SaveConfig() {
    ClampConfig();
    const Config &c = Cfg();
    IniFile ini;
    ini.Load(ConfigPath());

    Section *match = ini.GetOrCreateSection("MatchHUD");
    match->Set("Visible", c.matchHudVisible);
    match->Set("AutoHideInRankMenu", c.autoHideMatchHudInRankMenu);
    match->Set("MarginX", c.matchMarginX);
    match->Set("Y", c.matchY);
    match->Set("PanelWidth", c.matchPanelWidth);
    match->Set("RowHeight", c.matchRowHeight);
    match->Set("AvatarSize", c.matchAvatarSize);
    match->Set("PanelOpacity", c.matchPanelOpacity);
    match->Set("FontPct", c.matchFontPct);

    Section *rank = ini.GetOrCreateSection("RankMenu");
    rank->Set("Width", c.rankMenuWidth);
    rank->Set("RowHeight", c.rankRowHeight);
    rank->Set("AvatarSize", c.rankAvatarSize);
    rank->Set("FontPct", c.rankFontPct);
    rank->Set("DimOpacity", c.rankDimOpacity);
    rank->Set("ShowCharacterScores", c.showCharacterScores);

    Section *dev = ini.GetOrCreateSection("Dev");
    dev->Set("TestData", c.testData);

    Section *media = ini.GetOrCreateSection("FutureMedia");
    media->Set("X", c.mediaX);
    media->Set("Y", c.mediaY);
    media->Set("ScalePct", c.mediaScalePct);
    media->Set("DurationMs", c.mediaDurationMs);

    ini.Save(ConfigPath());
}

inline bool ToggleMatchHud() {
    EnsureLoaded();
    Cfg().matchHudVisible = !Cfg().matchHudVisible;
    return Cfg().matchHudVisible;
}

inline bool ToggleTestData() {
    EnsureLoaded();
    Cfg().testData = !Cfg().testData;
    return Cfg().testData;
}

// Reserved state for the next native integrations.  They deliberately do
// not touch SCBD RAM yet; DEV can verify the event path before HP/media work.
inline std::atomic<int> &PendingHealP1() {
    static std::atomic<int> value{0};
    return value;
}
inline std::atomic<int> &PendingHealP2() {
    static std::atomic<int> value{0};
    return value;
}
inline std::atomic<int> &PendingTop100Intro() {
    static std::atomic<int> value{0};
    return value;
}
inline void QueueHealTest(int side, int amount) {
    if (side == 1)
        PendingHealP1().fetch_add(amount, std::memory_order_relaxed);
    else
        PendingHealP2().fetch_add(amount, std::memory_order_relaxed);
}
inline void QueueTop100IntroTest() {
    PendingTop100Intro().fetch_add(1, std::memory_order_relaxed);
}

}  // namespace SCBDNativeHUD
'''
(scbd_dir / "SCBDNativeHUDConfig.h").write_text(config_h, encoding="utf-8")

# ================================================================
# 2) Native game-style ranking menu + native DEV editor
#    Top week/month/winstreak = 100 rows in one vertical ScrollView.
#    Character = all 28 fighters, each with Top 3 viewer names.
# ================================================================
screens_h = r'''#pragma once

#include <algorithm>
#include <cstdio>
#include <string>

#include "Common/UI/PopupScreens.h"
#include "Common/UI/ScrollView.h"
#include "Common/UI/View.h"
#include "SCBD/SCBDNativeHUDConfig.h"

class SCBDNativeRankScreen : public UI::PopupScreen {
public:
    enum class Tab {
        WEEK = 0,
        MONTH = 1,
        CHARACTER = 2,
        WIN_STREAK = 3,
    };

    SCBDNativeRankScreen()
        : UI::PopupScreen("SCBD BATTLE RANKING", "CLOSE", "") {
        SCBDNativeHUD::EnsureLoaded();
        SCBDNativeHUD::SetRankMenuOpen(true);
        SetHasDropShadow(true);
    }

    ~SCBDNativeRankScreen() override {
        SCBDNativeHUD::SetRankMenuOpen(false);
    }

    const char *tag() const override { return "SCBDNativeRankScreen"; }

protected:
    bool FillVertical() const override { return true; }
    UI::Size PopupWidth() const override {
        return static_cast<UI::Size>(SCBDNativeHUD::Cfg().rankMenuWidth);
    }

    void CreatePopupContents(UI::ViewGroup *parent) override {
        using namespace UI;
        SCBDNativeHUD::EnsureLoaded();

        LinearLayout *tabs = parent->Add(new LinearLayout(ORIENT_HORIZONTAL));
        AddTabButton(tabs, "TOP TUAN", Tab::WEEK);
        AddTabButton(tabs, "TOP THANG", Tab::MONTH);
        AddTabButton(tabs, "TOP NHAN VAT", Tab::CHARACTER);
        AddTabButton(tabs, "CHUOI WIN", Tab::WIN_STREAK);

        parent->Add(new TextView(TabSubtitle(), new LinearLayoutParams(Margins(12, 8))));

        ScrollView *scroll = parent->Add(
            new ScrollView(
                ORIENT_VERTICAL,
                new LinearLayoutParams(FILL_PARENT, WRAP_CONTENT, 1.0f)
            )
        );
        LinearLayout *list = scroll->Add(new LinearLayout(ORIENT_VERTICAL));
        list->SetSpacing(2.0f);

        if (!SCBDNativeHUD::Cfg().testData) {
            list->Add(new TextView(
                "CHUA CO DU LIEU LIVE - BAT TEST DATA TRONG DEV DE KIEM TRA UI",
                new LinearLayoutParams(Margins(12, 12))
            ));
            return;
        }

        switch (tab_) {
        case Tab::WEEK:
            BuildTop100(list, "WEEK", 1820000, 9250, false);
            break;
        case Tab::MONTH:
            BuildTop100(list, "MONTH", 9850000, 37850, false);
            break;
        case Tab::CHARACTER:
            BuildCharacters(list);
            break;
        case Tab::WIN_STREAK:
            BuildTop100(list, "STREAK", 100, 1, true);
            break;
        }
    }

private:
    void AddTabButton(UI::LinearLayout *tabs, const char *label, Tab tab) {
        UI::Choice *button = tabs->Add(
            new UI::Choice(label, new UI::LinearLayoutParams(1.0f))
        );
        button->OnClick.Add([this, tab](UI::EventParams &) {
            tab_ = tab;
            RecreateViews();
        });
    }

    const char *TabSubtitle() const {
        switch (tab_) {
        case Tab::WEEK:
            return "TOP 100 DIEM CAO NHAT TRONG TUAN - VUOT LEN/XUONG DE XEM";
        case Tab::MONTH:
            return "TOP 100 DIEM CAO NHAT TRONG THANG - VUOT LEN/XUONG DE XEM";
        case Tab::CHARACTER:
            return "28 NHAN VAT - MOI NHAN VAT HIEN TOP 3 VIEWER DIEM CAO NHAT";
        case Tab::WIN_STREAK:
            return "TOP 100 CHUOI THANG - BEST GIU LAI SAU KHI CURRENT VE 0";
        }
        return "";
    }

    void AddRankRow(UI::LinearLayout *list, int rank, const char *prefix, int value, bool streak) {
        char text[256];
        if (streak) {
            const int best = std::max(1, value);
            const int current = best % 11;
            std::snprintf(
                text, sizeof(text),
                "#%03d   [AVATAR]   %s_VIEWER_%03d      CURRENT:%d   BEST:%d",
                rank, prefix, rank, current, best
            );
        } else {
            std::snprintf(
                text, sizeof(text),
                "#%03d   [AVATAR]   %s_VIEWER_%03d                         %d",
                rank, prefix, rank, value
            );
        }

        const auto &cfg = SCBDNativeHUD::Cfg();
        UI::LinearLayout *line = list->Add(
            new UI::LinearLayout(
                UI::ORIENT_HORIZONTAL,
                new UI::LinearLayoutParams(UI::FILL_PARENT, static_cast<float>(cfg.rankRowHeight))
            )
        );
        UI::TextView *avatar = line->Add(
            new UI::TextView(
                "[AV]",
                ALIGN_CENTER,
                false,
                new UI::LinearLayoutParams(
                    static_cast<float>(cfg.rankAvatarSize),
                    static_cast<float>(cfg.rankAvatarSize)
                )
            )
        );
        avatar->SetScale(0.72f);
        UI::TextView *row = line->Add(
            new UI::TextView(
                text,
                ALIGN_VCENTER,
                false,
                new UI::LinearLayoutParams(1.0f, UI::Gravity::G_VCENTER)
            )
        );
        row->SetScale(static_cast<float>(cfg.rankFontPct) / 100.0f);
        row->SetShadow(true);
        if (rank == 1)
            row->SetTextColor(0xFF66DDFF);
        else if (rank == 2)
            row->SetTextColor(0xFFC0C0C0);
        else if (rank == 3)
            row->SetTextColor(0xFF88AAFF);
    }

    void BuildTop100(UI::LinearLayout *list, const char *prefix, int start, int step, bool streak) {
        for (int i = 0; i < 100; ++i) {
            const int rank = i + 1;
            const int value = std::max(1, start - i * step);
            AddRankRow(list, rank, prefix, value, streak);
        }
    }

    void BuildCharacters(UI::LinearLayout *list) {
        static const char *kCharacters[28] = {
            "ALGOL", "AMY", "ASTAROTH", "CASSANDRA", "CERVANTES", "DAMPIERRE", "HILDE",
            "IVY", "KILIK", "KRATOS", "LIZARDMAN", "MAXI", "MITSURUGI", "NIGHTMARE",
            "RAPHAEL", "ROCK", "SEONG_MI_NA", "SETSUKA", "SIEGFRIED", "SOPHITIA", "TAKI",
            "TALIM", "TIRA", "VOLDO", "XIANGHUA", "YOSHIMITSU", "YUN_SEONG", "ZASALAMEL"
        };
        static const char *kNames[10] = {
            "TINA", "EHBUDDEN", "FLO", "CHI_DUOT", "VIEWER_A",
            "VIEWER_B", "VIEWER_C", "PLAYER_88", "TOP_GIFTER", "SCBD_FAN"
        };

        for (int i = 0; i < 28; ++i) {
            const char *n1 = kNames[(i + 0) % 10];
            const char *n2 = kNames[(i + 3) % 10];
            const char *n3 = kNames[(i + 6) % 10];
            char text[320];
            if (SCBDNativeHUD::Cfg().showCharacterScores) {
                std::snprintf(
                    text, sizeof(text),
                    "%02d. %-12s : #1 %s 58000 | #2 %s 47000 | #3 %s 36000",
                    i + 1, kCharacters[i], n1, n2, n3
                );
            } else {
                std::snprintf(
                    text, sizeof(text),
                    "%02d. %-12s : %s - %s - %s",
                    i + 1, kCharacters[i], n1, n2, n3
                );
            }
            const auto &cfg = SCBDNativeHUD::Cfg();
            UI::LinearLayout *line = list->Add(
                new UI::LinearLayout(
                    UI::ORIENT_HORIZONTAL,
                    new UI::LinearLayoutParams(UI::FILL_PARENT, static_cast<float>(cfg.rankRowHeight))
                )
            );
            UI::TextView *portrait = line->Add(
                new UI::TextView(
                    "[CHAR]",
                    ALIGN_CENTER,
                    false,
                    new UI::LinearLayoutParams(
                        static_cast<float>(cfg.rankAvatarSize),
                        static_cast<float>(cfg.rankAvatarSize)
                    )
                )
            );
            portrait->SetScale(0.62f);
            UI::TextView *row = line->Add(
                new UI::TextView(
                    text,
                    ALIGN_VCENTER,
                    false,
                    new UI::LinearLayoutParams(1.0f, UI::Gravity::G_VCENTER)
                )
            );
            row->SetScale(static_cast<float>(cfg.rankFontPct) / 100.0f);
            row->SetShadow(true);
        }
    }

    Tab tab_ = Tab::WEEK;
};

class SCBDNativeDevScreen : public UI::PopupScreen {
public:
    SCBDNativeDevScreen()
        : UI::PopupScreen("SCBD HUD DEV", "SAVE", "CLOSE") {
        SCBDNativeHUD::EnsureLoaded();
    }

    const char *tag() const override { return "SCBDNativeDevScreen"; }

protected:
    bool FillVertical() const override { return true; }
    UI::Size PopupWidth() const override { return 760; }

    void CreatePopupContents(UI::ViewGroup *parent) override {
        using namespace UI;
        SCBDNativeHUD::EnsureLoaded();
        auto &c = SCBDNativeHUD::Cfg();

        ScrollView *scroll = parent->Add(
            new ScrollView(
                ORIENT_VERTICAL,
                new LinearLayoutParams(FILL_PARENT, WRAP_CONTENT, 1.0f)
            )
        );
        LinearLayout *list = scroll->Add(new LinearLayout(ORIENT_VERTICAL));

        list->Add(new TextView("MATCH HUD - TOP 10 P1/P2", new LinearLayoutParams(Margins(8, 8))));
        list->Add(new CheckBox(&c.matchHudVisible, "Match HUD ON/OFF"));
        list->Add(new CheckBox(&c.autoHideMatchHudInRankMenu, "Auto hide Match HUD khi mo Rank Menu"));
        list->Add(new PopupSliderChoice(&c.matchMarginX, 0, 300, 12, "Match Margin X", 2, screenManager(), " px"));
        list->Add(new PopupSliderChoice(&c.matchY, 0, 900, 170, "Match Y", 5, screenManager(), " px"));
        list->Add(new PopupSliderChoice(&c.matchPanelWidth, 180, 600, 310, "Match Panel Width", 5, screenManager(), " px"));
        list->Add(new PopupSliderChoice(&c.matchRowHeight, 20, 72, 31, "Match Row Height", 1, screenManager(), " px"));
        list->Add(new PopupSliderChoice(&c.matchAvatarSize, 12, 64, 24, "Match Avatar Size", 1, screenManager(), " px"));
        list->Add(new PopupSliderChoice(&c.matchPanelOpacity, 0, 255, 184, "Match Panel Opacity", 5, screenManager(), " /255"));
        list->Add(new PopupSliderChoice(&c.matchFontPct, 22, 80, 37, "Match Font Scale", 1, screenManager(), " %"));

        list->Add(new TextView("RANK MENU - TOP100 / 28 CHAR / WIN STREAK", new LinearLayoutParams(Margins(8, 12))));
        list->Add(new CheckBox(&c.showCharacterScores, "Top nhan vat: hien diem cua Top 3"));
        list->Add(new PopupSliderChoice(&c.rankMenuWidth, 600, 1500, 980, "Rank Menu Width", 10, screenManager(), " px"));
        list->Add(new PopupSliderChoice(&c.rankRowHeight, 28, 80, 42, "Rank Row Height", 1, screenManager(), " px"));
        list->Add(new PopupSliderChoice(&c.rankAvatarSize, 20, 72, 36, "Rank Avatar Size", 1, screenManager(), " px"));
        list->Add(new PopupSliderChoice(&c.rankFontPct, 70, 160, 100, "Rank Font Scale", 5, screenManager(), " %"));

        list->Add(new TextView("TEST / FUTURE HOOKS", new LinearLayoutParams(Margins(8, 12))));
        list->Add(new CheckBox(&c.testData, "TEST DATA Top10 / Top100 / 28 nhan vat"));

        list->Add(new UI::Choice("TEST GIFT +10 HP P1 (event only)"))->OnClick.Add([](UI::EventParams &) {
            SCBDNativeHUD::QueueHealTest(1, 10);
        });
        list->Add(new UI::Choice("TEST GIFT +10 HP P2 (event only)"))->OnClick.Add([](UI::EventParams &) {
            SCBDNativeHUD::QueueHealTest(2, 10);
        });
        list->Add(new UI::Choice("TEST TOP100 ENTRANCE VIDEO (event only)"))->OnClick.Add([](UI::EventParams &) {
            SCBDNativeHUD::QueueTop100IntroTest();
        });

        list->Add(new TextView("MEDIA DEV (danh cho video Top100 sau nay)", new LinearLayoutParams(Margins(8, 12))));
        list->Add(new PopupSliderChoice(&c.mediaX, 0, 100, 50, "Media X", 1, screenManager(), " %"));
        list->Add(new PopupSliderChoice(&c.mediaY, 0, 100, 70, "Media Y", 1, screenManager(), " %"));
        list->Add(new PopupSliderChoice(&c.mediaScalePct, 25, 250, 100, "Media Scale", 5, screenManager(), " %"));
        list->Add(new PopupSliderChoice(&c.mediaDurationMs, 500, 15000, 3200, "Media Duration", 100, screenManager(), " ms"));

        list->Add(new UI::Choice("SAVE NOW"))->OnClick.Add([](UI::EventParams &) {
            SCBDNativeHUD::SaveConfig();
        });
        list->Add(new UI::Choice("RELOAD CONFIG"))->OnClick.Add([this](UI::EventParams &) {
            SCBDNativeHUD::LoadConfig();
            RecreateViews();
        });
        list->Add(new UI::Choice("RESET DEFAULTS"))->OnClick.Add([this](UI::EventParams &) {
            SCBDNativeHUD::ResetConfig();
            SCBDNativeHUD::SaveConfig();
            RecreateViews();
        });

        list->Add(new TextView(
            "UI sliders apply truc tiep vao HUD render. SAVE luu vao PSP/SYSTEM/scbd_native_hud.ini."
        ));
    }

    void OnCompleted(UI::DialogResult result) override {
        if (result == UI::DR_OK)
            SCBDNativeHUD::SaveConfig();
    }
};
'''
(scbd_dir / "SCBDNativeHUDScreens.h").write_text(screens_h, encoding="utf-8")

# ================================================================
# 3) Replace old V0.4.6 controls with Match HUD / Rank Menu / DEV /
#    Test Data.  Rank Menu and DEV are real native PopupScreen UI.
# ================================================================
s = emu_text

include_anchor = '#include "SCBD/SCBDRankPanelState.h"\n'
s = replace_once(
    s,
    include_anchor,
    include_anchor
    + '#include "SCBD/SCBDNativeHUDConfig.h"\n'
    + '#include "SCBD/SCBDNativeHUDScreens.h"\n',
    "EmuScreen native HUD includes",
)

old_globals = '''static UI::Button *g_scbdHUDButton = nullptr;
static UI::Button *g_scbdRankTestButton = nullptr;
static UI::Button *g_scbdRankNextTabButton = nullptr;
'''
new_globals = '''static UI::Button *g_scbdMatchHUDButton = nullptr;
static UI::Button *g_scbdRankMenuButton = nullptr;
static UI::Button *g_scbdDevButton = nullptr;
static UI::Button *g_scbdNativeTestButton = nullptr;
'''
s = replace_once(s, old_globals, new_globals, "native HUD button globals")

old_reset = '''    g_scbdHUDButton = nullptr;
    g_scbdRankTestButton = nullptr;
    g_scbdRankNextTabButton = nullptr;
'''
new_reset = '''    g_scbdMatchHUDButton = nullptr;
    g_scbdRankMenuButton = nullptr;
    g_scbdDevButton = nullptr;
    g_scbdNativeTestButton = nullptr;
'''
s = replace_once(s, old_reset, new_reset, "native HUD button reset")

controls_start = '        g_scbdHUDButton = root_->Add(\n'
controls_end = '    if (g_scbdAvatarButton) {\n'
new_controls = r'''        SCBDNativeHUD::EnsureLoaded();

        g_scbdMatchHUDButton = root_->Add(
            new Button(
                "MATCH HUD",
                new AnchorLayoutParams(150, 50, NONE, 10, 170, NONE)
            )
        );
        g_scbdMatchHUDButton->SetScale(0.62f);
        g_scbdMatchHUDButton->OnClick.Add([](UI::EventParams &) {
            const bool enabled = SCBDNativeHUD::ToggleMatchHud();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                enabled ? "Match Top10 HUD ON" : "Match Top10 HUD OFF",
                1.4f,
                "scbd_match_hud_toggle"
            );
        });

        g_scbdRankMenuButton = root_->Add(
            new Button(
                "RANK MENU",
                new AnchorLayoutParams(150, 50, NONE, 10, 230, NONE)
            )
        );
        g_scbdRankMenuButton->SetScale(0.62f);
        g_scbdRankMenuButton->OnClick.Add([this](UI::EventParams &) {
            screenManager()->push(new SCBDNativeRankScreen());
        });

        g_scbdDevButton = root_->Add(
            new Button(
                "DEV",
                new AnchorLayoutParams(150, 50, NONE, 10, 290, NONE)
            )
        );
        g_scbdDevButton->SetScale(0.62f);
        g_scbdDevButton->OnClick.Add([this](UI::EventParams &) {
            screenManager()->push(new SCBDNativeDevScreen());
        });

        g_scbdNativeTestButton = root_->Add(
            new Button(
                "TEST DATA",
                new AnchorLayoutParams(150, 50, NONE, 10, 350, NONE)
            )
        );
        g_scbdNativeTestButton->SetScale(0.62f);
        g_scbdNativeTestButton->OnClick.Add([](UI::EventParams &) {
            const bool enabled = SCBDNativeHUD::ToggleTestData();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                enabled ? "SCBD TEST DATA ON" : "SCBD TEST DATA OFF",
                1.4f,
                "scbd_native_test_toggle"
            );
        });

'''
s = replace_between(
    s,
    controls_start,
    controls_end,
    new_controls,
    "replace V0.4.6 ranking controls",
)

old_visibility = '''    if (g_scbdHUDButton) {
        g_scbdHUDButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

    if (g_scbdRankTestButton) {
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
new_visibility = '''    if (g_scbdMatchHUDButton) {
        g_scbdMatchHUDButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

    if (g_scbdRankMenuButton) {
        g_scbdRankMenuButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

    if (g_scbdDevButton) {
        g_scbdDevButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

    if (g_scbdNativeTestButton) {
        g_scbdNativeTestButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

'''
s = replace_once(s, old_visibility, new_visibility, "native HUD control visibility")

emu.write_text(s, encoding="utf-8")

# ================================================================
# 4) Replace V0.4.6 centered painted popup with continuous Match Top10
#    HUD.  The large ranking UI now lives in a native PopupScreen.
# ================================================================
s = debug_text

include_anchor = '#include "SCBD/SCBDRankPanelState.h"\n'
s = replace_once(
    s,
    include_anchor,
    include_anchor + '#include "SCBD/SCBDNativeHUDConfig.h"\n',
    "DebugOverlay native HUD config include",
)

match_helpers = r'''struct SCBDMatchMockRow {
    const char *avatar;
    const char *name;
    const char *score;
};

static void DrawSCBDMatchTop10HUD(
    UIContext *ctx,
    FontID font,
    const Bounds &bounds
) {
    using namespace SCBDNativeHUD;
    EnsureLoaded();
    const Config &cfg = Cfg();

    if (!cfg.matchHudVisible)
        return;
    if (cfg.autoHideMatchHudInRankMenu && RankMenuOpen())
        return;

    static const SCBDMatchMockRow p1[10] = {
        {"A1", "TINA", "50000"}, {"A2", "CHI_DUOT", "42000"},
        {"A3", "FLO", "36500"}, {"A4", "P1_VIEWER_04", "31000"},
        {"A5", "P1_VIEWER_05", "27800"}, {"A6", "P1_VIEWER_06", "23100"},
        {"A7", "P1_VIEWER_07", "19900"}, {"A8", "P1_VIEWER_08", "16700"},
        {"A9", "P1_VIEWER_09", "12400"}, {"A10", "P1_VIEWER_10", "9800"},
    };
    static const SCBDMatchMockRow p2[10] = {
        {"B1", "EHBUDDEN", "62000"}, {"B2", "P2_VIEWER_02", "45500"},
        {"B3", "P2_VIEWER_03", "38800"}, {"B4", "P2_VIEWER_04", "33000"},
        {"B5", "P2_VIEWER_05", "28900"}, {"B6", "P2_VIEWER_06", "24400"},
        {"B7", "P2_VIEWER_07", "20200"}, {"B8", "P2_VIEWER_08", "17500"},
        {"B9", "P2_VIEWER_09", "13800"}, {"B10", "P2_VIEWER_10", "10300"},
    };

    const float panelW = static_cast<float>(cfg.matchPanelWidth);
    const float rowH = static_cast<float>(cfg.matchRowHeight);
    const float avatar = static_cast<float>(cfg.matchAvatarSize);
    const float headerH = 34.0f;
    const float panelH = headerH + rowH * 10.0f + 8.0f;
    const float y = bounds.y + static_cast<float>(cfg.matchY);
    const float leftX = bounds.x + static_cast<float>(cfg.matchMarginX);
    const float rightX = bounds.x + bounds.w - static_cast<float>(cfg.matchMarginX) - panelW;
    const uint32_t panelAlpha = static_cast<uint32_t>(cfg.matchPanelOpacity & 0xFF) << 24;
    const uint32_t panelColor = panelAlpha | 0x00161620;

    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->Rect(leftX - 2.0f, y - 2.0f, panelW + 4.0f, panelH + 4.0f, 0xCC66FF88);
    ctx->Draw()->Rect(leftX, y, panelW, panelH, panelColor);
    ctx->Draw()->Rect(rightX - 2.0f, y - 2.0f, panelW + 4.0f, panelH + 4.0f, 0xCCFF8877);
    ctx->Draw()->Rect(rightX, y, panelW, panelH, panelColor);
    ctx->Draw()->Rect(leftX, y, panelW, headerH, 0xD0202A24);
    ctx->Draw()->Rect(rightX, y, panelW, headerH, 0xD02A2020);

    if (cfg.testData) {
        for (int i = 0; i < 10; ++i) {
            const float ry = y + headerH + 4.0f + rowH * i;
            const uint32_t rowColor = (i % 2 == 0) ? 0x84282834 : 0x7020202A;
            ctx->Draw()->Rect(leftX + 5.0f, ry, panelW - 10.0f, rowH - 2.0f, rowColor);
            ctx->Draw()->Rect(rightX + 5.0f, ry, panelW - 10.0f, rowH - 2.0f, rowColor);

            const float avY = ry + (rowH - avatar) * 0.5f - 1.0f;
            ctx->Draw()->Rect(leftX + 9.0f, avY, avatar, avatar, 0xFF3B3B48);
            ctx->Draw()->Rect(rightX + 9.0f, avY, avatar, avatar, 0xFF3B3B48);
        }
    }

    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();

    ctx->Draw()->SetFontScale(0.44f, 0.44f);
    ctx->Draw()->DrawText(font, "TEAM P1 - TOP 10", leftX + 10.0f, y + 9.0f, 0xFFAAFFBB, FLAG_DYNAMIC_ASCII);
    ctx->Draw()->DrawText(font, "TEAM P2 - TOP 10", rightX + 10.0f, y + 9.0f, 0xFFFFAA99, FLAG_DYNAMIC_ASCII);

    if (!cfg.testData) {
        ctx->Draw()->SetFontScale(0.34f, 0.34f);
        ctx->Draw()->DrawText(font, "WAITING LIVE DATA", leftX + panelW * 0.5f, y + 68.0f, 0xFFFFFFFF, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->DrawText(font, "WAITING LIVE DATA", rightX + panelW * 0.5f, y + 68.0f, 0xFFFFFFFF, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
    } else {
        const float fontScale = static_cast<float>(cfg.matchFontPct) / 100.0f;
        ctx->Draw()->SetFontScale(fontScale, fontScale);
        for (int i = 0; i < 10; ++i) {
            const float ry = y + headerH + 4.0f + rowH * i;
            const float avY = ry + (rowH - avatar) * 0.5f - 1.0f;
            char rank[8];
            std::snprintf(rank, sizeof(rank), "#%d", i + 1);

            ctx->Draw()->DrawText(font, p1[i].avatar, leftX + 9.0f + avatar * 0.5f, avY + avatar * 0.5f, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
            ctx->Draw()->DrawText(font, rank, leftX + 16.0f + avatar, ry + 8.0f, 0xFFAAFFBB, FLAG_DYNAMIC_ASCII);
            ctx->Draw()->DrawTextRect(font, p1[i].name, leftX + 48.0f + avatar, ry + 4.0f, panelW - avatar - 120.0f, rowH - 6.0f, 0xFFFFFFFF, FLAG_DYNAMIC_ASCII);
            ctx->Draw()->DrawText(font, p1[i].score, leftX + panelW - 12.0f, ry + 8.0f, 0xFFFFFFFF, ALIGN_RIGHT | FLAG_DYNAMIC_ASCII);

            ctx->Draw()->DrawText(font, p2[i].avatar, rightX + 9.0f + avatar * 0.5f, avY + avatar * 0.5f, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
            ctx->Draw()->DrawText(font, rank, rightX + 16.0f + avatar, ry + 8.0f, 0xFFFFAA99, FLAG_DYNAMIC_ASCII);
            ctx->Draw()->DrawTextRect(font, p2[i].name, rightX + 48.0f + avatar, ry + 4.0f, panelW - avatar - 120.0f, rowH - 6.0f, 0xFFFFFFFF, FLAG_DYNAMIC_ASCII);
            ctx->Draw()->DrawText(font, p2[i].score, rightX + panelW - 12.0f, ry + 8.0f, 0xFFFFFFFF, ALIGN_RIGHT | FLAG_DYNAMIC_ASCII);
        }
    }

    ctx->Draw()->SetFontScale(1.0f, 1.0f);
    ctx->Flush();
    ctx->RebindTexture();
}

'''

s = replace_between(
    s,
    "struct SCBDRankMockRow {",
    "static void DrawSCBDBoneMapper(",
    match_helpers,
    "replace V0.4.6 painted popup with Match Top10 HUD",
)

s = replace_once(
    s,
    '"RANK V0.4.6 | AVATAR:%s | CAM:%s F:%u | "',
    '"NATIVE HUD V0.5.0 | AVATAR:%s | CAM:%s F:%u | "',
    "V0.5.0 runtime diagnostic label",
)

s = replace_once(
    s,
    "    DrawSCBDRankingPopup(ctx, ubuntu24, bounds);\n",
    "    DrawSCBDMatchTop10HUD(ctx, ubuntu24, bounds);\n",
    "replace popup render call with Match Top10 HUD",
)

debug.write_text(s, encoding="utf-8")

# ================================================================
# 5) Build marker
# ================================================================
info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")
info.write_text(
    "PSP Live FloGB V0.5.0 Native HUD Framework\\n"
    "Target: Soulcalibur Broken Destiny ULUS-10457\\n"
    "Package: com.scbd.vieweremulator\\n"
    "Tracker/avatar pipeline from V0.4.6 preserved\\n"
    "Match HUD: continuous P1 Top10 + P2 Top10, toggleable, avatar slots reserved\\n"
    "Rank Menu: native PopupScreen, touch-scroll Top100 Week / Month / Win Streak\\n"
    "Character Rank: all 28 characters, Top3 viewer names per character\\n"
    "DEV: native settings editor with live render sliders and TEST DATA\\n"
    "DEV persistence: PSP/SYSTEM/scbd_native_hud.ini\\n"
    "Future hooks reserved: gift heal events + Top100 entrance media events\\n"
    "Important: future UI tuning should use DEV/settings, not rebuild APK\\n",
    encoding="utf-8",
)

print("PSP Live FloGB V0.5.0 Native HUD Framework patch applied successfully.")
