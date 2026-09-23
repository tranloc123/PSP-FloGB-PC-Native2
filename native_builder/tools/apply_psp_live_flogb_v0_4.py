from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_4.py <ppsspp_repo>")

repo = Path(sys.argv[1]).resolve()

def require(rel):
    p = repo / rel
    if not p.exists():
        raise SystemExit(f"Missing expected path: {rel}")
    return p

def read(rel):
    p = require(rel)
    return p, p.read_text(encoding="utf-8")

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 occurrence, found {count}")
    return text.replace(old, new, 1)

# V0.4 is intentionally incremental. V0.3 must already be applied.
require("SCBD/SCBDViewer.h")
require("SCBD/SCBDMemoryInspector.h")

p_info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")
if "V0.3" not in p_info.read_text(encoding="utf-8"):
    raise SystemExit("V0.4 expects the V0.3 patch to be applied first")

scbd_dir = repo / "SCBD"

# ================================================================
# 1) Native fighter/bone reader + atomic camera snapshot
# ================================================================
bone_h = r'''#pragma once

#include <atomic>
#include <cmath>

#include "Common/CommonTypes.h"
#include "Core/MemMap.h"
#include "GPU/Math3D.h"

namespace SCBDBoneMapper {

// ULUS-10457 module base confirmed at runtime.
inline constexpr u32 kModuleBase = 0x08804000;

// Static EBOOT global fighter-pointer VAs:
//   P1 = *[0x00004A28]
//   P2 = *[0x00004A2C]
inline constexpr u32 kP1FighterPtrAddress = kModuleBase + 0x00004A28;
inline constexpr u32 kP2FighterPtrAddress = kModuleBase + 0x00004A2C;

// Reverse-engineered fighter transform layout.
inline constexpr u32 kBoneArrayPtrOffset = 0x000002B4;
inline constexpr u32 kBoneStride = 0x00000040;
inline constexpr u32 kBoneXOffset = 0x00000030;
inline constexpr u32 kBoneYOffset = 0x00000034;
inline constexpr u32 kBoneZOffset = 0x00000038;

inline constexpr int kScanBones = 128;
inline constexpr int kDrawTopBones = 40;

struct CameraSnapshot {
    bool valid = false;
    u32 flip = 0;
    float viewProj[16]{};
    float viewportXScale = 0.0f;
    float viewportYScale = 0.0f;
    float viewportXCenter = 0.0f;
    float viewportYCenter = 0.0f;
    float offsetX = 0.0f;
    float offsetY = 0.0f;
};

struct AtomicCameraState {
    std::atomic<u32> sequence{0};
    std::atomic<u32> lastCapturedFlip{0xFFFFFFFFu};
    std::atomic<u32> flip{0};
    std::atomic<float> viewProj[16]{};
    std::atomic<float> viewportXScale{0.0f};
    std::atomic<float> viewportYScale{0.0f};
    std::atomic<float> viewportXCenter{0.0f};
    std::atomic<float> viewportYCenter{0.0f};
    std::atomic<float> offsetX{0.0f};
    std::atomic<float> offsetY{0.0f};
};

inline AtomicCameraState &CameraState() {
    static AtomicCameraState state;
    return state;
}

// Called from the GPU primitive path. We only need one camera capture per
// displayed frame. Every field is atomic so UI/GPU thread overlap is safe.
inline void CaptureCamera(
    const float viewProj[16],
    float viewportXScale,
    float viewportYScale,
    float viewportXCenter,
    float viewportYCenter,
    float offsetX,
    float offsetY,
    u32 flip
) {
    AtomicCameraState &s = CameraState();

    u32 previous = s.lastCapturedFlip.load(std::memory_order_relaxed);
    if (previous == flip)
        return;

    if (!s.lastCapturedFlip.compare_exchange_strong(
            previous, flip, std::memory_order_relaxed, std::memory_order_relaxed)) {
        return;
    }

    s.sequence.fetch_add(1, std::memory_order_acq_rel);  // odd = writer active

    for (int i = 0; i < 16; ++i)
        s.viewProj[i].store(viewProj[i], std::memory_order_relaxed);

    s.viewportXScale.store(viewportXScale, std::memory_order_relaxed);
    s.viewportYScale.store(viewportYScale, std::memory_order_relaxed);
    s.viewportXCenter.store(viewportXCenter, std::memory_order_relaxed);
    s.viewportYCenter.store(viewportYCenter, std::memory_order_relaxed);
    s.offsetX.store(offsetX, std::memory_order_relaxed);
    s.offsetY.store(offsetY, std::memory_order_relaxed);
    s.flip.store(flip, std::memory_order_relaxed);

    s.sequence.fetch_add(1, std::memory_order_release);  // even = stable
}

inline CameraSnapshot ReadCamera() {
    CameraSnapshot out{};
    AtomicCameraState &s = CameraState();

    for (int attempt = 0; attempt < 4; ++attempt) {
        const u32 before = s.sequence.load(std::memory_order_acquire);
        if (before == 0 || (before & 1))
            continue;

        out.flip = s.flip.load(std::memory_order_relaxed);
        for (int i = 0; i < 16; ++i)
            out.viewProj[i] = s.viewProj[i].load(std::memory_order_relaxed);

        out.viewportXScale = s.viewportXScale.load(std::memory_order_relaxed);
        out.viewportYScale = s.viewportYScale.load(std::memory_order_relaxed);
        out.viewportXCenter = s.viewportXCenter.load(std::memory_order_relaxed);
        out.viewportYCenter = s.viewportYCenter.load(std::memory_order_relaxed);
        out.offsetX = s.offsetX.load(std::memory_order_relaxed);
        out.offsetY = s.offsetY.load(std::memory_order_relaxed);

        const u32 after = s.sequence.load(std::memory_order_acquire);
        if (before == after && !(after & 1)) {
            out.valid = true;
            return out;
        }
    }

    return CameraSnapshot{};
}

struct FighterState {
    bool valid = false;
    u32 fighter = 0;
    u32 boneArray = 0;
};

struct BoneWorld {
    bool valid = false;
    int index = -1;
    float x = 0.0f;
    float y = 0.0f;
    float z = 0.0f;
};

inline bool ReadU32Safe(u32 address, u32 *value) {
    if (!Memory::IsActive() || !Memory::IsValid4AlignedAddress(address))
        return false;
    *value = Memory::ReadUnchecked_U32(address);
    return true;
}

inline bool ReadFloatSafe(u32 address, float *value) {
    if (!Memory::IsActive() || !Memory::IsValid4AlignedAddress(address))
        return false;
    *value = Memory::ReadUnchecked_Float(address);
    return std::isfinite(*value);
}

inline bool ValidPSPPointer(u32 address) {
    return address != 0 && Memory::IsActive() && Memory::IsValidAddress(address);
}

inline FighterState ReadFighter(int player) {
    FighterState out{};
    const u32 globalPtr = player == 2 ? kP2FighterPtrAddress : kP1FighterPtrAddress;

    if (!ReadU32Safe(globalPtr, &out.fighter) || !ValidPSPPointer(out.fighter))
        return out;

    const u32 bonePtrAddress = out.fighter + kBoneArrayPtrOffset;
    if (!ReadU32Safe(bonePtrAddress, &out.boneArray) || !ValidPSPPointer(out.boneArray))
        return out;

    out.valid = true;
    return out;
}

inline BoneWorld ReadBone(const FighterState &fighter, int index) {
    BoneWorld out{};
    out.index = index;

    if (!fighter.valid || index < 0 || index >= kScanBones)
        return out;

    const u32 base = fighter.boneArray + static_cast<u32>(index) * kBoneStride;

    if (!ReadFloatSafe(base + kBoneXOffset, &out.x) ||
        !ReadFloatSafe(base + kBoneYOffset, &out.y) ||
        !ReadFloatSafe(base + kBoneZOffset, &out.z)) {
        return out;
    }

    constexpr float kMaxAbs = 1000000.0f;
    if (std::fabs(out.x) > kMaxAbs ||
        std::fabs(out.y) > kMaxAbs ||
        std::fabs(out.z) > kMaxAbs) {
        return out;
    }

    if (std::fabs(out.x) < 0.000001f &&
        std::fabs(out.y) < 0.000001f &&
        std::fabs(out.z) < 0.000001f) {
        return out;
    }

    out.valid = true;
    return out;
}

inline bool ProjectWorldToPSP(
    const CameraSnapshot &camera,
    const BoneWorld &bone,
    float *x,
    float *y
) {
    if (!camera.valid || !bone.valid)
        return false;

    float world[3] = {bone.x, bone.y, bone.z};
    float clip[4]{};
    Vec3ByMatrix44(clip, world, camera.viewProj);

    if (!std::isfinite(clip[0]) ||
        !std::isfinite(clip[1]) ||
        !std::isfinite(clip[2]) ||
        !std::isfinite(clip[3]) ||
        clip[3] <= 0.00001f) {
        return false;
    }

    const float sx =
        clip[0] * camera.viewportXScale / clip[3] +
        camera.viewportXCenter -
        camera.offsetX;

    const float sy =
        clip[1] * camera.viewportYScale / clip[3] +
        camera.viewportYCenter -
        camera.offsetY;

    if (!std::isfinite(sx) || !std::isfinite(sy))
        return false;

    if (sx < -32.0f || sx > 512.0f || sy < -32.0f || sy > 304.0f)
        return false;

    *x = sx;
    *y = sy;
    return true;
}

}  // namespace SCBDBoneMapper
'''
(scbd_dir / "SCBDBoneMapper.h").write_text(bone_h, encoding="utf-8")

# ================================================================
# 2) Capture the Soulcalibur 3D camera in PPSSPP's HW PRIM path
# ================================================================
p, s = read("GPU/GPUCommonHW.cpp")

include_anchor = '#include "GPU/GPUCommonHW.h"\n'
if include_anchor not in s:
    raise SystemExit("GPUCommonHW.cpp: include anchor missing")
s = replace_once(
    s,
    include_anchor,
    include_anchor + '#include "SCBD/SCBDBoneMapper.h"\n',
    "GPUCommonHW.cpp SCBD include",
)

camera_anchor = '''\tFlushImm();
\tUpdateMatrixProducts();

\t// Upper bits are ignored.
'''
if camera_anchor not in s:
    raise SystemExit("GPUCommonHW.cpp: Execute_Prim camera anchor missing")

camera_hook = '''\tFlushImm();
\tUpdateMatrixProducts();

\t// PSP Live FloGB V0.4: capture one non-through skinned 3D camera per flip.
\tif (!gstate.isModeThrough() && vertTypeIsSkinningEnabled(gstate.vertType)) {
\t\tSCBDBoneMapper::CaptureCamera(
\t\t\tgstate_c.viewproj,
\t\t\tgstate.getViewportXScale(),
\t\t\tgstate.getViewportYScale(),
\t\t\tgstate.getViewportXCenter(),
\t\t\tgstate.getViewportYCenter(),
\t\t\t(float)gstate.getOffsetX(),
\t\t\t(float)gstate.getOffsetY(),
\t\t\t(u32)gpuStats.totals.numFlips
\t\t);
\t}

\t// Upper bits are ignored.
'''
s = replace_once(
    s,
    camera_anchor,
    camera_hook,
    "GPUCommonHW.cpp camera hook",
)
p.write_text(s, encoding="utf-8")

# ================================================================
# 3) Draw projected bone indices in the existing V0.3 native HUD
# ================================================================
p, s = read("UI/DebugOverlay.cpp")

include_anchor = '#include "SCBD/SCBDMemoryInspector.h"\n'
if include_anchor not in s:
    raise SystemExit("DebugOverlay.cpp: V0.3 SCBD include anchor missing")

extra_includes = (
    '#include "SCBD/SCBDBoneMapper.h"\n'
    '#include "GPU/Common/PresentationCommon.h"\n'
    '#include "Common/System/Display.h"\n'
)
s = replace_once(
    s,
    include_anchor,
    include_anchor + extra_includes,
    "DebugOverlay.cpp V0.4 includes",
)

helper_anchor = 'bool ShouldDrawSCBDOverlay() {\n'
if helper_anchor not in s:
    raise SystemExit("DebugOverlay.cpp: ShouldDrawSCBDOverlay anchor missing")

helper_code = r'''namespace {

struct SCBDScreenBone {
    int index = -1;
    float pspX = 0.0f;
    float pspY = 0.0f;
    float outX = 0.0f;
    float outY = 0.0f;
};

static std::vector<SCBDScreenBone> CollectSCBDScreenBones(
    const SCBDBoneMapper::FighterState &fighter,
    const SCBDBoneMapper::CameraSnapshot &camera,
    const FRect &outputRect
) {
    std::vector<SCBDScreenBone> bones;
    bones.reserve(SCBDBoneMapper::kScanBones);

    for (int i = 0; i < SCBDBoneMapper::kScanBones; ++i) {
        const SCBDBoneMapper::BoneWorld world =
            SCBDBoneMapper::ReadBone(fighter, i);

        float pspX = 0.0f;
        float pspY = 0.0f;
        if (!SCBDBoneMapper::ProjectWorldToPSP(
                camera, world, &pspX, &pspY)) {
            continue;
        }

        SCBDScreenBone b{};
        b.index = i;
        b.pspX = pspX;
        b.pspY = pspY;
        b.outX = outputRect.x + (pspX / 480.0f) * outputRect.w;
        b.outY = outputRect.y + (pspY / 272.0f) * outputRect.h;
        bones.push_back(b);
    }

    return bones;
}

static int PickSCBDAutoHead(const std::vector<SCBDScreenBone> &bones) {
    if (bones.empty())
        return -1;

    std::vector<float> xs;
    xs.reserve(bones.size());
    for (const auto &b : bones)
        xs.push_back(b.pspX);

    std::sort(xs.begin(), xs.end());
    const float medianX = xs[xs.size() / 2];

    int bestIndex = -1;
    float bestY = 1000000.0f;

    for (const auto &b : bones) {
        if (std::fabs(b.pspX - medianX) > 70.0f)
            continue;
        if (b.pspY < bestY) {
            bestY = b.pspY;
            bestIndex = b.index;
        }
    }

    return bestIndex;
}

static const SCBDScreenBone *FindSCBDScreenBone(
    const std::vector<SCBDScreenBone> &bones,
    int index
) {
    for (const auto &b : bones) {
        if (b.index == index)
            return &b;
    }
    return nullptr;
}

static void DrawSCBDBoneSet(
    UIContext *ctx,
    FontID font,
    std::vector<SCBDScreenBone> bones,
    int headIndex,
    uint32_t color
) {
    if (bones.empty())
        return;

    std::sort(
        bones.begin(),
        bones.end(),
        [](const SCBDScreenBone &a, const SCBDScreenBone &b) {
            return a.pspY < b.pspY;
        }
    );

    const size_t count = std::min(
        bones.size(),
        static_cast<size_t>(SCBDBoneMapper::kDrawTopBones)
    );

    for (size_t i = 0; i < count; ++i) {
        const SCBDScreenBone &b = bones[i];
        std::string label = std::to_string(b.index);

        ctx->Draw()->DrawTextRect(
            font,
            label,
            b.outX - 13.0f,
            b.outY - 8.0f,
            40.0f,
            20.0f,
            color,
            FLAG_DYNAMIC_ASCII
        );
    }

    const SCBDScreenBone *head = FindSCBDScreenBone(bones, headIndex);
    if (head) {
        std::string label = "H#" + std::to_string(headIndex);
        ctx->Draw()->DrawTextRect(
            font,
            label,
            head->outX - 22.0f,
            head->outY - 22.0f,
            60.0f,
            24.0f,
            0xFFFFFF40,
            FLAG_DYNAMIC_ASCII
        );
    }
}

static void DrawSCBDBoneMapper(UIContext *ctx, const Bounds &bounds) {
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

    const int p1Head = PickSCBDAutoHead(p1Bones);
    const int p2Head = PickSCBDAutoHead(p2Bones);

    FontID ubuntu24("UBUNTU24");

    ctx->Flush();
    ctx->BindFontTexture();
    ctx->Draw()->SetFontScale(0.38f, 0.38f);

    DrawSCBDBoneSet(ctx, ubuntu24, p1Bones, p1Head, 0xFF66FF88);
    DrawSCBDBoneSet(ctx, ubuntu24, p2Bones, p2Head, 0xFF8080FF);

    char summary[512];
    std::snprintf(
        summary,
        sizeof(summary),
        "BONE V0.4 | CAM:%s F:%u | "
        "P1 F:%08X B:%08X N:%zu H#%d | "
        "P2 F:%08X B:%08X N:%zu H#%d",
        camera.valid ? "OK" : "WAIT",
        camera.flip,
        p1.fighter,
        p1.boneArray,
        p1Bones.size(),
        p1Head,
        p2.fighter,
        p2.boneArray,
        p2Bones.size(),
        p2Head
    );

    ctx->Draw()->SetFontScale(0.42f, 0.42f);
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

}  // namespace

'''
s = replace_once(
    s,
    helper_anchor,
    helper_code + helper_anchor,
    "DebugOverlay.cpp bone helper",
)

draw_end_anchor = '''    ctx->Draw()->SetFontScale(1.0f, 1.0f);
    ctx->Flush();
    ctx->RebindTexture();
}

void DrawFPS(UIContext *ctx, const Bounds &bounds) {
'''
if draw_end_anchor not in s:
    raise SystemExit("DebugOverlay.cpp: V0.3 DrawSCBDOverlay end anchor missing")

draw_end_new = '''    ctx->Draw()->SetFontScale(1.0f, 1.0f);
    ctx->Flush();
    ctx->RebindTexture();

    DrawSCBDBoneMapper(ctx, bounds);
}

void DrawFPS(UIContext *ctx, const Bounds &bounds) {
'''
s = replace_once(
    s,
    draw_end_anchor,
    draw_end_new,
    "DebugOverlay.cpp DrawSCBDBoneMapper hook",
)
p.write_text(s, encoding="utf-8")

# ================================================================
# 4) Build marker
# ================================================================
p_info.write_text(
    "PSP Live FloGB V0.4 Native Bone Mapper Diagnostic\n"
    "Target: Soulcalibur Broken Destiny ULUS-10457\n"
    "Package: com.scbd.vieweremulator\n"
    "Base: V0.3 Developer Memory Inspector preserved\n"
    "Fighter globals: P1@08808A28 P2@08808A2C\n"
    "Bone layout: fighter+2B4 -> array, stride 40h, XYZ +30/+34/+38\n"
    "Camera: captured from first non-through skinned HW PRIM per flip\n"
    "Overlay: projects native world bones through PPSSPP view/projection/viewport\n",
    encoding="utf-8",
)

print("PSP Live FloGB V0.4 Bone Mapper patch applied successfully.")
