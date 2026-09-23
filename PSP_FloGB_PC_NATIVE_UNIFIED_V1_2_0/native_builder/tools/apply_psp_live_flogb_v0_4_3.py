from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_4_3.py <ppsspp_repo>")

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
    if text.count(start) != 1:
        raise SystemExit(f"{label}: expected exactly 1 start marker, found {text.count(start)}")
    a = text.find(start)
    b = text.find(end, a + len(start))
    if b < 0:
        raise SystemExit(f"{label}: end marker missing")
    return text[:a] + replacement + text[b:]

# V0.4.2 must already be applied.
debug = require("UI/DebugOverlay.cpp")
debug_text = debug.read_text(encoding="utf-8")
for marker in (
    "struct SCBDHeadTrackerState",
    "static SCBDTrackedHead UpdateSCBDHeadTracker(",
    "HEAD V0.4.2",
):
    if marker not in debug_text:
        raise SystemExit(f"V0.4.2 prerequisite missing: {marker}")

emu = require("UI/EmuScreen.cpp")
emu_text = emu.read_text(encoding="utf-8")
for marker in (
    "g_scbdInspectorButton",
    "g_scbdInspectorPanel",
    "SCBDInspector::TogglePanel",
):
    if marker not in emu_text:
        raise SystemExit(f"V0.3 UI prerequisite missing: {marker}")

# ================================================================
# 1) Shared avatar toggle state
# ================================================================
scbd_dir = repo / "SCBD"
avatar_state_h = r'''#pragma once

#include <atomic>

namespace SCBDAvatarState {

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

}  // namespace SCBDAvatarState
'''
(scbd_dir / "SCBDAvatarState.h").write_text(avatar_state_h, encoding="utf-8")

# ================================================================
# 2) Add AVATAR ON/OFF touch button beside MEM
# ================================================================
s = emu_text

include_anchor = '#include "SCBD/SCBDMemoryInspector.h"\n'
s = replace_once(
    s,
    include_anchor,
    include_anchor + '#include "SCBD/SCBDAvatarState.h"\n',
    "EmuScreen avatar state include",
)

globals_anchor = 'static UI::Button *g_scbdInspectorButton = nullptr;\n'
s = replace_once(
    s,
    globals_anchor,
    globals_anchor + 'static UI::Button *g_scbdAvatarButton = nullptr;\n',
    "EmuScreen avatar button global",
)

reset_anchor = '''    g_scbdInspectorButton = nullptr;
    g_scbdInspectorPanel = nullptr;
'''
s = replace_once(
    s,
    reset_anchor,
    '''    g_scbdInspectorButton = nullptr;
    g_scbdAvatarButton = nullptr;
    g_scbdInspectorPanel = nullptr;
''',
    "EmuScreen avatar button reset",
)

mem_button_block = '''        g_scbdInspectorButton->OnClick.Add([](UI::EventParams &) {
            SCBDInspector::TogglePanel();
        });

'''
avatar_button_block = r'''        g_scbdInspectorButton->OnClick.Add([](UI::EventParams &) {
            SCBDInspector::TogglePanel();
        });

        g_scbdAvatarButton = root_->Add(
            new Button(
                "AVATAR ON/OFF",
                new AnchorLayoutParams(150, 50, NONE, 10, 110, NONE)
            )
        );
        g_scbdAvatarButton->SetScale(0.62f);
        g_scbdAvatarButton->OnClick.Add([](UI::EventParams &) {
            const bool enabled = SCBDAvatarState::Toggle();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                enabled ? "Avatar test ON" : "Avatar test OFF",
                1.5f,
                "scbd_avatar_toggle"
            );
        });

'''
s = replace_once(
    s,
    mem_button_block,
    avatar_button_block,
    "EmuScreen avatar toggle control",
)

visibility_anchor = '''    if (g_scbdInspectorButton) {
        g_scbdInspectorButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

'''
visibility_new = visibility_anchor + '''    if (g_scbdAvatarButton) {
        g_scbdAvatarButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

'''
s = replace_once(
    s,
    visibility_anchor,
    visibility_new,
    "EmuScreen avatar button visibility",
)

emu.write_text(s, encoding="utf-8")

# ================================================================
# 3) Dynamic head tracking: no LEARN/LOCK, no boneArray reset
# ================================================================
s = debug_text

include_anchor = '#include "SCBD/SCBDBoneMapper.h"\n'
if include_anchor not in s:
    raise SystemExit("DebugOverlay SCBDBoneMapper include missing")
s = replace_once(
    s,
    include_anchor,
    include_anchor + '#include "SCBD/SCBDAvatarState.h"\n',
    "DebugOverlay avatar state include",
)

dynamic_helpers = r'''struct SCBDDynamicHeadState {
    static constexpr int kResetMissingFrames = 24;
    static constexpr int kSwitchHoldFrames = 3;

    u32 fighter = 0;
    int currentIndex = -1;
    int pendingIndex = -1;
    int pendingFrames = 0;
    int missingFrames = 0;

    bool smoothValid = false;
    float smoothX = 0.0f;
    float smoothY = 0.0f;
};

struct SCBDDynamicHead {
    bool visible = false;
    int index = -1;
    int proposal = -1;
    float x = 0.0f;
    float y = 0.0f;
};

static SCBDDynamicHeadState &GetSCBDDynamicHeadState(int player) {
    static SCBDDynamicHeadState p1;
    static SCBDDynamicHeadState p2;
    return player == 2 ? p2 : p1;
}

static void ResetSCBDDynamicHeadState(
    SCBDDynamicHeadState &state,
    u32 fighter
) {
    state.fighter = fighter;
    state.currentIndex = -1;
    state.pendingIndex = -1;
    state.pendingFrames = 0;
    state.missingFrames = 0;
    state.smoothValid = false;
    state.smoothX = 0.0f;
    state.smoothY = 0.0f;
}

static void SmoothSCBDDynamicHead(
    SCBDDynamicHeadState &state,
    float targetX,
    float targetY
) {
    if (!state.smoothValid) {
        state.smoothX = targetX;
        state.smoothY = targetY;
        state.smoothValid = true;
        return;
    }

    const float dx = targetX - state.smoothX;
    const float dy = targetY - state.smoothY;
    const float distance = std::sqrt(dx * dx + dy * dy);

    float alpha = 0.30f;
    if (distance > 90.0f)
        alpha = 0.86f;
    else if (distance > 40.0f)
        alpha = 0.62f;
    else if (distance > 18.0f)
        alpha = 0.44f;

    state.smoothX += dx * alpha;
    state.smoothY += dy * alpha;
}

static SCBDDynamicHead UpdateSCBDDynamicHead(
    int player,
    const SCBDBoneMapper::FighterState &fighter,
    const std::vector<SCBDScreenBone> &bones
) {
    SCBDDynamicHead out{};
    SCBDDynamicHeadState &state = GetSCBDDynamicHeadState(player);

    // IMPORTANT: boneArray is a rotating/animation transform buffer in SCBD.
    // V0.4.2 incorrectly treated it as fighter identity. Only the fighter
    // pointer itself identifies the current P1/P2 object.
    if (fighter.fighter != state.fighter) {
        ResetSCBDDynamicHeadState(state, fighter.fighter);
    }

    if (!fighter.valid || bones.empty()) {
        ++state.missingFrames;
        if (state.missingFrames >= SCBDDynamicHeadState::kResetMissingFrames)
            ResetSCBDDynamicHeadState(state, 0);
        return out;
    }

    state.missingFrames = 0;

    const int proposal = PickSCBDAutoHead(bones);
    out.proposal = proposal;
    if (proposal < 0)
        return out;

    const SCBDScreenBone *proposalBone =
        FindSCBDScreenBone(bones, proposal);
    if (!proposalBone)
        return out;

    if (state.currentIndex < 0) {
        state.currentIndex = proposal;
        state.pendingIndex = -1;
        state.pendingFrames = 0;
    } else if (proposal != state.currentIndex) {
        const SCBDScreenBone *currentBone =
            FindSCBDScreenBone(bones, state.currentIndex);

        bool switchNow = currentBone == nullptr;

        if (currentBone) {
            const float dx = proposalBone->outX - currentBone->outX;
            const float dy = proposalBone->outY - currentBone->outY;
            const float distance = std::sqrt(dx * dx + dy * dy);

            // If the newly detected head is clearly elsewhere, follow it
            // immediately. Nearby head/helmet bones need a few stable frames
            // before switching to avoid 117/118/119 chatter.
            if (distance > 34.0f)
                switchNow = true;
        }

        if (!switchNow) {
            if (state.pendingIndex == proposal) {
                ++state.pendingFrames;
            } else {
                state.pendingIndex = proposal;
                state.pendingFrames = 1;
            }

            if (state.pendingFrames >= SCBDDynamicHeadState::kSwitchHoldFrames)
                switchNow = true;
        }

        if (switchNow) {
            state.currentIndex = proposal;
            state.pendingIndex = -1;
            state.pendingFrames = 0;
        }
    } else {
        state.pendingIndex = -1;
        state.pendingFrames = 0;
    }

    const SCBDScreenBone *target =
        FindSCBDScreenBone(bones, state.currentIndex);

    if (!target) {
        state.currentIndex = proposal;
        target = proposalBone;
    }

    SmoothSCBDDynamicHead(state, target->outX, target->outY);

    out.visible = state.smoothValid;
    out.index = state.currentIndex;
    out.x = state.smoothX;
    out.y = state.smoothY;
    return out;
}

static void DrawSCBDTestAvatar(
    UIContext *ctx,
    FontID font,
    const SCBDDynamicHead &head,
    int player
) {
    if (!head.visible || !SCBDAvatarState::Enabled())
        return;

    const float centerX = head.x;
    const float centerY = head.y - 10.0f;
    const float radius = 28.0f;

    const uint32_t fill =
        player == 1 ? 0xE04CCF70 : 0xE06B78FF;
    const uint32_t border =
        player == 1 ? 0xFFFFFFFF : 0xFFFFFFFF;

    ctx->Flush();
    ctx->BeginNoTex();

    ctx->Draw()->FillCircle(
        centerX,
        centerY,
        radius + 4.0f,
        40,
        0xD0000000
    );
    ctx->Draw()->FillCircle(
        centerX,
        centerY,
        radius + 2.0f,
        40,
        border
    );
    ctx->Draw()->FillCircle(
        centerX,
        centerY,
        radius,
        40,
        fill
    );

    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();
    ctx->Draw()->SetFontScale(0.62f, 0.62f);

    ctx->Draw()->DrawText(
        font,
        player == 1 ? "P1" : "P2",
        centerX,
        centerY,
        0xFFFFFFFF,
        ALIGN_CENTER | FLAG_DYNAMIC_ASCII
    );

    ctx->Draw()->SetFontScale(1.0f, 1.0f);
    ctx->Flush();
    ctx->RebindTexture();
}

'''

s = replace_between(
    s,
    "struct SCBDHeadTrackerState {",
    "static void DrawSCBDBoneMapper(",
    dynamic_helpers,
    "replace V0.4.2 learning tracker with dynamic tracker",
)

new_mapper = r'''static void DrawSCBDBoneMapper(UIContext *ctx, const Bounds &bounds) {
    const SCBDBoneMapper::CameraSnapshot camera =
        SCBDBoneMapper::ReadCamera();

    const SCBDBoneMapper::FighterState p1 =
        SCBDBoneMapper::ReadFighter(1);
    const SCBDBoneMapper::FighterState p2 =
        SCBDBoneMapper::ReadFighter(2);

    DisplayLayoutConfig &layout =
        g_Config.GetDisplayLayoutConfig(g_display.GetDeviceOrientation());

    FRect frame{
        bounds.x,
        bounds.y,
        bounds.w,
        bounds.h
    };

    FRect outputRect{};
    CalculateDisplayOutputRect(
        layout,
        &outputRect,
        480.0f,
        272.0f,
        frame,
        layout.iInternalScreenRotation
    );

    std::vector<SCBDScreenBone> p1Bones;
    std::vector<SCBDScreenBone> p2Bones;

    if (camera.valid && p1.valid)
        p1Bones = CollectSCBDScreenBones(p1, camera, outputRect);
    if (camera.valid && p2.valid)
        p2Bones = CollectSCBDScreenBones(p2, camera, outputRect);

    const SCBDDynamicHead p1Head =
        UpdateSCBDDynamicHead(1, p1, p1Bones);
    const SCBDDynamicHead p2Head =
        UpdateSCBDDynamicHead(2, p2, p2Bones);

    FontID ubuntu24("UBUNTU24");

    DrawSCBDTestAvatar(ctx, ubuntu24, p1Head, 1);
    DrawSCBDTestAvatar(ctx, ubuntu24, p2Head, 2);

    ctx->Flush();
    ctx->BindFontTexture();

    char summary[640];
    std::snprintf(
        summary,
        sizeof(summary),
        "HEAD V0.4.3 | AVATAR:%s | CAM:%s F:%u | "
        "P1 F:%08X B:%08X N:%zu H#%d P#%d | "
        "P2 F:%08X B:%08X N:%zu H#%d P#%d",
        SCBDAvatarState::Enabled() ? "ON" : "OFF",
        camera.valid ? "OK" : "WAIT",
        camera.flip,
        p1.fighter,
        p1.boneArray,
        p1Bones.size(),
        p1Head.index,
        p1Head.proposal,
        p2.fighter,
        p2.boneArray,
        p2Bones.size(),
        p2Head.index,
        p2Head.proposal
    );

    ctx->Draw()->SetFontScale(0.38f, 0.38f);
    ctx->Draw()->DrawTextRect(
        ubuntu24,
        summary,
        bounds.x + 12.0f,
        bounds.y + bounds.h - 34.0f,
        bounds.w - 24.0f,
        28.0f,
        0xFFFFFFFF,
        FLAG_DYNAMIC_ASCII
    );

    ctx->Draw()->SetFontScale(1.0f, 1.0f);
    ctx->Flush();
    ctx->RebindTexture();
}

'''

s = replace_between(
    s,
    "static void DrawSCBDBoneMapper(",
    "\n}  // namespace\n",
    new_mapper,
    "replace V0.4.2 mapper with V0.4.3 avatar mapper",
)

debug.write_text(s, encoding="utf-8")

# ================================================================
# 4) Build marker
# ================================================================
info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")
info.write_text(
    "PSP Live FloGB V0.4.3 Dynamic Head Avatar Test\\n"
    "Target: Soulcalibur Broken Destiny ULUS-10457\\n"
    "Package: com.scbd.vieweremulator\\n"
    "Base: V0.3 + V0.4 + V0.4.1 + V0.4.2 preserved\\n"
    "Fix: boneArray changes no longer reset head tracking\\n"
    "Head: dynamic per-frame proposal with 3-frame local hysteresis\\n"
    "Smoothing: adaptive EMA retained\\n"
    "Avatar test: native circular P1/P2 badges, default ON\\n"
    "UI: AVATAR ON/OFF button beside MEM\\n"
    "Camera/fighter/bone reader unchanged from PASS baseline\\n",
    encoding="utf-8",
)

print("PSP Live FloGB V0.4.3 Dynamic Head Avatar patch applied successfully.")
