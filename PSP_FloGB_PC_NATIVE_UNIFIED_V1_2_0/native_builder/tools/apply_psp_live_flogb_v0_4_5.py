from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_4_5.py <ppsspp_repo>")

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

# V0.4.4 must already be applied.
debug = require("UI/DebugOverlay.cpp")
debug_text = debug.read_text(encoding="utf-8")
for marker in (
    "PickSCBDRefinedHead",
    "HEAD V0.4.4",
    "DrawSCBDTestAvatar",
    '#include "SCBD/SCBDAvatarState.h"',
):
    if marker not in debug_text:
        raise SystemExit(f"V0.4.4 prerequisite missing in DebugOverlay.cpp: {marker}")

emu = require("UI/EmuScreen.cpp")
emu_text = emu.read_text(encoding="utf-8")
for marker in (
    "g_scbdAvatarButton",
    "AVATAR ON/OFF",
    "SCBDAvatarState::Toggle",
):
    if marker not in emu_text:
        raise SystemExit(f"V0.4.3+ prerequisite missing in EmuScreen.cpp: {marker}")

# ================================================================
# 1) Shared HUD toggle state
# ================================================================
scbd_dir = repo / "SCBD"
hud_state_h = r'''#pragma once

#include <atomic>

namespace SCBDHUDState {

inline std::atomic<bool> &EnabledAtomic() {
    static std::atomic<bool> enabled{true};
    return enabled;
}

inline bool Enabled() {
    return EnabledAtomic().load(std::memory_order_relaxed);
}

inline bool Toggle() {
    const bool before = EnabledAtomic().load(std::memory_order_relaxed);
    const bool after = !before;
    EnabledAtomic().store(after, std::memory_order_relaxed);
    return after;
}

inline void SetEnabled(bool enabled) {
    EnabledAtomic().store(enabled, std::memory_order_relaxed);
}

}  // namespace SCBDHUDState
'''
(scbd_dir / "SCBDHUDState.h").write_text(hud_state_h, encoding="utf-8")

# ================================================================
# 2) Add HUD ON/OFF button under AVATAR ON/OFF
# ================================================================
s = emu_text

include_anchor = '#include "SCBD/SCBDAvatarState.h"\n'
s = replace_once(
    s,
    include_anchor,
    include_anchor + '#include "SCBD/SCBDHUDState.h"\n',
    "EmuScreen HUD state include",
)

globals_anchor = 'static UI::Button *g_scbdAvatarButton = nullptr;\n'
s = replace_once(
    s,
    globals_anchor,
    globals_anchor + 'static UI::Button *g_scbdHUDButton = nullptr;\n',
    "EmuScreen HUD button global",
)

reset_anchor = '''    g_scbdInspectorButton = nullptr;
    g_scbdAvatarButton = nullptr;
    g_scbdInspectorPanel = nullptr;
'''
s = replace_once(
    s,
    reset_anchor,
    '''    g_scbdInspectorButton = nullptr;
    g_scbdAvatarButton = nullptr;
    g_scbdHUDButton = nullptr;
    g_scbdInspectorPanel = nullptr;
''',
    "EmuScreen HUD button reset",
)

avatar_block_end = '''        g_scbdAvatarButton->OnClick.Add([](UI::EventParams &) {
            const bool enabled = SCBDAvatarState::Toggle();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                enabled ? "Avatar test ON" : "Avatar test OFF",
                1.5f,
                "scbd_avatar_toggle"
            );
        });

'''
hud_button_block = avatar_block_end + r'''        g_scbdHUDButton = root_->Add(
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
s = replace_once(
    s,
    avatar_block_end,
    hud_button_block,
    "EmuScreen HUD toggle control",
)

avatar_visibility = '''    if (g_scbdAvatarButton) {
        g_scbdAvatarButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

'''
s = replace_once(
    s,
    avatar_visibility,
    avatar_visibility + '''    if (g_scbdHUDButton) {
        g_scbdHUDButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

''',
    "EmuScreen HUD button visibility",
)

emu.write_text(s, encoding="utf-8")

# ================================================================
# 3) Draw native dual-team ranking HUD (MOCK data for layout test)
# ================================================================
s = debug_text

include_anchor = '#include "SCBD/SCBDAvatarState.h"\n'
s = replace_once(
    s,
    include_anchor,
    include_anchor + '#include "SCBD/SCBDHUDState.h"\n',
    "DebugOverlay HUD state include",
)

hud_helpers = r'''static void DrawSCBDTeamHUD(
    UIContext *ctx,
    FontID font,
    const Bounds &bounds
) {
    if (!SCBDHUDState::Enabled())
        return;

    // V0.4.5 intentionally uses deterministic mock leaderboard data.
    // This test is only for native in-game layout, visibility and FPS impact.
    // Live TikTok data will replace these strings after the HUD itself passes.
    const char *p1Text =
        "TEAM P1   12,500\n"
        "1. TOP1_P1      5,000\n"
        "2. VIEWER_P1_2  4,000\n"
        "3. VIEWER_P1_3  3,500";

    const char *p2Text =
        "TEAM P2   10,200\n"
        "1. TOP1_P2      6,000\n"
        "2. VIEWER_P2_2  2,500\n"
        "3. VIEWER_P2_3  1,700";

    const float panelW = std::min(245.0f, bounds.w * 0.34f);
    const float panelH = 112.0f;
    const float leftX = bounds.x + 12.0f;
    const float rightX = bounds.x + bounds.w - panelW - 12.0f;
    const float topY = bounds.y + 14.0f;

    ctx->Flush();
    ctx->BindFontTexture();
    ctx->Draw()->SetFontScale(0.42f, 0.42f);

    // Shadow pass gives the ranking readable pseudo-panels without touching
    // the game framebuffer or requiring texture assets.
    ctx->Draw()->DrawTextRect(
        font,
        p1Text,
        leftX + 2.0f,
        topY + 2.0f,
        panelW,
        panelH,
        0xE0000000,
        FLAG_DYNAMIC_ASCII
    );
    ctx->Draw()->DrawTextRect(
        font,
        p1Text,
        leftX,
        topY,
        panelW,
        panelH,
        0xFF66FF88,
        FLAG_DYNAMIC_ASCII
    );

    ctx->Draw()->DrawTextRect(
        font,
        p2Text,
        rightX + 2.0f,
        topY + 2.0f,
        panelW,
        panelH,
        0xE0000000,
        FLAG_DYNAMIC_ASCII
    );
    ctx->Draw()->DrawTextRect(
        font,
        p2Text,
        rightX,
        topY,
        panelW,
        panelH,
        0xFFFF8877,
        FLAG_DYNAMIC_ASCII
    );

    const char *centerText = "BXH TEST V0.4.5 | MOCK DATA";
    ctx->Draw()->SetFontScale(0.36f, 0.36f);
    ctx->Draw()->DrawText(
        font,
        centerText,
        bounds.x + bounds.w * 0.5f + 1.0f,
        topY + 1.0f,
        0xE0000000,
        ALIGN_HCENTER | FLAG_DYNAMIC_ASCII
    );
    ctx->Draw()->DrawText(
        font,
        centerText,
        bounds.x + bounds.w * 0.5f,
        topY,
        0xFFFFFFFF,
        ALIGN_HCENTER | FLAG_DYNAMIC_ASCII
    );

    ctx->Draw()->SetFontScale(1.0f, 1.0f);
    ctx->Flush();
    ctx->RebindTexture();
}

'''
mapper_anchor = 'static void DrawSCBDBoneMapper(UIContext *ctx, const Bounds &bounds) {'
if s.count(mapper_anchor) != 1:
    raise SystemExit("V0.4.4 mapper anchor missing or duplicated")
s = s.replace(mapper_anchor, hud_helpers + mapper_anchor, 1)

avatar_calls = '''    DrawSCBDTestAvatar(ctx, ubuntu24, p1Head, 1);
    DrawSCBDTestAvatar(ctx, ubuntu24, p2Head, 2);

'''
s = replace_once(
    s,
    avatar_calls,
    avatar_calls + '''    DrawSCBDTeamHUD(ctx, ubuntu24, bounds);

''',
    "Draw dual-team HUD after player avatars",
)

s = replace_once(
    s,
    '"HEAD V0.4.4 | AVATAR:%s | CAM:%s F:%u | "',
    '"HUD V0.4.5 | AVATAR:%s | CAM:%s F:%u | "',
    "V0.4.5 runtime diagnostic label",
)

debug.write_text(s, encoding="utf-8")

# ================================================================
# 4) Build marker
# ================================================================
info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")
info.write_text(
    "PSP Live FloGB V0.4.5 Dual Team HUD Test\\n"
    "Target: Soulcalibur Broken Destiny ULUS-10457\\n"
    "Package: com.scbd.vieweremulator\\n"
    "Base: V0.4.4 Head Picker Refinement fully preserved\\n"
    "Avatar: current body/head anchor behavior preserved, no tracker changes\\n"
    "HUD: native in-game P1/P2 Top 3 ranking layer, default ON\\n"
    "HUD data: MOCK only in V0.4.5 for layout/performance test\\n"
    "UI: HUD ON/OFF button below AVATAR ON/OFF\\n"
    "Next after PASS: replace mock rows with live TikTok team leaderboard data\\n",
    encoding="utf-8",
)

print("PSP Live FloGB V0.4.5 Dual Team HUD Test patch applied successfully.")
