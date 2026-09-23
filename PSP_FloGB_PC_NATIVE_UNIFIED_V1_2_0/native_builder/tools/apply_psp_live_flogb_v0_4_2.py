from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_4_2.py <ppsspp_repo>")

repo = Path(sys.argv[1]).resolve()

def require(rel):
    p = repo / rel
    if not p.exists():
        raise SystemExit(f"Missing expected path: {rel}")
    return p

def replace_between(text, start, end, replacement, label):
    start_count = text.count(start)
    if start_count != 1:
        raise SystemExit(f"{label}: expected 1 start marker, found {start_count}")
    a = text.find(start)
    b = text.find(end, a + len(start))
    if b < 0:
        raise SystemExit(f"{label}: end marker missing")
    return text[:a] + replacement + text[b:]

# V0.4.1 must already be applied.
bone = require("SCBD/SCBDBoneMapper.h")
bone_text = bone.read_text(encoding="utf-8")
for marker in (
    "kDataLoadVA",
    "kExpectedP1Fighter",
    "kExpectedP2Fighter",
):
    if marker not in bone_text:
        raise SystemExit(f"V0.4.1 prerequisite missing: {marker}")

p = require("UI/DebugOverlay.cpp")
s = p.read_text(encoding="utf-8")

for marker in (
    "static int PickSCBDAutoHead(",
    "static void DrawSCBDBoneSet(",
    "static void DrawSCBDBoneMapper(",
):
    if marker not in s:
        raise SystemExit(f"V0.4 prerequisite missing: {marker}")

tracker_helpers = r'''struct SCBDHeadTrackerState {
    static constexpr int kBoneCount = SCBDBoneMapper::kScanBones;
    static constexpr int kLearningSamples = 45;
    static constexpr int kResetMissingFrames = 24;

    int votes[kBoneCount]{};
    int sampleCount = 0;
    int lockedIndex = -1;
    int bestVotes = 0;
    int missingFrames = 0;

    bool smoothValid = false;
    float smoothX = 0.0f;
    float smoothY = 0.0f;

    u32 fighter = 0;
    u32 boneArray = 0;
};

struct SCBDTrackedHead {
    bool visible = false;
    bool locked = false;
    int index = -1;
    int sampleCount = 0;
    int bestVotes = 0;
    float x = 0.0f;
    float y = 0.0f;
};

static SCBDHeadTrackerState &GetSCBDHeadTracker(int player) {
    static SCBDHeadTrackerState p1;
    static SCBDHeadTrackerState p2;
    return player == 2 ? p2 : p1;
}

static void ResetSCBDHeadTracker(
    SCBDHeadTrackerState &state,
    u32 fighter,
    u32 boneArray
) {
    for (int &vote : state.votes)
        vote = 0;

    state.sampleCount = 0;
    state.lockedIndex = -1;
    state.bestVotes = 0;
    state.missingFrames = 0;
    state.smoothValid = false;
    state.smoothX = 0.0f;
    state.smoothY = 0.0f;
    state.fighter = fighter;
    state.boneArray = boneArray;
}

static int BestSCBDHeadVote(
    const SCBDHeadTrackerState &state,
    int *bestVotes
) {
    int bestIndex = -1;
    int votes = 0;

    for (int i = 0; i < SCBDHeadTrackerState::kBoneCount; ++i) {
        if (state.votes[i] > votes) {
            votes = state.votes[i];
            bestIndex = i;
        }
    }

    if (bestVotes)
        *bestVotes = votes;
    return bestIndex;
}

static void SmoothSCBDHead(
    SCBDHeadTrackerState &state,
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
        alpha = 0.82f;
    else if (distance > 40.0f)
        alpha = 0.58f;
    else if (distance > 18.0f)
        alpha = 0.42f;

    state.smoothX += dx * alpha;
    state.smoothY += dy * alpha;
}

static SCBDTrackedHead UpdateSCBDHeadTracker(
    int player,
    const SCBDBoneMapper::FighterState &fighter,
    const std::vector<SCBDScreenBone> &bones
) {
    SCBDTrackedHead out{};
    SCBDHeadTrackerState &state = GetSCBDHeadTracker(player);

    if (fighter.fighter != state.fighter ||
        fighter.boneArray != state.boneArray) {
        ResetSCBDHeadTracker(state, fighter.fighter, fighter.boneArray);
    }

    if (!fighter.valid || bones.empty()) {
        ++state.missingFrames;
        if (state.missingFrames >= SCBDHeadTrackerState::kResetMissingFrames) {
            ResetSCBDHeadTracker(state, fighter.fighter, fighter.boneArray);
        }
        return out;
    }

    state.missingFrames = 0;

    // V0.4's per-frame heuristic was confirmed by the recorded runtime test:
    // Nightmare -> 117, Dampierre -> 5. V0.4.2 votes across time instead
    // of trusting a single frame, then locks the dominant bone index.
    if (state.lockedIndex < 0) {
        const int proposal = PickSCBDAutoHead(bones);
        if (proposal >= 0 && proposal < SCBDHeadTrackerState::kBoneCount) {
            ++state.votes[proposal];
            ++state.sampleCount;

            int currentBestVotes = 0;
            const int currentBest =
                BestSCBDHeadVote(state, &currentBestVotes);
            state.bestVotes = currentBestVotes;

            if (state.sampleCount >= SCBDHeadTrackerState::kLearningSamples &&
                currentBest >= 0) {
                state.lockedIndex = currentBest;
            }
        }
    }

    int targetIndex = state.lockedIndex;
    if (targetIndex < 0)
        targetIndex = PickSCBDAutoHead(bones);

    const SCBDScreenBone *target =
        FindSCBDScreenBone(bones, targetIndex);

    if (!target)
        return out;

    SmoothSCBDHead(state, target->outX, target->outY);

    out.visible = state.smoothValid;
    out.locked = state.lockedIndex >= 0;
    out.index = targetIndex;
    out.sampleCount = state.sampleCount;
    out.bestVotes = state.bestVotes;
    out.x = state.smoothX;
    out.y = state.smoothY;
    return out;
}

static void DrawSCBDTrackedHead(
    UIContext *ctx,
    FontID font,
    const SCBDTrackedHead &head,
    int player,
    uint32_t color
) {
    if (!head.visible)
        return;

    char label[96];
    if (head.locked) {
        std::snprintf(
            label,
            sizeof(label),
            "P%d HEAD #%d LOCK",
            player,
            head.index
        );
    } else {
        std::snprintf(
            label,
            sizeof(label),
            "P%d HEAD #%d LEARN %d/%d",
            player,
            head.index,
            head.sampleCount,
            SCBDHeadTrackerState::kLearningSamples
        );
    }

    ctx->Draw()->DrawTextRect(
        font,
        "+",
        head.x - 8.0f,
        head.y - 9.0f,
        20.0f,
        20.0f,
        0xFFFFFFFF,
        FLAG_DYNAMIC_ASCII
    );

    ctx->Draw()->DrawTextRect(
        font,
        label,
        head.x + 8.0f,
        head.y - 12.0f,
        170.0f,
        24.0f,
        color,
        FLAG_DYNAMIC_ASCII
    );
}

'''

s = replace_between(
    s,
    "static void DrawSCBDBoneSet(",
    "static void DrawSCBDBoneMapper(",
    tracker_helpers,
    "replace bone labels with adaptive tracker helpers",
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

    const SCBDTrackedHead p1Head =
        UpdateSCBDHeadTracker(1, p1, p1Bones);
    const SCBDTrackedHead p2Head =
        UpdateSCBDHeadTracker(2, p2, p2Bones);

    FontID ubuntu24("UBUNTU24");

    ctx->Flush();
    ctx->BindFontTexture();
    ctx->Draw()->SetFontScale(0.42f, 0.42f);

    DrawSCBDTrackedHead(ctx, ubuntu24, p1Head, 1, 0xFF66FF88);
    DrawSCBDTrackedHead(ctx, ubuntu24, p2Head, 2, 0xFF8080FF);

    char summary[640];
    std::snprintf(
        summary,
        sizeof(summary),
        "HEAD V0.4.2 | CAM:%s F:%u | "
        "P1 F:%08X B:%08X N:%zu H#%d %s V:%d/%d | "
        "P2 F:%08X B:%08X N:%zu H#%d %s V:%d/%d",
        camera.valid ? "OK" : "WAIT",
        camera.flip,
        p1.fighter,
        p1.boneArray,
        p1Bones.size(),
        p1Head.index,
        p1Head.locked ? "LOCK" : "LEARN",
        p1Head.bestVotes,
        p1Head.sampleCount,
        p2.fighter,
        p2.boneArray,
        p2Bones.size(),
        p2Head.index,
        p2Head.locked ? "LOCK" : "LEARN",
        p2Head.bestVotes,
        p2Head.sampleCount
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
    "replace V0.4 mapper with V0.4.2 head tracker",
)

p.write_text(s, encoding="utf-8")

info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")
info.write_text(
    "PSP Live FloGB V0.4.2 Adaptive Head Tracker\\n"
    "Target: Soulcalibur Broken Destiny ULUS-10457\\n"
    "Package: com.scbd.vieweremulator\\n"
    "Base: V0.3 Inspector + V0.4 Bone Mapper + V0.4.1 pointer hotfix preserved\\n"
    "Camera/fighter/bone reader unchanged from PASS baseline\\n"
    "Head learning: V0.4 heuristic voted across 45 valid frames per player\\n"
    "Lock: dominant bone index held until fighter data disappears/reloads\\n"
    "Smoothing: adaptive EMA with fast catch-up on large movement\\n"
    "Diagnostic: only P1/P2 head markers remain\\n",
    encoding="utf-8",
)

print("PSP Live FloGB V0.4.2 Adaptive Head Tracker patch applied successfully.")
