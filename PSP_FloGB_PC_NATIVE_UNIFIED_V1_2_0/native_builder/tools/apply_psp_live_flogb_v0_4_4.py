from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_4_4.py <ppsspp_repo>")

repo = Path(sys.argv[1]).resolve()

def require(rel):
    p = repo / rel
    if not p.exists():
        raise SystemExit(f"Missing expected path: {rel}")
    return p

def replace_between(text, start, end, replacement, label):
    count = text.count(start)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 start marker, found {count}")
    a = text.find(start)
    b = text.find(end, a + len(start))
    if b < 0:
        raise SystemExit(f"{label}: end marker missing")
    return text[:a] + replacement + text[b:]

debug = require("UI/DebugOverlay.cpp")
s = debug.read_text(encoding="utf-8")

for marker in (
    "struct SCBDDynamicHeadState",
    "static SCBDDynamicHead UpdateSCBDDynamicHead(",
    "static void DrawSCBDTestAvatar(",
    "HEAD V0.4.3",
):
    if marker not in s:
        raise SystemExit(f"V0.4.3 prerequisite missing: {marker}")

refined_helpers = r'''struct SCBDDynamicHeadState {
    static constexpr int kResetMissingFrames = 24;
    static constexpr int kSwitchHoldFrames = 4;

    u32 fighter = 0;
    int currentIndex = -1;
    int pendingIndex = -1;
    int pendingFrames = 0;
    int missingFrames = 0;

    bool smoothValid = false;
    float smoothX = 0.0f;
    float smoothY = 0.0f;

    bool lastPSPValid = false;
    float lastPSPX = 0.0f;
    float lastPSPY = 0.0f;
};

struct SCBDDynamicHead {
    bool visible = false;
    int index = -1;
    int proposal = -1;
    float score = 0.0f;
    float x = 0.0f;
    float y = 0.0f;
};

struct SCBDHeadPick {
    int index = -1;
    float score = -1000000.0f;
    float bodyX = 0.0f;
    float targetY = 0.0f;
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
    state.lastPSPValid = false;
    state.lastPSPX = 0.0f;
    state.lastPSPY = 0.0f;
}

static float SCBDPercentile(std::vector<float> values, float p) {
    if (values.empty())
        return 0.0f;

    std::sort(values.begin(), values.end());

    if (p <= 0.0f)
        return values.front();
    if (p >= 1.0f)
        return values.back();

    const float pos = p * static_cast<float>(values.size() - 1);
    const size_t lo = static_cast<size_t>(pos);
    const size_t hi = std::min(lo + 1, values.size() - 1);
    const float t = pos - static_cast<float>(lo);
    return values[lo] * (1.0f - t) + values[hi] * t;
}

static int SCBDLocalBoneDensity(
    const std::vector<SCBDScreenBone> &bones,
    const SCBDScreenBone &center
) {
    int count = 0;

    for (const auto &other : bones) {
        const float dx = other.pspX - center.pspX;
        const float dy = other.pspY - center.pspY;

        if (std::fabs(dx) <= 24.0f &&
            std::fabs(dy) <= 20.0f &&
            dx * dx + dy * dy <= 26.0f * 26.0f) {
            ++count;
        }
    }

    return count;
}

static SCBDHeadPick PickSCBDRefinedHead(
    const std::vector<SCBDScreenBone> &bones,
    const SCBDDynamicHeadState &state
) {
    SCBDHeadPick out{};
    if (bones.empty())
        return out;

    std::vector<float> allX;
    std::vector<float> allY;
    allX.reserve(bones.size());
    allY.reserve(bones.size());

    for (const auto &b : bones) {
        allX.push_back(b.pspX);
        allY.push_back(b.pspY);
    }

    const float y25 = SCBDPercentile(allY, 0.25f);
    const float y35 = SCBDPercentile(allY, 0.35f);
    const float y55 = SCBDPercentile(allY, 0.55f);
    const float y75 = SCBDPercentile(allY, 0.75f);

    std::vector<float> torsoX;
    torsoX.reserve(bones.size());
    for (const auto &b : bones) {
        if (b.pspY >= y35 && b.pspY <= y75)
            torsoX.push_back(b.pspX);
    }

    if (torsoX.size() < 4)
        torsoX = allX;

    const float bodyX = SCBDPercentile(torsoX, 0.50f);
    const float x25 = SCBDPercentile(torsoX, 0.25f);
    const float x75 = SCBDPercentile(torsoX, 0.75f);
    const float coreWidth = std::max(1.0f, x75 - x25);

    // Aim near the upper quartile, not the absolute top-most bone.
    const float targetY = y25;
    const float upperLimit = y55 + 2.0f;

    const float centerLimit =
        std::max(34.0f, std::min(72.0f, coreWidth * 2.0f + 18.0f));

    out.bodyX = bodyX;
    out.targetY = targetY;

    bool foundStrict = false;

    for (const auto &b : bones) {
        const float centerDist = std::fabs(b.pspX - bodyX);

        if (b.pspY > upperLimit || centerDist > centerLimit)
            continue;

        const int density = SCBDLocalBoneDensity(bones, b);
        const float verticalError = std::fabs(b.pspY - targetY);

        float score =
            static_cast<float>(density) * 11.0f -
            verticalError * 1.35f -
            centerDist * 1.45f;

        if (state.lastPSPValid) {
            const float dx = b.pspX - state.lastPSPX;
            const float dy = b.pspY - state.lastPSPY;
            const float dist = std::sqrt(dx * dx + dy * dy);
            score -= dist * 1.65f;
        }

        if (b.index == state.currentIndex)
            score += 16.0f;

        if (!foundStrict || score > out.score) {
            foundStrict = true;
            out.index = b.index;
            out.score = score;
        }
    }

    if (foundStrict)
        return out;

    for (const auto &b : bones) {
        const int density = SCBDLocalBoneDensity(bones, b);
        const float centerDist = std::fabs(b.pspX - bodyX);
        const float verticalError = std::fabs(b.pspY - targetY);

        float score =
            static_cast<float>(density) * 8.0f -
            verticalError * 1.0f -
            centerDist * 1.1f;

        if (state.lastPSPValid) {
            const float dx = b.pspX - state.lastPSPX;
            const float dy = b.pspY - state.lastPSPY;
            score -= std::sqrt(dx * dx + dy * dy) * 1.2f;
        }

        if (b.index == state.currentIndex)
            score += 12.0f;

        if (out.index < 0 || score > out.score) {
            out.index = b.index;
            out.score = score;
        }
    }

    return out;
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

    if (fighter.fighter != state.fighter)
        ResetSCBDDynamicHeadState(state, fighter.fighter);

    if (!fighter.valid || bones.empty()) {
        ++state.missingFrames;
        if (state.missingFrames >= SCBDDynamicHeadState::kResetMissingFrames)
            ResetSCBDDynamicHeadState(state, 0);
        return out;
    }

    state.missingFrames = 0;

    const SCBDHeadPick pick = PickSCBDRefinedHead(bones, state);
    out.proposal = pick.index;
    out.score = pick.score;

    if (pick.index < 0)
        return out;

    const SCBDScreenBone *proposalBone =
        FindSCBDScreenBone(bones, pick.index);
    if (!proposalBone)
        return out;

    if (state.currentIndex < 0) {
        state.currentIndex = pick.index;
        state.pendingIndex = -1;
        state.pendingFrames = 0;
    } else if (pick.index != state.currentIndex) {
        const SCBDScreenBone *currentBone =
            FindSCBDScreenBone(bones, state.currentIndex);

        if (!currentBone) {
            state.currentIndex = pick.index;
            state.pendingIndex = -1;
            state.pendingFrames = 0;
        } else {
            if (state.pendingIndex == pick.index) {
                ++state.pendingFrames;
            } else {
                state.pendingIndex = pick.index;
                state.pendingFrames = 1;
            }

            if (state.pendingFrames >= SCBDDynamicHeadState::kSwitchHoldFrames) {
                state.currentIndex = pick.index;
                state.pendingIndex = -1;
                state.pendingFrames = 0;
            }
        }
    } else {
        state.pendingIndex = -1;
        state.pendingFrames = 0;
    }

    const SCBDScreenBone *target =
        FindSCBDScreenBone(bones, state.currentIndex);

    if (!target) {
        state.currentIndex = pick.index;
        target = proposalBone;
    }

    state.lastPSPValid = true;
    state.lastPSPX = target->pspX;
    state.lastPSPY = target->pspY;

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
    const uint32_t border = 0xFFFFFFFF;

    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->FillCircle(centerX, centerY, radius + 4.0f, 40, 0xD0000000);
    ctx->Draw()->FillCircle(centerX, centerY, radius + 2.0f, 40, border);
    ctx->Draw()->FillCircle(centerX, centerY, radius, 40, fill);
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
    "struct SCBDDynamicHeadState {",
    "static void DrawSCBDBoneMapper(",
    refined_helpers,
    "replace V0.4.3 head picker with refined picker",
)

old_summary = (
    '        "HEAD V0.4.3 | AVATAR:%s | CAM:%s F:%u | "\n'
    '        "P1 F:%08X B:%08X N:%zu H#%d P#%d | "\n'
    '        "P2 F:%08X B:%08X N:%zu H#%d P#%d",\n'
)
new_summary = (
    '        "HEAD V0.4.4 | AVATAR:%s | CAM:%s F:%u | "\n'
    '        "P1 F:%08X B:%08X N:%zu H#%d P#%d S:%.1f | "\n'
    '        "P2 F:%08X B:%08X N:%zu H#%d P#%d S:%.1f",\n'
)
if s.count(old_summary) != 1:
    raise SystemExit("V0.4.3 summary format anchor missing")
s = s.replace(old_summary, new_summary, 1)

old_args = (
    "        p1Head.index,\n"
    "        p1Head.proposal,\n"
    "        p2.fighter,\n"
)
new_args = (
    "        p1Head.index,\n"
    "        p1Head.proposal,\n"
    "        p1Head.score,\n"
    "        p2.fighter,\n"
)
if s.count(old_args) != 1:
    raise SystemExit("V0.4.3 P1 summary args anchor missing")
s = s.replace(old_args, new_args, 1)

old_p2_args = (
    "        p2Head.index,\n"
    "        p2Head.proposal\n"
    "    );\n"
)
new_p2_args = (
    "        p2Head.index,\n"
    "        p2Head.proposal,\n"
    "        p2Head.score\n"
    "    );\n"
)
if s.count(old_p2_args) != 1:
    raise SystemExit("V0.4.3 P2 summary args anchor missing")
s = s.replace(old_p2_args, new_p2_args, 1)

debug.write_text(s, encoding="utf-8")

info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")
info.write_text(
    "PSP Live FloGB V0.4.4 Head Picker Refinement\\n"
    "Target: Soulcalibur Broken Destiny ULUS-10457\\n"
    "Package: com.scbd.vieweremulator\\n"
    "Base: V0.4.3 Dynamic Head Avatar preserved\\n"
    "Fix: reject hand/weapon head candidates using robust body core\\n"
    "Picker: torso X + upper quartile target + local bone density + temporal continuity\\n"
    "Switching: 4-frame hysteresis; no distance-triggered instant jump\\n"
    "Avatar ON/OFF button and circular P1/P2 test avatars preserved\\n"
    "Camera/fighter/bone reader unchanged from PASS baseline\\n",
    encoding="utf-8",
)

print("PSP Live FloGB V0.4.4 Head Picker Refinement patch applied successfully.")
