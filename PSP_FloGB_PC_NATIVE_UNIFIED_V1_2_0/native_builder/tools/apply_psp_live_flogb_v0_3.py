from pathlib import Path
import sys

try:
    from PIL import Image
except Exception as e:
    raise SystemExit("Pillow is required: " + str(e))

if len(sys.argv) != 3:
    raise SystemExit(
        "Usage: apply_psp_live_flogb_v0_3.py <ppsspp_repo> <icon_source.png>"
    )

repo = Path(sys.argv[1]).resolve()
icon_source = Path(sys.argv[2]).resolve()

APP_NAME = "PSP Live FloGB"
APPLICATION_ID = "com.scbd.vieweremulator"

def require(rel):
    p = repo / rel
    if not p.exists():
        raise SystemExit(f"Missing expected PPSSPP path: {rel}")
    return p

def read(rel):
    p = require(rel)
    return p, p.read_text(encoding="utf-8")

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly 1 occurrence, found {count}")
    return text.replace(old, new, 1)

# ================================================================
# 1) Preserve V0.2 app identity / branding
# ================================================================
p, s = read("android/build.gradle.kts")
old_app_id = 'applicationId = "org.ppsspp.ppsspp"'
count = s.count(old_app_id)
if count != 2:
    raise SystemExit(
        f"android/build.gradle.kts: expected 2 normal applicationId entries, found {count}"
    )
s = s.replace(old_app_id, f'applicationId = "{APPLICATION_ID}"')
p.write_text(s, encoding="utf-8")

p, s = read("android/res/values/strings.xml")
s = replace_once(
    s,
    '<string name="app_name">PPSSPP</string>',
    f'<string name="app_name">{APP_NAME}</string>',
    "strings.xml app_name",
)
s = replace_once(
    s,
    '<string name="shortcut_name">PPSSPP game</string>',
    f'<string name="shortcut_name">{APP_NAME}</string>',
    "strings.xml shortcut_name",
)
p.write_text(s, encoding="utf-8")

p, s = read("UI/NativeApp.cpp")
s = replace_once(
    s,
    '*app_nice_name = "PPSSPP";',
    f'*app_nice_name = "{APP_NAME}";',
    "NativeApp.cpp nice name",
)
p.write_text(s, encoding="utf-8")

if not icon_source.exists():
    raise SystemExit(f"Icon source not found: {icon_source}")

im = Image.open(icon_source).convert("RGB")
iw, ih = im.size
side = min(iw, ih)
x0 = (iw - side) // 2
y0 = (ih - side) // 2
im = im.crop((x0, y0, x0 + side, y0 + side))

launcher_sizes = {
    "mipmap-mdpi": 48,
    "mipmap-hdpi": 72,
    "mipmap-xhdpi": 96,
    "mipmap-xxhdpi": 144,
    "mipmap-xxxhdpi": 192,
}
foreground_sizes = {
    "mipmap-mdpi": 108,
    "mipmap-hdpi": 162,
    "mipmap-xhdpi": 216,
    "mipmap-xxhdpi": 324,
    "mipmap-xxxhdpi": 432,
}

for folder, px in launcher_sizes.items():
    d = require(f"android/normal/res/{folder}")
    resized = im.resize((px, px), Image.Resampling.LANCZOS)
    resized.save(d / "ic_launcher.png", "PNG", optimize=True)
    resized.save(d / "ic_launcher_round.png", "PNG", optimize=True)

for folder, px in foreground_sizes.items():
    d = require(f"android/normal/res/{folder}")
    resized = im.resize((px, px), Image.Resampling.LANCZOS)
    resized.save(d / "ic_launcher_foreground.png", "PNG", optimize=True)

p, s = read("android/normal/res/values/ic_launcher_background.xml")
s = replace_once(
    s,
    "#2D4553",
    "#26070D",
    "launcher background",
)
p.write_text(s, encoding="utf-8")

# ================================================================
# 2) SCBD native known-address reader
# ================================================================
scbd_dir = repo / "SCBD"
scbd_dir.mkdir(exist_ok=True)

viewer_h = r'''#pragma once

#include "Core/MemMap.h"

namespace SCBDViewer {

inline constexpr const char *kTargetGameId = "ULUS10457";

inline constexpr u32 kMode     = 0x08BCFE44;
inline constexpr u32 kGate     = 0x08BD034C;
inline constexpr u32 kState    = 0x08BCFCC8;
inline constexpr u32 kCombat   = 0x08BCFC90;
inline constexpr u32 kState3   = 0x08BCFC68;
inline constexpr u32 kVictory5 = 0x08BCFC50;
inline constexpr u32 kP1HP     = 0x08BE364C;
inline constexpr u32 kP2HP     = 0x08BFA30C;
inline constexpr u32 kFighterStride = 0x00016CC0;

struct Snapshot {
    bool readable = false;
    float p1HP = 0.0f;
    float p2HP = 0.0f;
    u32 mode = 0;
    u32 gate = 0;
    u32 state = 0;
    u32 combat = 0;
    u32 state3 = 0;
    u32 victory5 = 0;
};

inline bool CanRead32(u32 address) {
    return Memory::IsActive() && Memory::IsValid4AlignedAddress(address);
}

inline u32 ReadU32(u32 address) {
    return CanRead32(address) ? Memory::ReadUnchecked_U32(address) : 0;
}

inline float ReadFloat(u32 address) {
    return CanRead32(address) ? Memory::ReadUnchecked_Float(address) : 0.0f;
}

inline bool CoreAddressesReadable() {
    return CanRead32(kP1HP) &&
           CanRead32(kP2HP) &&
           CanRead32(kMode) &&
           CanRead32(kGate) &&
           CanRead32(kState) &&
           CanRead32(kCombat) &&
           CanRead32(kState3) &&
           CanRead32(kVictory5);
}

inline Snapshot ReadSnapshot() {
    Snapshot s{};
    s.readable = CoreAddressesReadable();
    if (!s.readable)
        return s;

    s.p1HP = ReadFloat(kP1HP);
    s.p2HP = ReadFloat(kP2HP);
    s.mode = ReadU32(kMode);
    s.gate = ReadU32(kGate);
    s.state = ReadU32(kState);
    s.combat = ReadU32(kCombat);
    s.state3 = ReadU32(kState3);
    s.victory5 = ReadU32(kVictory5);
    return s;
}

}  // namespace SCBDViewer
'''
(scbd_dir / "SCBDViewer.h").write_text(viewer_h, encoding="utf-8")

# ================================================================
# 3) Reusable Developer Memory Inspector
# ================================================================
inspector_h = r'''#pragma once

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

#include "Core/MemMap.h"
#include "SCBD/SCBDViewer.h"

namespace SCBDInspector {

enum class Action : int {
    None = 0,
    Base,
    Changed,
    Same,
    Increased,
    Decreased,
    P1Only,
    P2Only,
    Reset,
    SelectPrev,
    SelectNext,
    PagePrev,
    PageNext,
    PinToggle,
    ClearPins,
    ApplyRange,
};

struct Candidate {
    u32 address = 0;
    float previousP1 = 0.0f;
    float previousP2 = 0.0f;
};

struct State {
    u32 rangeStart = 0x08BD0000;
    u32 rangeSize = 0x00016CC0;
    u32 stride = SCBDViewer::kFighterStride;

    std::vector<Candidate> candidates;
    std::vector<u32> pins;

    size_t selected = 0;
    bool active = false;
    std::string status = "Press BASE to capture a float baseline";
};

inline State &GetState() {
    static State state;
    return state;
}

inline std::atomic<int> &PendingAction() {
    static std::atomic<int> action{static_cast<int>(Action::None)};
    return action;
}

inline std::atomic<u32> &PendingRangeStart() {
    static std::atomic<u32> value{0x08BD0000};
    return value;
}

inline std::atomic<u32> &PendingRangeSize() {
    static std::atomic<u32> value{0x00016CC0};
    return value;
}

inline std::atomic<bool> &PanelVisibleAtomic() {
    static std::atomic<bool> visible{false};
    return visible;
}

inline bool PanelVisible() {
    return PanelVisibleAtomic().load(std::memory_order_relaxed);
}

inline void TogglePanel() {
    bool before = PanelVisibleAtomic().load(std::memory_order_relaxed);
    PanelVisibleAtomic().store(!before, std::memory_order_relaxed);
}

inline void SetPanelVisible(bool visible) {
    PanelVisibleAtomic().store(visible, std::memory_order_relaxed);
}

inline void Queue(Action action) {
    PendingAction().store(static_cast<int>(action), std::memory_order_release);
}

inline void QueueRange(u32 start, u32 size) {
    PendingRangeStart().store(start, std::memory_order_relaxed);
    PendingRangeSize().store(size, std::memory_order_relaxed);
    PendingAction().store(static_cast<int>(Action::ApplyRange), std::memory_order_release);
}

inline bool ReadFloatAt(u32 address, float *value) {
    if (!Memory::IsActive() || !Memory::IsValid4AlignedAddress(address))
        return false;
    *value = Memory::ReadUnchecked_Float(address);
    return std::isfinite(*value);
}

inline bool SaneFloat(float value) {
    if (!std::isfinite(value))
        return false;
    return std::fabs(value) <= 100000000.0f;
}

inline bool Different(float a, float b) {
    if (!std::isfinite(a) || !std::isfinite(b))
        return true;
    const float scale = std::max(1.0f, std::max(std::fabs(a), std::fabs(b)));
    return std::fabs(a - b) > (0.000001f * scale);
}

inline bool ReadPair(u32 p1Address, float *p1, float *p2) {
    const State &s = GetState();
    const u32 p2Address = p1Address + s.stride;
    return ReadFloatAt(p1Address, p1) &&
           ReadFloatAt(p2Address, p2) &&
           SaneFloat(*p1) &&
           SaneFloat(*p2);
}

inline const char *ActionName(Action action) {
    switch (action) {
    case Action::Base: return "BASE";
    case Action::Changed: return "CHANGED";
    case Action::Same: return "SAME";
    case Action::Increased: return "INCREASED";
    case Action::Decreased: return "DECREASED";
    case Action::P1Only: return "P1ONLY";
    case Action::P2Only: return "P2ONLY";
    case Action::Reset: return "RESET";
    case Action::SelectPrev: return "PREV";
    case Action::SelectNext: return "NEXT";
    case Action::PagePrev: return "PAGE-";
    case Action::PageNext: return "PAGE+";
    case Action::PinToggle: return "PIN";
    case Action::ClearPins: return "CLEAR PINS";
    case Action::ApplyRange: return "RANGE";
    default: return "NONE";
    }
}

inline void SetCountStatus(const char *label, size_t count) {
    char buf[160];
    std::snprintf(buf, sizeof(buf), "%s -> %zu candidates", label, count);
    GetState().status = buf;
}

inline void ResetScan() {
    State &s = GetState();
    s.candidates.clear();
    s.pins.clear();
    s.selected = 0;
    s.active = false;
    s.status = "RESET -> press BASE";
}

inline void ApplyPendingRange() {
    State &s = GetState();

    u32 start = PendingRangeStart().load(std::memory_order_relaxed) & ~3u;
    u32 size = PendingRangeSize().load(std::memory_order_relaxed) & ~3u;

    constexpr u32 kMinRange = 4;
    constexpr u32 kMaxRange = 0x00400000;

    if (size < kMinRange)
        size = kMinRange;
    if (size > kMaxRange)
        size = kMaxRange;

    s.rangeStart = start;
    s.rangeSize = size;
    s.candidates.clear();
    s.pins.clear();
    s.selected = 0;
    s.active = false;

    char buf[192];
    std::snprintf(
        buf,
        sizeof(buf),
        "RANGE %08X + %08X -> press BASE",
        s.rangeStart,
        s.rangeSize
    );
    s.status = buf;
}

inline void CaptureBaseline() {
    State &s = GetState();
    s.candidates.clear();
    s.selected = 0;

    const u64 end64 = static_cast<u64>(s.rangeStart) + static_cast<u64>(s.rangeSize);
    const u32 end = end64 > 0xFFFFFFFFULL ? 0xFFFFFFFFu : static_cast<u32>(end64);

    s.candidates.reserve(static_cast<size_t>(s.rangeSize / 4));

    for (u32 address = s.rangeStart; address <= end - 4; address += 4) {
        float p1 = 0.0f;
        float p2 = 0.0f;
        if (!ReadPair(address, &p1, &p2))
            continue;

        Candidate c{};
        c.address = address;
        c.previousP1 = p1;
        c.previousP2 = p2;
        s.candidates.push_back(c);

        if (address > 0xFFFFFFF8u)
            break;
    }

    s.active = true;
    SetCountStatus("BASE", s.candidates.size());
}

inline void Filter(Action action) {
    State &s = GetState();
    if (!s.active) {
        s.status = "No baseline. Press BASE first.";
        return;
    }

    std::vector<Candidate> kept;
    kept.reserve(s.candidates.size());

    for (const Candidate &old : s.candidates) {
        float p1 = 0.0f;
        float p2 = 0.0f;
        if (!ReadPair(old.address, &p1, &p2))
            continue;

        const bool p1Changed = Different(p1, old.previousP1);
        const bool p2Changed = Different(p2, old.previousP2);

        bool keep = false;
        switch (action) {
        case Action::Changed:
            keep = p1Changed;
            break;
        case Action::Same:
            keep = !p1Changed;
            break;
        case Action::Increased:
            keep = p1Changed && p1 > old.previousP1;
            break;
        case Action::Decreased:
            keep = p1Changed && p1 < old.previousP1;
            break;
        case Action::P1Only:
            keep = p1Changed && !p2Changed;
            break;
        case Action::P2Only:
            keep = p2Changed && !p1Changed;
            break;
        default:
            break;
        }

        if (keep) {
            Candidate next = old;
            next.previousP1 = p1;
            next.previousP2 = p2;
            kept.push_back(next);
        }
    }

    s.candidates.swap(kept);
    if (s.candidates.empty()) {
        s.selected = 0;
    } else if (s.selected >= s.candidates.size()) {
        s.selected = s.candidates.size() - 1;
    }

    SetCountStatus(ActionName(action), s.candidates.size());
}

inline void MoveSelection(int delta) {
    State &s = GetState();
    if (s.candidates.empty()) {
        s.selected = 0;
        return;
    }

    long long next = static_cast<long long>(s.selected) + delta;
    if (next < 0)
        next = 0;
    if (next >= static_cast<long long>(s.candidates.size()))
        next = static_cast<long long>(s.candidates.size() - 1);
    s.selected = static_cast<size_t>(next);
}

inline void ToggleSelectedPin() {
    State &s = GetState();
    if (s.candidates.empty() || s.selected >= s.candidates.size()) {
        s.status = "PIN -> no selected candidate";
        return;
    }

    const u32 address = s.candidates[s.selected].address;
    auto it = std::find(s.pins.begin(), s.pins.end(), address);
    if (it != s.pins.end()) {
        s.pins.erase(it);
        s.status = "PIN removed";
        return;
    }

    if (s.pins.size() >= 8) {
        s.status = "PIN limit reached (8)";
        return;
    }

    s.pins.push_back(address);
    s.status = "PIN added";
}

inline void ProcessPending() {
    const Action action = static_cast<Action>(
        PendingAction().exchange(static_cast<int>(Action::None), std::memory_order_acq_rel)
    );

    switch (action) {
    case Action::None:
        break;
    case Action::ApplyRange:
        ApplyPendingRange();
        break;
    case Action::Base:
        CaptureBaseline();
        break;
    case Action::Changed:
    case Action::Same:
    case Action::Increased:
    case Action::Decreased:
    case Action::P1Only:
    case Action::P2Only:
        Filter(action);
        break;
    case Action::Reset:
        ResetScan();
        break;
    case Action::SelectPrev:
        MoveSelection(-1);
        break;
    case Action::SelectNext:
        MoveSelection(1);
        break;
    case Action::PagePrev:
        MoveSelection(-8);
        break;
    case Action::PageNext:
        MoveSelection(8);
        break;
    case Action::PinToggle:
        ToggleSelectedPin();
        break;
    case Action::ClearPins:
        GetState().pins.clear();
        GetState().status = "Pins cleared";
        break;
    }
}

inline bool GetLivePair(u32 address, float *p1, float *p2) {
    return ReadPair(address, p1, p2);
}

}  // namespace SCBDInspector
'''
(scbd_dir / "SCBDMemoryInspector.h").write_text(inspector_h, encoding="utf-8")

# ================================================================
# 4) Debug overlay: V0.3 HUD + scanner processing
# ================================================================
p, s = read("UI/DebugOverlay.h")
anchor = 'void DrawFPS(UIContext *ctx, const Bounds &bounds);\n'
if anchor not in s:
    raise SystemExit("DebugOverlay.h: DrawFPS anchor missing")
s = s.replace(
    anchor,
    anchor +
    'bool ShouldDrawSCBDOverlay();\n'
    'void DrawSCBDOverlay(UIContext *ctx, const Bounds &bounds);\n',
    1,
)
p.write_text(s, encoding="utf-8")

p, s = read("UI/DebugOverlay.cpp")
include_anchor = '#include "Core/ELF/ParamSFO.h"\n'
if include_anchor not in s:
    raise SystemExit("DebugOverlay.cpp: ParamSFO include anchor missing")
s = s.replace(
    include_anchor,
    include_anchor +
    '#include "SCBD/SCBDViewer.h"\n'
    '#include "SCBD/SCBDMemoryInspector.h"\n',
    1,
)

drawfps_anchor = 'void DrawFPS(UIContext *ctx, const Bounds &bounds) {\n'
if drawfps_anchor not in s:
    raise SystemExit("DebugOverlay.cpp: DrawFPS anchor missing")

overlay_code = r'''bool ShouldDrawSCBDOverlay() {
    if (!PSP_IsInited())
        return false;
    if (g_paramSFO.GetDiscID() != SCBDViewer::kTargetGameId)
        return false;
    return SCBDViewer::CoreAddressesReadable();
}

void DrawSCBDOverlay(UIContext *ctx, const Bounds &bounds) {
    if (!ShouldDrawSCBDOverlay())
        return;

    // IMPORTANT: This function is reached through EmuScreen::renderUI(), which
    // is rendered under NativeFrame's g_frameMutex. Scanner memory work therefore
    // stays in the emulator's synchronized render span rather than touch callbacks.
    SCBDInspector::ProcessPending();

    const SCBDViewer::Snapshot snap = SCBDViewer::ReadSnapshot();
    if (!snap.readable)
        return;

    SCBDInspector::State &mem = SCBDInspector::GetState();

    char text[8192];
    StringWriter w(text, sizeof(text));

    w.F(
        "PSP Live FloGB | SCBD V0.3 DEV\n"
        "ULUS10457 | RAM OK | HP %.2f / %.2f | MODE %08X\n"
        "STATE %08X  COMBAT %08X  STATE3 %08X  VICTORY %08X\n"
        "MEM %08X + %08X | STRIDE %08X | CAND %zu | PINS %zu\n"
        "%s\n",
        snap.p1HP,
        snap.p2HP,
        snap.mode,
        snap.state,
        snap.combat,
        snap.state3,
        snap.victory5,
        mem.rangeStart,
        mem.rangeSize,
        mem.stride,
        mem.candidates.size(),
        mem.pins.size(),
        mem.status.c_str()
    );

    if (mem.active && !mem.candidates.empty()) {
        const size_t pageSize = 8;
        const size_t pageStart = (mem.selected / pageSize) * pageSize;
        const size_t pageEnd = std::min(pageStart + pageSize, mem.candidates.size());

        w.F("---- CANDIDATES %zu-%zu / %zu ----\n",
            pageStart + 1,
            pageEnd,
            mem.candidates.size());

        for (size_t i = pageStart; i < pageEnd; ++i) {
            const SCBDInspector::Candidate &c = mem.candidates[i];
            float p1 = 0.0f;
            float p2 = 0.0f;
            const bool ok = SCBDInspector::GetLivePair(c.address, &p1, &p2);

            const bool pinned =
                std::find(mem.pins.begin(), mem.pins.end(), c.address) != mem.pins.end();

            w.F(
                "%c%c %08X  P1:% .5f  P2:% .5f%s\n",
                i == mem.selected ? '>' : ' ',
                pinned ? '*' : ' ',
                c.address,
                ok ? p1 : 0.0f,
                ok ? p2 : 0.0f,
                ok ? "" : " [INVALID]"
            );
        }
    }

    if (!mem.pins.empty()) {
        w.F("---- LIVE PINS ----\n");
        for (size_t i = 0; i < mem.pins.size(); ++i) {
            float p1 = 0.0f;
            float p2 = 0.0f;
            const bool ok = SCBDInspector::GetLivePair(mem.pins[i], &p1, &p2);
            w.F(
                "#%zu %08X  P1:% .6f  P2:% .6f%s\n",
                i + 1,
                mem.pins[i],
                ok ? p1 : 0.0f,
                ok ? p2 : 0.0f,
                ok ? "" : " [INVALID]"
            );
        }
    }

    FontID ubuntu24("UBUNTU24");

    ctx->Flush();
    ctx->BindFontTexture();
    ctx->Draw()->SetFontScale(0.43f, 0.43f);

    const float x = bounds.x + 12.0f;
    const float y = bounds.y + 48.0f;
    const float width = std::min(bounds.w * 0.54f, 680.0f);
    const float height = bounds.h - 55.0f;

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

    ctx->Draw()->SetFontScale(1.0f, 1.0f);
    ctx->Flush();
    ctx->RebindTexture();
}

'''
s = s.replace(drawfps_anchor, overlay_code + drawfps_anchor, 1)
p.write_text(s, encoding="utf-8")

# ================================================================
# 5) EmuScreen: touch-friendly inspector controls
# ================================================================
p, s = read("UI/EmuScreen.cpp")

# Includes.
include_anchor = '#include <functional>\n'
if include_anchor not in s:
    raise SystemExit("EmuScreen.cpp: <functional> include anchor missing")
s = s.replace(
    include_anchor,
    '#include <functional>\n#include <cerrno>\n#include <cstdlib>\n',
    1,
)

ui_include_anchor = '#include "Common/UI/ScreenManager.h"\n'
if ui_include_anchor not in s:
    raise SystemExit("EmuScreen.cpp: ScreenManager include anchor missing")
s = s.replace(
    ui_include_anchor,
    ui_include_anchor + '#include "Common/UI/PopupScreens.h"\n',
    1,
)

debug_include_anchor = '#include "UI/DebugOverlay.h"\n'
if debug_include_anchor not in s:
    raise SystemExit("EmuScreen.cpp: DebugOverlay include anchor missing")
s = s.replace(
    debug_include_anchor,
    debug_include_anchor +
    '#include "SCBD/SCBDViewer.h"\n'
    '#include "SCBD/SCBDMemoryInspector.h"\n',
    1,
)

# File-static UI pointers and range edit text.
global_anchor = 'extern bool g_TakeScreenshot;\n'
if global_anchor not in s:
    raise SystemExit("EmuScreen.cpp: global anchor missing")

globals_code = r'''
static UI::Button *g_scbdInspectorButton = nullptr;
static UI::LinearLayout *g_scbdInspectorPanel = nullptr;
static std::string g_scbdRangeStartText = "08BD0000";
static std::string g_scbdRangeSizeText = "00016CC0";

static bool ParseSCBDHex32(const std::string &text, u32 *value) {
    if (text.empty())
        return false;

    errno = 0;
    char *end = nullptr;
    unsigned long parsed = std::strtoul(text.c_str(), &end, 16);

    if (errno != 0 || end == text.c_str() || *end != '\0')
        return false;

    if (parsed > 0xFFFFFFFFUL)
        return false;

    *value = static_cast<u32>(parsed);
    return true;
}

static bool QueueSCBDRangeFromText() {
    u32 start = 0;
    u32 size = 0;
    if (!ParseSCBDHex32(g_scbdRangeStartText, &start) ||
        !ParseSCBDHex32(g_scbdRangeSizeText, &size)) {
        return false;
    }

    SCBDInspector::QueueRange(start, size);
    return true;
}

'''
s = s.replace(global_anchor, global_anchor + globals_code, 1)

# Add controls immediately after root pad creation.
root_anchor = '\troot_ = CreatePadLayout(touch, bounds.w, bounds.h, &pauseTrigger_, &g_controlMapper);\n'
if root_anchor not in s:
    raise SystemExit("EmuScreen.cpp: CreatePadLayout anchor missing")

controls_code = r'''
    g_scbdInspectorButton = nullptr;
    g_scbdInspectorPanel = nullptr;

    if (g_paramSFO.GetDiscID() == SCBDViewer::kTargetGameId) {
        g_scbdInspectorButton = root_->Add(
            new Button(
                "MEM",
                new AnchorLayoutParams(92, 50, NONE, 10, 12, NONE)
            )
        );
        g_scbdInspectorButton->SetScale(0.72f);
        g_scbdInspectorButton->OnClick.Add([](UI::EventParams &) {
            SCBDInspector::TogglePanel();
        });

        g_scbdInspectorPanel = root_->Add(
            new LinearLayout(
                Orientation::ORIENT_VERTICAL,
                new AnchorLayoutParams(570, 228, NONE, 70, 12, NONE)
            )
        );
        g_scbdInspectorPanel->SetBG(Drawable(0xD0181818));
        g_scbdInspectorPanel->padding = Padding(6);
        g_scbdInspectorPanel->SetSpacing(3.0f);

        auto addRow = [&]() -> LinearLayout * {
            LinearLayout *row = g_scbdInspectorPanel->Add(
                new LinearLayout(
                    Orientation::ORIENT_HORIZONTAL,
                    new LinearLayoutParams(FILL_PARENT, 50)
                )
            );
            row->SetSpacing(3.0f);
            return row;
        };

        auto addAction = [](LinearLayout *row, const char *label, SCBDInspector::Action action) {
            Button *button = row->Add(
                new Button(label, new LinearLayoutParams(1.0f))
            );
            button->SetScale(0.62f);
            button->OnClick.Add([action](UI::EventParams &) {
                SCBDInspector::Queue(action);
            });
            return button;
        };

        LinearLayout *row1 = addRow();
        addAction(row1, "BASE", SCBDInspector::Action::Base);
        addAction(row1, "CHG", SCBDInspector::Action::Changed);
        addAction(row1, "SAME", SCBDInspector::Action::Same);
        addAction(row1, "INC", SCBDInspector::Action::Increased);
        addAction(row1, "DEC", SCBDInspector::Action::Decreased);

        LinearLayout *row2 = addRow();
        addAction(row2, "P1ONLY", SCBDInspector::Action::P1Only);
        addAction(row2, "P2ONLY", SCBDInspector::Action::P2Only);
        addAction(row2, "RESET", SCBDInspector::Action::Reset);

        LinearLayout *row3 = addRow();

        Button *addrButton = row3->Add(
            new Button("ADDR", new LinearLayoutParams(1.0f))
        );
        addrButton->SetScale(0.62f);
        addrButton->OnClick.Add([this](UI::EventParams &) {
            UI::TextEditPopupScreen *popup = new UI::TextEditPopupScreen(
                &g_scbdRangeStartText,
                "08BD0000",
                "Range start HEX",
                10
            );
            if (System_GetPropertyBool(SYSPROP_KEYBOARD_IS_SOFT))
                popup->SetAlignTop(true);
            popup->OnChange.Add([](UI::EventParams &) {
                if (!QueueSCBDRangeFromText()) {
                    g_OSD.Show(
                        OSDType::MESSAGE_WARNING,
                        "Invalid HEX range",
                        2.0f,
                        "scbd_bad_range"
                    );
                }
            });
            screenManager()->push(popup);
        });

        Button *sizeButton = row3->Add(
            new Button("SIZE", new LinearLayoutParams(1.0f))
        );
        sizeButton->SetScale(0.62f);
        sizeButton->OnClick.Add([this](UI::EventParams &) {
            UI::TextEditPopupScreen *popup = new UI::TextEditPopupScreen(
                &g_scbdRangeSizeText,
                "00016CC0",
                "Range size HEX",
                10
            );
            if (System_GetPropertyBool(SYSPROP_KEYBOARD_IS_SOFT))
                popup->SetAlignTop(true);
            popup->OnChange.Add([](UI::EventParams &) {
                if (!QueueSCBDRangeFromText()) {
                    g_OSD.Show(
                        OSDType::MESSAGE_WARNING,
                        "Invalid HEX range",
                        2.0f,
                        "scbd_bad_range"
                    );
                }
            });
            screenManager()->push(popup);
        });

        addAction(row3, "<", SCBDInspector::Action::SelectPrev);
        addAction(row3, ">", SCBDInspector::Action::SelectNext);
        addAction(row3, "PG-", SCBDInspector::Action::PagePrev);
        addAction(row3, "PG+", SCBDInspector::Action::PageNext);

        LinearLayout *row4 = addRow();
        addAction(row4, "PIN +/-", SCBDInspector::Action::PinToggle);
        addAction(row4, "CLEAR PINS", SCBDInspector::Action::ClearPins);

        g_scbdInspectorPanel->SetVisibility(
            SCBDInspector::PanelVisible() ? V_VISIBLE : V_GONE
        );
    }
'''
s = s.replace(root_anchor, root_anchor + controls_code, 1)

# Keep button/panel visibility synchronized.
update_anchor = '''\t// This is where views are recreated.
\tUIScreen::update();
'''
if update_anchor not in s:
    raise SystemExit("EmuScreen.cpp: update anchor missing")

update_code = r'''
    const bool scbdTarget =
        g_paramSFO.GetDiscID() == SCBDViewer::kTargetGameId;

    if (g_scbdInspectorButton) {
        g_scbdInspectorButton->SetVisibility(
            scbdTarget ? UI::V_VISIBLE : UI::V_GONE
        );
    }

    if (g_scbdInspectorPanel) {
        g_scbdInspectorPanel->SetVisibility(
            scbdTarget && SCBDInspector::PanelVisible()
                ? UI::V_VISIBLE
                : UI::V_GONE
        );
    }
'''
s = s.replace(update_anchor, update_anchor + update_code, 1)

# Force UI render for SCBD so the native HUD is present even if normal touch controls are hidden.
visible_anchor = '''bool EmuScreen::hasVisibleUI() {
\t// Regular but uncommon UI.
'''
if visible_anchor not in s:
    raise SystemExit("EmuScreen.cpp: hasVisibleUI anchor missing")
s = s.replace(
    visible_anchor,
    '''bool EmuScreen::hasVisibleUI() {
\tif (ShouldDrawSCBDOverlay())
\t\treturn true;

\t// Regular but uncommon UI.
''',
    1,
)

# Draw native HUD after regular status flags.
render_anchor = '''\t\tif (g_Config.iShowStatusFlags) {
\t\t\tDrawFPS(ctx, GetLayoutBounds(*ctx));
\t\t}
'''
if render_anchor not in s:
    raise SystemExit("EmuScreen.cpp: renderUI FPS anchor missing")
s = s.replace(
    render_anchor,
    render_anchor +
    '''\t\tif (ShouldDrawSCBDOverlay()) {
\t\t\tDrawSCBDOverlay(ctx, GetLayoutBounds(*ctx));
\t\t}
''',
    1,
)

p.write_text(s, encoding="utf-8")

# ================================================================
# 6) Build marker
# ================================================================
(repo / "PSP_LIVE_FLOGB_BUILD_INFO.txt").write_text(
    "PSP Live FloGB V0.3 Developer Memory Inspector\n"
    "Target: Soulcalibur Broken Destiny ULUS-10457\n"
    "Package: com.scbd.vieweremulator\n"
    "Features: float baseline scanner, CHG/SAME/INC/DEC, P1ONLY/P2ONLY, "
    "editable range, stride compare, candidate paging, up to 8 live pins\n",
    encoding="utf-8",
)

print("PSP Live FloGB V0.3 patch applied successfully.")
