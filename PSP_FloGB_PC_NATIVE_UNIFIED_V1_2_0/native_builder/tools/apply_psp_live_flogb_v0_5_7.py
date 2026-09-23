from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_5_7.py <ppsspp_repo>")

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


def insert_before_once(text, marker, addition, label):
    count = text.count(marker)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 marker, found {count}")
    return text.replace(marker, addition + marker, 1)


state = require("SCBD/SCBDInGameLayerState.h")
debug = require("UI/DebugOverlay.cpp")
emu = require("UI/EmuScreen.cpp")
info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")

state_text = state.read_text(encoding="utf-8")
debug_text = debug.read_text(encoding="utf-8")
emu_text = emu.read_text(encoding="utf-8")

# Fail fast if this is not the frozen V0.5.6 branch shape.
for marker in (
    "enum class Panel : int { NONE = 0, MENU = 1, RANK = 2, DEV = 3, AVATAR_TEST = 4 };",
    "inline int RankRowCount() { return RankTab() == 2 ? 28 : 100; }",
):
    if marker not in state_text:
        raise SystemExit(f"V0.5.7 state prerequisite missing: {marker}")

for marker in (
    "DrawSCBDInGameLayer",
    "DrawSCBDCharacterPortraitSlot",
    "DrawSCBDMatchTop5HUD",
    "TEST AVATAR BXH",
    "kSCBDRankFrameTuning[7]",
    "radius * 0.78f",
):
    if marker not in debug_text:
        raise SystemExit(f"V0.5.7 DebugOverlay prerequisite missing: {marker}")

for marker in (
    "HandleSCBDLayerTouch",
    "Panel::AVATAR_TEST",
    "SCBDInGameLayerState::ToggleMenu",
    "const Bounds &scbdBounds",
):
    if marker not in emu_text:
        raise SystemExit(f"V0.5.7 EmuScreen prerequisite missing: {marker}")

scbd_dir = repo / "SCBD"

# -----------------------------------------------------------------------------
# 1) Always-on native virtual input core (P1/physical PSP route in V0.5.7).
#    The API is already shaped for tap/chord/sequence and can be fed by the
#    future live bridge without changing combat code.
# -----------------------------------------------------------------------------
virtual_input_h = r'''#pragma once

#include <chrono>
#include <cstddef>
#include <deque>
#include <initializer_list>
#include <mutex>

#include "Common/CommonTypes.h"
#include "Core/HLE/sceCtrl.h"

namespace SCBDVirtualInput {

struct Pulse {
    u32 mask = 0;
    int holdMs = 80;
    int gapMs = 70;
};

struct EngineState {
    std::mutex mutex;
    std::deque<Pulse> queue;
    bool down = false;
    bool gap = false;
    u32 activeMask = 0;
    u32 preserveMask = 0;
    u32 lastMask = 0;
    int activeGapMs = 0;
    std::chrono::steady_clock::time_point deadline{};
};

inline EngineState &State() {
    static EngineState s;
    return s;
}

inline int ClampMs(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

inline void QueueChord(u32 mask, int holdMs = 80, int gapMs = 70) {
    mask &= CTRL_MASK_USER;
    if (!mask)
        return;
    EngineState &s = State();
    std::lock_guard<std::mutex> guard(s.mutex);
    if (s.queue.size() >= 64)
        return;
    s.queue.push_back(Pulse{mask, ClampMs(holdMs, 20, 1200), ClampMs(gapMs, 0, 1200)});
    s.lastMask = mask;
}

inline void QueueTap(u32 mask, int holdMs = 80, int gapMs = 70) {
    QueueChord(mask, holdMs, gapMs);
}

inline void QueueSequence(std::initializer_list<u32> masks, int holdMs = 70, int gapMs = 55) {
    for (u32 mask : masks)
        QueueChord(mask, holdMs, gapMs);
}

inline void CancelAll() {
    EngineState &s = State();
    std::lock_guard<std::mutex> guard(s.mutex);
    if (s.down && s.activeMask) {
        const u32 clearMask = s.activeMask & ~s.preserveMask;
        __CtrlUpdateButtons(0, clearMask);
    }
    s.queue.clear();
    s.down = false;
    s.gap = false;
    s.activeMask = 0;
    s.preserveMask = 0;
    s.activeGapMs = 0;
}

inline void Process() {
    using Clock = std::chrono::steady_clock;
    const auto now = Clock::now();
    EngineState &s = State();
    std::lock_guard<std::mutex> guard(s.mutex);

    if (s.down && now >= s.deadline) {
        const u32 clearMask = s.activeMask & ~s.preserveMask;
        __CtrlUpdateButtons(0, clearMask);
        s.down = false;
        s.gap = true;
        s.deadline = now + std::chrono::milliseconds(s.activeGapMs);
        s.activeGapMs = 0;
    }

    if (s.gap && now >= s.deadline)
        s.gap = false;

    if (!s.down && !s.gap && !s.queue.empty()) {
        const Pulse pulse = s.queue.front();
        s.queue.pop_front();
        s.activeMask = pulse.mask;
        s.preserveMask = __CtrlPeekButtons() & pulse.mask;
        __CtrlUpdateButtons(pulse.mask, 0);
        s.down = true;
        s.gap = false;
        s.activeGapMs = pulse.gapMs;
        s.deadline = now + std::chrono::milliseconds(pulse.holdMs);
        return;
    }
}

inline bool Busy() {
    EngineState &s = State();
    std::lock_guard<std::mutex> guard(s.mutex);
    return s.down || s.gap || !s.queue.empty();
}

inline size_t QueueSize() {
    EngineState &s = State();
    std::lock_guard<std::mutex> guard(s.mutex);
    return s.queue.size() + (s.down ? 1 : 0);
}

inline u32 LastMask() {
    EngineState &s = State();
    std::lock_guard<std::mutex> guard(s.mutex);
    return s.lastMask;
}

}  // namespace SCBDVirtualInput
'''
(scbd_dir / "SCBDVirtualInput.h").write_text(virtual_input_h, encoding="utf-8")

# -----------------------------------------------------------------------------
# 2) Native Winner/Pick state machine. V0.5.7 exposes a stable native API and
#    DEV test flow. Web Winner V5 remains the live fallback; bridge cutover is
#    deliberately NOT done in this build.
# -----------------------------------------------------------------------------
winner_h = r'''#pragma once

#include <algorithm>
#include <chrono>
#include <mutex>
#include <string>

namespace SCBDNativeWinner {

enum class Phase : int {
    NONE = 0,
    WINNER = 1,
    PICK = 2,
    PICK_SUCCESS = 3,
    TIMEOUT = 4,
};

struct State {
    std::mutex mutex;
    Phase phase = Phase::NONE;
    std::string username = "TINA";
    int team = 1;
    int characterId = 14;
    std::string character = "KRATOS";
    std::chrono::steady_clock::time_point deadline{};
};

struct Snapshot {
    Phase phase = Phase::NONE;
    std::string username;
    int team = 1;
    int characterId = 14;
    std::string character;
    int remainingMs = 0;
};

inline State &GetState() {
    static State s;
    return s;
}

inline void BeginWinnerPick(const char *username, int team) {
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    s.username = (username && *username) ? username : "TOP1";
    s.team = team == 2 ? 2 : 1;
    s.phase = Phase::WINNER;
    s.deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(5500);
}

inline void ShowPickSuccess(int characterId, const char *character) {
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    s.characterId = std::clamp(characterId, 1, 28);
    s.character = (character && *character) ? character : "CHARACTER";
    s.phase = Phase::PICK_SUCCESS;
    s.deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(4500);
}

inline void ShowTimeout() {
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    s.phase = Phase::TIMEOUT;
    s.deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(2600);
}

inline void Cancel() {
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    s.phase = Phase::NONE;
}

inline void Process() {
    using Clock = std::chrono::steady_clock;
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    if (s.phase == Phase::NONE)
        return;
    const auto now = Clock::now();
    if (now < s.deadline)
        return;

    if (s.phase == Phase::WINNER) {
        s.phase = Phase::PICK;
        s.deadline = now + std::chrono::milliseconds(15000);
    } else if (s.phase == Phase::PICK) {
        s.phase = Phase::TIMEOUT;
        s.deadline = now + std::chrono::milliseconds(2600);
    } else {
        s.phase = Phase::NONE;
    }
}

inline Snapshot Read() {
    using Clock = std::chrono::steady_clock;
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    Snapshot out;
    out.phase = s.phase;
    out.username = s.username;
    out.team = s.team;
    out.characterId = s.characterId;
    out.character = s.character;
    if (s.phase != Phase::NONE) {
        const auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(s.deadline - Clock::now()).count();
        out.remainingMs = static_cast<int>(std::max<long long>(0, ms));
    }
    return out;
}

}  // namespace SCBDNativeWinner
'''
(scbd_dir / "SCBDNativeWinner.h").write_text(winner_h, encoding="utf-8")

# -----------------------------------------------------------------------------
# 3) Extend existing in-game layer manager with WINNER TEST and INPUT LAB.
# -----------------------------------------------------------------------------
state_text = replace_once(
    state_text,
    "enum class Panel : int { NONE = 0, MENU = 1, RANK = 2, DEV = 3, AVATAR_TEST = 4 };",
    "enum class Panel : int { NONE = 0, MENU = 1, RANK = 2, DEV = 3, AVATAR_TEST = 4, WINNER_TEST = 5, INPUT_TEST = 6 };",
    "extend layer panel enum",
)
state_text = replace_once(
    state_text,
    "    if (v < 0 || v > 4) v = 0;",
    "    if (v < 0 || v > 6) v = 0;",
    "extend panel clamp",
)

rect_addition = r'''inline Rect WinnerButtonRect(int i, float sw, float sh) {
    Rect p = MainPanel(sw, sh);
    const float w = std::min(520.0f, p.w - 60.0f);
    const float h = 58.0f;
    return {p.x + (p.w - w) * 0.5f, p.y + 105.0f + i * 72.0f, w, h};
}
inline Rect InputButtonRect(int i, float sw, float sh) {
    Rect p = MainPanel(sw, sh);
    const float gap = 10.0f;
    const float w = (p.w - 70.0f) * 0.5f;
    const float h = 48.0f;
    const int col = i % 2;
    const int row = i / 2;
    return {p.x + 25.0f + col * (w + gap), p.y + 86.0f + row * (h + gap), w, h};
}
'''
state_text = insert_before_once(
    state_text,
    "inline int RankRowCount() { return RankTab() == 2 ? 28 : 100; }",
    rect_addition,
    "add winner/input test rectangles",
)
state.write_text(state_text, encoding="utf-8")

# -----------------------------------------------------------------------------
# 4) EmuScreen touch/control wiring.
# -----------------------------------------------------------------------------
emu_text = replace_once(
    emu_text,
    '#include "SCBD/SCBDInGameLayerState.h"\n',
    '#include "SCBD/SCBDInGameLayerState.h"\n#include "SCBD/SCBDNativeWinner.h"\n#include "SCBD/SCBDVirtualInput.h"\n',
    "include V0.5.7 runtime headers in EmuScreen",
)

emu_text = replace_once(
    emu_text,
    "        for (int i = 0; i < 6; ++i) if (MenuButtonRect(i, sw, sh).Contains(touch.x, touch.y)) {\n",
    "        for (int i = 0; i < 8; ++i) if (MenuButtonRect(i, sw, sh).Contains(touch.x, touch.y)) {\n",
    "expand SCBD menu touch targets",
)

old_menu_actions = '''            if (i == 0) SetPanel(Panel::RANK);
            if (i == 1) SetPanel(Panel::DEV);
            if (i == 2) SetPanel(Panel::AVATAR_TEST);
            if (i == 3) SCBDNativeHUD::ToggleMatchHud();
            if (i == 4) SCBDAvatarState::Toggle();
            if (i == 5) CloseAndSwallow();
'''
new_menu_actions = '''            if (i == 0) SetPanel(Panel::RANK);
            if (i == 1) SetPanel(Panel::DEV);
            if (i == 2) SetPanel(Panel::AVATAR_TEST);
            if (i == 3) SCBDNativeHUD::ToggleMatchHud();
            if (i == 4) SCBDAvatarState::Toggle();
            if (i == 5) SetPanel(Panel::WINNER_TEST);
            if (i == 6) SetPanel(Panel::INPUT_TEST);
            if (i == 7) CloseAndSwallow();
'''
emu_text = replace_once(emu_text, old_menu_actions, new_menu_actions, "expand SCBD menu actions")

extra_touch = r'''    if (panel == Panel::WINNER_TEST) {
        if (WinnerButtonRect(0, sw, sh).Contains(touch.x, touch.y)) {
            SCBDNativeWinner::BeginWinnerPick("TINA", 1);
            CloseAndSwallow();
        } else if (WinnerButtonRect(1, sw, sh).Contains(touch.x, touch.y)) {
            SCBDNativeWinner::BeginWinnerPick("EHBUDDEN", 2);
            CloseAndSwallow();
        } else if (WinnerButtonRect(2, sw, sh).Contains(touch.x, touch.y)) {
            SCBDNativeWinner::BeginWinnerPick("TINA", 1);
            SCBDNativeWinner::ShowPickSuccess(14, "KRATOS");
            CloseAndSwallow();
        } else if (WinnerButtonRect(3, sw, sh).Contains(touch.x, touch.y)) {
            SCBDNativeWinner::Cancel();
            SetPanel(Panel::MENU);
        }
        return true;
    }
    if (panel == Panel::INPUT_TEST) {
        for (int i = 0; i < 10; ++i) {
            if (!InputButtonRect(i, sw, sh).Contains(touch.x, touch.y))
                continue;
            if (i == 0) SCBDVirtualInput::QueueTap(CTRL_TRIANGLE);
            if (i == 1) SCBDVirtualInput::QueueTap(CTRL_CIRCLE);
            if (i == 2) SCBDVirtualInput::QueueTap(CTRL_CROSS);
            if (i == 3) SCBDVirtualInput::QueueTap(CTRL_SQUARE);
            if (i == 4) SCBDVirtualInput::QueueTap(CTRL_LEFT);
            if (i == 5) SCBDVirtualInput::QueueTap(CTRL_RIGHT);
            if (i == 6) SCBDVirtualInput::QueueChord(CTRL_TRIANGLE | CTRL_CROSS, 95, 80);
            if (i == 7) SCBDVirtualInput::QueueChord(CTRL_TRIANGLE | CTRL_CIRCLE, 95, 80);
            if (i == 8) SCBDVirtualInput::QueueChord(CTRL_SQUARE | CTRL_TRIANGLE, 95, 80);
            if (i == 9) SCBDVirtualInput::QueueSequence({CTRL_LEFT, CTRL_RIGHT, CTRL_TRIANGLE, CTRL_CROSS}, 70, 55);
            return true;
        }
        return true;
    }
'''

touch_tail = '''    if (panel == Panel::AVATAR_TEST) {
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
    return true;
}
'''
if touch_tail not in emu_text:
    raise SystemExit("V0.5.7 could not find final V0.5.1 touch tail")
emu_text = emu_text.replace(touch_tail, touch_tail.replace("    return true;\n}\n", extra_touch + "    return true;\n}\n"), 1)
emu.write_text(emu_text, encoding="utf-8")

# -----------------------------------------------------------------------------
# 5) DebugOverlay: process engines, hide legacy green memory panel, draw new
#    native Winner Pick layer and DEV panels.
# -----------------------------------------------------------------------------
debug_text = replace_once(
    debug_text,
    '#include "SCBD/SCBDInGameLayerState.h"\n',
    '#include "SCBD/SCBDInGameLayerState.h"\n#include "SCBD/SCBDNativeWinner.h"\n#include "SCBD/SCBDVirtualInput.h"\n',
    "include V0.5.7 runtime headers in DebugOverlay",
)

debug_text = replace_once(
    debug_text,
    "    SCBDInspector::ProcessPending();\n",
    "    SCBDInspector::ProcessPending();\n    SCBDVirtualInput::Process();\n    SCBDNativeWinner::Process();\n",
    "process runtime engines each SCBD overlay frame",
)

legacy_draw = r'''    ctx->Draw()->DrawTextRect(
        ubuntu24,
        w.as_view(),
        x + 2.0f,
        y + 2.0f,
        width,
        height,
        0xD0000000,
        FLAG_DYNAMIC_ASCII
    );
    ctx->Draw()->DrawTextRect(
        ubuntu24,
        w.as_view(),
        x,
        y,
        width,
        height,
        0xFF66FF88,
        FLAG_DYNAMIC_ASCII
    );
'''
legacy_hidden = r'''    // V0.5.7: keep the memory scanner/backend alive, but retire its old
    // green on-screen text panel from normal gameplay.
    static constexpr bool SCBD_LEGACY_MEMORY_INSPECTOR_VISIBLE = false;
    if (SCBD_LEGACY_MEMORY_INSPECTOR_VISIBLE) {
        ctx->Draw()->DrawTextRect(
            ubuntu24,
            w.as_view(),
            x + 2.0f,
            y + 2.0f,
            width,
            height,
            0xD0000000,
            FLAG_DYNAMIC_ASCII
        );
        ctx->Draw()->DrawTextRect(
            ubuntu24,
            w.as_view(),
            x,
            y,
            width,
            height,
            0xFF66FF88,
            FLAG_DYNAMIC_ASCII
        );
    }
'''
debug_text = replace_once(debug_text, legacy_draw, legacy_hidden, "hide legacy green memory panel")

old_title = '    const char *title = page == Panel::RANK ? "SCBD RANKING" : page == Panel::DEV ? "SCBD DEV" : page == Panel::AVATAR_TEST ? "TEST AVATAR BXH" : "SCBD CONTROL";\n'
new_title = '''    const char *title = page == Panel::RANK ? "SCBD RANKING" :
        page == Panel::DEV ? "SCBD DEV" :
        page == Panel::AVATAR_TEST ? "TEST AVATAR BXH" :
        page == Panel::WINNER_TEST ? "NATIVE WINNER TEST" :
        page == Panel::INPUT_TEST ? "INPUT LAB" : "SCBD CONTROL";
'''
debug_text = replace_once(debug_text, old_title, new_title, "extend layer titles")

old_menu = '''        const char *labels[6] = {"BXH","DEV","TEST AVATAR BXH",cfg.matchHudVisible ? "MATCH HUD: ON" : "MATCH HUD: OFF",SCBDAvatarState::Enabled() ? "AVATAR: ON" : "AVATAR: OFF","CLOSE"};
        for (int i = 0; i < 6; ++i) DrawSCBDLayerButton(ctx, font, MenuButtonRect(i, sw, sh), labels[i], i == 2 ? 0xDD315A44 : i == 5 ? 0xDD74343E : 0xDD273244);
'''
new_menu = '''        const char *labels[8] = {
            "BXH", "DEV", "TEST AVATAR BXH",
            cfg.matchHudVisible ? "MATCH HUD: ON" : "MATCH HUD: OFF",
            SCBDAvatarState::Enabled() ? "AVATAR: ON" : "AVATAR: OFF",
            "WINNER TEST", "INPUT LAB", "CLOSE"
        };
        for (int i = 0; i < 8; ++i)
            DrawSCBDLayerButton(ctx, font, MenuButtonRect(i, sw, sh), labels[i], i == 5 ? 0xDD674A28 : i == 6 ? 0xDD315A44 : i == 7 ? 0xDD74343E : 0xDD273244);
'''
debug_text = replace_once(debug_text, old_menu, new_menu, "extend SCBD control menu")

panel_draws = r'''
    if (page == Panel::WINNER_TEST) {
        ctx->Draw()->SetFontScale(0.35f, 0.35f);
        ctx->Draw()->DrawText(
            font,
            "Web Winner V5 van la fallback LIVE. Cac nut nay chi test layer native V1.",
            panel.x + panel.w * 0.5f,
            panel.y + 76.0f,
            0xFFBFD0E0,
            ALIGN_HCENTER | FLAG_DYNAMIC_ASCII
        );
        const char *winnerTests[4] = {
            "TEST FLOW - P1 / TINA",
            "TEST FLOW - P2 / EHBUDDEN",
            "TEST PICK SUCCESS - 14 KRATOS",
            "CANCEL NATIVE WINNER"
        };
        for (int i = 0; i < 4; ++i)
            DrawSCBDLayerButton(ctx, font, WinnerButtonRect(i, sw, sh), winnerTests[i], i == 2 ? 0xDD315A44 : i == 3 ? 0xDD74343E : 0xDD674A28);
    }

    if (page == Panel::INPUT_TEST) {
        const char *inputTests[10] = {
            "TRIANGLE", "CIRCLE", "CROSS", "SQUARE", "LEFT", "RIGHT",
            "TRIANGLE + CROSS", "TRIANGLE + CIRCLE", "SQUARE + TRIANGLE", "SEQ: L R TRI X"
        };
        for (int i = 0; i < 10; ++i)
            DrawSCBDLayerButton(ctx, font, InputButtonRect(i, sw, sh), inputTests[i], i >= 6 ? 0xDD315A44 : 0xDD2C3442);

        char inputStatus[160];
        std::snprintf(
            inputStatus,
            sizeof(inputStatus),
            "ALWAYS ON | ROUTE: PSP PAD / P1 | BUSY:%s | QUEUE:%zu | LAST:0x%04X",
            SCBDVirtualInput::Busy() ? "YES" : "NO",
            SCBDVirtualInput::QueueSize(),
            static_cast<unsigned int>(SCBDVirtualInput::LastMask())
        );
        ctx->Draw()->SetFontScale(0.30f, 0.30f);
        ctx->Draw()->DrawText(
            font,
            inputStatus,
            panel.x + panel.w * 0.5f,
            panel.y + panel.h - 34.0f,
            0xFFBFD0E0,
            ALIGN_HCENTER | FLAG_DYNAMIC_ASCII
        );
    }
'''
reset_marker = "    ctx->Draw()->SetFontScale(1.0f, 1.0f); ctx->Flush(); ctx->RebindTexture();\n}\n\n"
debug_text = insert_before_once(debug_text, reset_marker, panel_draws, "insert Winner/Input DEV panel renderers")

winner_draw = r'''
static int SCBDWinnerCharacterAtlasIndex(const std::string &name, int fallbackId) {
    static const char *kCharacters[28] = {
        "ALGOL","AMY","ASTAROTH","CASSANDRA","CERVANTES","DAMPIERRE","HILDE",
        "IVY","KILIK","KRATOS","LIZARDMAN","MAXI","MITSURUGI","NIGHTMARE",
        "RAPHAEL","ROCK","SEONG_MI_NA","SETSUKA","SIEGFRIED","SOPHITIA","TAKI",
        "TALIM","TIRA","VOLDO","XIANGHUA","YOSHIMITSU","YUN_SEONG","ZASALAMEL"
    };
    for (int i = 0; i < 28; ++i) {
        if (name == kCharacters[i])
            return i;
    }
    return std::clamp(fallbackId - 1, 0, 27);
}

static void DrawSCBDNativeWinnerLayer(UIContext *ctx, FontID font, const Bounds &bounds) {
    const SCBDNativeWinner::Snapshot s = SCBDNativeWinner::Read();
    if (s.phase == SCBDNativeWinner::Phase::NONE)
        return;

    const float cardW = std::min(bounds.w * 0.74f, 760.0f);
    const float cardH = std::min(bounds.h * 0.54f, 330.0f);
    const float x = bounds.x + (bounds.w - cardW) * 0.5f;
    const float y = bounds.y + (bounds.h - cardH) * 0.5f;
    const float cx = x + cardW * 0.5f;

    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->Rect(x - 4.0f, y - 4.0f, cardW + 8.0f, cardH + 8.0f, 0xCCB78335);
    ctx->Draw()->Rect(x, y, cardW, cardH, 0xF0151822);
    ctx->Draw()->Rect(x, y, cardW, 58.0f, s.team == 2 ? 0xE06B3158 : 0xE02C5F8B);
    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();

    if (s.phase == SCBDNativeWinner::Phase::PICK_SUCCESS) {
        ctx->Draw()->SetFontScale(0.58f, 0.58f);
        ctx->Draw()->DrawText(font, "PICK THANH CONG!", cx, y + 31.0f, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);

        const float portraitW = 118.0f;
        const float portraitH = 112.0f;
        const float portraitX = cx - portraitW * 0.5f;
        const float portraitY = y + 83.0f;
        DrawSCBDCharacterPortraitSlot(ctx, font, s.character.c_str(), SCBDWinnerCharacterAtlasIndex(s.character, s.characterId), portraitX, portraitY, portraitW, portraitH);

        char idText[24];
        std::snprintf(idText, sizeof(idText), "%02d", s.characterId);
        ctx->Draw()->SetFontScale(0.54f, 0.54f);
        ctx->Draw()->DrawText(font, idText, x + 72.0f, y + 142.0f, 0xFFFFD86A, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->DrawText(font, s.character.c_str(), cx, y + 220.0f, 0xFFFFD86A, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);

        char success[192];
        std::snprintf(success, sizeof(success), "%s DA CHON THANH CONG", s.username.c_str());
        ctx->Draw()->SetFontScale(0.36f, 0.36f);
        ctx->Draw()->DrawText(font, success, cx, y + 264.0f, 0xFFFFFFFF, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
    } else if (s.phase == SCBDNativeWinner::Phase::TIMEOUT) {
        ctx->Draw()->SetFontScale(0.62f, 0.62f);
        ctx->Draw()->DrawText(font, "HET THOI GIAN", cx, y + 118.0f, 0xFFFFD86A, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->SetFontScale(0.46f, 0.46f);
        ctx->Draw()->DrawText(font, "RANDOM 30", cx, y + 186.0f, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
    } else {
        ctx->Draw()->SetFontScale(0.58f, 0.58f);
        ctx->Draw()->DrawText(font, "TOP 1 WINNER", cx, y + 31.0f, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);

        const float avatarX = x + 86.0f;
        const float avatarY = y + 130.0f;
        ctx->Flush();
        ctx->BeginNoTex();
        ctx->Draw()->FillCircle(avatarX, avatarY, 45.0f, 40, 0xD0000000);
        ctx->Draw()->FillCircle(avatarX, avatarY, 42.0f, 40, s.team == 2 ? 0xE06B78FF : 0xE04CCF70);
        ctx->Flush();
        ctx->Begin();
        ctx->BindFontTexture();
        ctx->Draw()->SetFontScale(0.52f, 0.52f);
        const char initial[2] = {s.username.empty() ? '?' : s.username[0], '\0'};
        ctx->Draw()->DrawText(font, initial, avatarX, avatarY, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);

        ctx->Draw()->SetFontScale(0.48f, 0.48f);
        ctx->Draw()->DrawText(font, s.username.c_str(), x + 156.0f, y + 112.0f, 0xFFFFFFFF, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
        char teamText[64];
        std::snprintf(teamText, sizeof(teamText), "TEAM P%d WINNER", s.team);
        ctx->Draw()->SetFontScale(0.33f, 0.33f);
        ctx->Draw()->DrawText(font, teamText, x + 156.0f, y + 151.0f, 0xFFFFD86A, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);

        const int tenths = std::max(0, s.remainingMs / 100);
        char timerText[64];
        std::snprintf(timerText, sizeof(timerText), "%d.%ds", tenths / 10, tenths % 10);
        ctx->Draw()->SetFontScale(0.62f, 0.62f);
        ctx->Draw()->DrawText(font, timerText, x + cardW - 88.0f, y + 132.0f, 0xFFFFD86A, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);

        ctx->Draw()->SetFontScale(0.42f, 0.42f);
        if (s.phase == SCBDNativeWinner::Phase::WINNER) {
            ctx->Draw()->DrawText(font, "BAN CO QUYEN CHON NHAN VAT TRAN TIEP THEO", cx, y + 225.0f, 0xFFFFFFFF, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
            ctx->Draw()->SetFontScale(0.31f, 0.31f);
            ctx->Draw()->DrawText(font, "PICK PHASE BAT DAU SAU WINNER ANIMATION", cx, y + 267.0f, 0xFFBFD0E0, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
        } else {
            ctx->Draw()->DrawText(font, "HAY CHON NHAN VAT", cx, y + 220.0f, 0xFFFFFFFF, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
            ctx->Draw()->SetFontScale(0.38f, 0.38f);
            ctx->Draw()->DrawText(font, "COMMENT: /pick 1..28", cx, y + 267.0f, 0xFFFFD86A, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
        }
    }

    ctx->Draw()->SetFontScale(1.0f, 1.0f);
    ctx->Flush();
    ctx->RebindTexture();
}

'''
debug_text = insert_before_once(debug_text, "static void DrawSCBDBoneMapper(", winner_draw, "insert native winner renderer")

debug_text = replace_once(
    debug_text,
    "    DrawSCBDInGameLayer(ctx, ubuntu24, bounds);\n",
    "    DrawSCBDInGameLayer(ctx, ubuntu24, bounds);\n    DrawSCBDNativeWinnerLayer(ctx, ubuntu24, bounds);\n",
    "draw native winner layer",
)

debug.write_text(debug_text, encoding="utf-8")

# -----------------------------------------------------------------------------
# 6) Final source sanity checks.
# -----------------------------------------------------------------------------
state_final = state.read_text(encoding="utf-8")
emu_final = emu.read_text(encoding="utf-8")
debug_final = debug.read_text(encoding="utf-8")

required_markers = (
    (state_final, "WINNER_TEST = 5"),
    (state_final, "INPUT_TEST = 6"),
    (emu_final, "SCBDNativeWinner::BeginWinnerPick"),
    (emu_final, "SCBDVirtualInput::QueueChord(CTRL_TRIANGLE | CTRL_CROSS"),
    (debug_final, "SCBD_LEGACY_MEMORY_INSPECTOR_VISIBLE = false"),
    (debug_final, "DrawSCBDNativeWinnerLayer"),
    (debug_final, "PICK THANH CONG!"),
    (debug_final, "WINNER TEST"),
    (debug_final, "INPUT LAB"),
    (debug_final, "SCBDVirtualInput::Process();"),
)
for text, marker in required_markers:
    if marker not in text:
        raise SystemExit(f"V0.5.7 generated source missing marker: {marker}")

# Preserve the known-stable V0.5.6 visual markers.
for marker in (
    "kSCBDRankFrameTuning[7]",
    "radius * 0.78f",
    "active != 3",
    "slot + 1, true",
    "DrawSCBDMatchTop5HUD",
):
    if marker not in debug_final:
        raise SystemExit(f"V0.5.7 regression: V0.5.6 marker missing: {marker}")

with info.open("a", encoding="utf-8") as f:
    f.write(
        "\nPSP Live FloGB V0.5.7 Runtime Core + Native Winner V1\n"
        "Legacy green memory inspector UI hidden; memory backend remains active\n"
        "Native Winner/Pick state machine: Winner 5.5s -> Pick 15s -> Timeout/Random30\n"
        "Native Pick Success test: 14 KRATOS / TINA\n"
        "Web Winner V5 remains the live fallback; no bridge cutover in V0.5.7\n"
        "Always-on Virtual Input Core V1: tap/chord/sequence through PPSSPP sceCtrl\n"
        "Input Lab route in this validation build: physical PSP pad / P1\n"
        "No existing V0.5.6 rank/HUD visuals intentionally changed\n"
    )

print("PSP Live FloGB V0.5.7 Runtime Core + Native Winner V1 patch applied successfully.")
