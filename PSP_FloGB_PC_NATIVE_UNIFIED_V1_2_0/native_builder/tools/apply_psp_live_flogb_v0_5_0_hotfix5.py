from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('Usage: apply_psp_live_flogb_v0_5_0_hotfix5.py <ppsspp_repo>')

repo = Path(sys.argv[1]).resolve()

def require(rel):
    p = repo / rel
    if not p.exists():
        raise SystemExit(f'Missing expected path: {rel}')
    return p

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 occurrence, found {count}')
    return text.replace(old, new, 1)

emu = require('UI/EmuScreen.cpp')
debug = require('UI/DebugOverlay.cpp')
info = require('PSP_LIVE_FLOGB_BUILD_INFO.txt')
emu_text = emu.read_text(encoding='utf-8')
debug_text = debug.read_text(encoding='utf-8')

for marker in ('g_scbdMatchHUDButton','g_scbdRankMenuButton','g_scbdDevButton','g_scbdNativeTestButton','SCBDNativeHUDConfig.h'):
    if marker not in emu_text:
        raise SystemExit(f'Hotfix5 prerequisite missing in EmuScreen.cpp: {marker}')
for marker in ('DrawSCBDMatchTop10HUD','DrawSCBDTestAvatar','NATIVE HUD V0.5.0','const auto &cfg = SCBDNativeHUD::Cfg();'):
    if marker not in debug_text:
        raise SystemExit(f'Hotfix5 prerequisite missing in DebugOverlay.cpp: {marker}')

scbd_dir = repo / 'SCBD'
scbd_dir.mkdir(exist_ok=True)
state_h = r'''#pragma once
#include <algorithm>
#include <atomic>

namespace SCBDInGameLayerState {

enum class Panel : int { NONE = 0, MENU = 1, RANK = 2, DEV = 3, AVATAR_TEST = 4 };

struct Rect {
    float x = 0.0f, y = 0.0f, w = 0.0f, h = 0.0f;
    bool Contains(float px, float py) const { return px >= x && py >= y && px <= x + w && py <= y + h; }
};

inline std::atomic<int> &PanelAtomic() { static std::atomic<int> v{0}; return v; }
inline Panel CurrentPanel() {
    int v = PanelAtomic().load(std::memory_order_relaxed);
    if (v < 0 || v > 4) v = 0;
    return static_cast<Panel>(v);
}
inline bool Open() { return CurrentPanel() != Panel::NONE; }
inline void SetPanel(Panel p) { PanelAtomic().store(static_cast<int>(p), std::memory_order_relaxed); }
inline void ToggleMenu() { SetPanel(Open() ? Panel::NONE : Panel::MENU); }

inline std::atomic<bool> &SwallowAtomic() { static std::atomic<bool> v{false}; return v; }
inline bool SwallowUntilUp() { return SwallowAtomic().load(std::memory_order_relaxed); }
inline void SetSwallowUntilUp(bool v) { SwallowAtomic().store(v, std::memory_order_relaxed); }
inline void CloseAndSwallow() { SetPanel(Panel::NONE); SetSwallowUntilUp(true); }

inline std::atomic<int> &RankTabAtomic() { static std::atomic<int> v{0}; return v; }
inline float &RankScrollRef() { static float v = 0.0f; return v; }
inline int RankTab() { return std::clamp(RankTabAtomic().load(std::memory_order_relaxed), 0, 3); }
inline void SetRankTab(int v) { RankTabAtomic().store(std::clamp(v, 0, 3), std::memory_order_relaxed); RankScrollRef() = 0.0f; }
inline float RankScroll() { return RankScrollRef(); }
inline bool &RankDraggingRef() { static bool v = false; return v; }
inline float &RankLastYRef() { static float v = 0.0f; return v; }
inline void BeginRankDrag(float y) { RankDraggingRef() = true; RankLastYRef() = y; }
inline void EndRankDrag() { RankDraggingRef() = false; }
inline bool RankDragging() { return RankDraggingRef(); }
inline void DragRankTo(float y, float maxScroll) {
    if (!RankDraggingRef()) return;
    const float d = RankLastYRef() - y;
    RankLastYRef() = y;
    RankScrollRef() = std::clamp(RankScrollRef() + d, 0.0f, std::max(0.0f, maxScroll));
}

inline std::atomic<bool> &AvatarTestAtomic() { static std::atomic<bool> v{false}; return v; }
inline bool AvatarTestEnabled() { return AvatarTestAtomic().load(std::memory_order_relaxed); }
inline void SetAvatarTestEnabled(bool v) { AvatarTestAtomic().store(v, std::memory_order_relaxed); }
inline bool ToggleAvatarTest() { bool v = !AvatarTestEnabled(); SetAvatarTestEnabled(v); return v; }
inline std::atomic<int> &AvatarRadiusAtomic() { static std::atomic<int> v{28}; return v; }
inline int AvatarRadius() { return std::clamp(AvatarRadiusAtomic().load(std::memory_order_relaxed), 18, 52); }
inline void AdjustAvatarRadius(int d) { AvatarRadiusAtomic().store(std::clamp(AvatarRadius() + d, 18, 52), std::memory_order_relaxed); }
inline std::atomic<int> &AvatarYOffsetAtomic() { static std::atomic<int> v{-10}; return v; }
inline int AvatarYOffset() { return std::clamp(AvatarYOffsetAtomic().load(std::memory_order_relaxed), -70, 30); }
inline void AdjustAvatarYOffset(int d) { AvatarYOffsetAtomic().store(std::clamp(AvatarYOffset() + d, -70, 30), std::memory_order_relaxed); }
inline void ResetAvatarPreview() { AvatarRadiusAtomic().store(28); AvatarYOffsetAtomic().store(-10); AvatarTestAtomic().store(true); }

inline Rect MainPanel(float sw, float sh) {
    const float w = std::min(sw * 0.76f, 820.0f), h = std::min(sh * 0.80f, 500.0f);
    return {(sw - w) * 0.5f, (sh - h) * 0.5f, w, h};
}
inline Rect HeaderBackRect(float sw, float sh) { Rect p = MainPanel(sw, sh); return {p.x + 12, p.y + 10, 92, 44}; }
inline Rect HeaderCloseRect(float sw, float sh) { Rect p = MainPanel(sw, sh); return {p.x + p.w - 58, p.y + 10, 46, 44}; }
inline Rect MenuButtonRect(int i, float sw, float sh) {
    Rect p = MainPanel(sw, sh); const float gap = 14, bw = (p.w - gap * 3) * 0.5f, bh = 70;
    int col = i % 2, row = i / 2; return {p.x + gap + col * (bw + gap), p.y + 82 + row * (bh + gap), bw, bh};
}
inline Rect RankTabRect(int i, float sw, float sh) {
    Rect p = MainPanel(sw, sh); const float left = p.x + 18, total = p.w - 36, gap = 8, w = (total - gap * 3) * 0.25f;
    return {left + i * (w + gap), p.y + 68, w, 42};
}
inline Rect RankListRect(float sw, float sh) { Rect p = MainPanel(sw, sh); return {p.x + 20, p.y + 122, p.w - 40, p.h - 144}; }
inline Rect DevRowRect(int row, float sw, float sh) { Rect p = MainPanel(sw, sh); return {p.x + 28, p.y + 80 + row * 60.0f, p.w - 56, 50}; }
inline Rect DevMinusRect(int row, float sw, float sh) { Rect r = DevRowRect(row, sw, sh); return {r.x + r.w - 132, r.y + 3, 54, 44}; }
inline Rect DevPlusRect(int row, float sw, float sh) { Rect r = DevRowRect(row, sw, sh); return {r.x + r.w - 64, r.y + 3, 54, 44}; }
inline Rect DevSaveRect(float sw, float sh) { Rect p = MainPanel(sw, sh); return {p.x + p.w - 184, p.y + p.h - 58, 74, 42}; }
inline Rect DevBackRect(float sw, float sh) { Rect p = MainPanel(sw, sh); return {p.x + p.w - 100, p.y + p.h - 58, 74, 42}; }
inline Rect AvatarControlRect(int i, float sw, float sh) {
    Rect p = MainPanel(sw, sh); const float gap = 10, w = (p.w - 70) * 0.5f, h = 48; int col = i % 2, row = i / 2;
    return {p.x + 25 + col * (w + gap), p.y + p.h - 170 + row * (h + gap), w, h};
}
inline int RankRowCount() { return RankTab() == 2 ? 28 : 100; }

}  // namespace SCBDInGameLayerState
'''
(scbd_dir / 'SCBDInGameLayerState.h').write_text(state_h, encoding='utf-8')

# EmuScreen: one launcher, hide old SCBD debug buttons, intercept layer touch.
s = emu_text
s = replace_once(s, '#include "SCBD/SCBDNativeHUDScreens.h"\n', '#include "SCBD/SCBDNativeHUDScreens.h"\n#include "SCBD/SCBDInGameLayerState.h"\n', 'layer include')
s = replace_once(s, '                "MATCH HUD",\n                new AnchorLayoutParams(150, 50, NONE, 10, 170, NONE)\n', '                "SCBD",\n                new AnchorLayoutParams(128, 64, NONE, 18, 18, NONE)\n', 'launcher position')
s = replace_once(s, '        g_scbdMatchHUDButton->SetScale(0.62f);\n', '        g_scbdMatchHUDButton->SetScale(0.78f);\n', 'launcher scale')

start = '        g_scbdMatchHUDButton->OnClick.Add([](UI::EventParams &) {\n'
end = '        g_scbdRankMenuButton = root_->Add(\n'
a = s.find(start); b = s.find(end, a + len(start))
if a < 0 or b < 0: raise SystemExit('launcher click markers missing')
s = s[:a] + '''        g_scbdMatchHUDButton->OnClick.Add([](UI::EventParams &) {
            SCBDInGameLayerState::ToggleMenu();
        });

''' + s[b:]

s = replace_once(s, '''        g_scbdRankMenuButton->OnClick.Add([this](UI::EventParams &) {
            screenManager()->push(new SCBDNativeRankScreen());
        });
''', '''        g_scbdRankMenuButton->OnClick.Add([](UI::EventParams &) {
            SCBDInGameLayerState::SetPanel(SCBDInGameLayerState::Panel::RANK);
        });
''', 'remove Rank PopupScreen push')
s = replace_once(s, '''        g_scbdDevButton->OnClick.Add([this](UI::EventParams &) {
            screenManager()->push(new SCBDNativeDevScreen());
        });
''', '''        g_scbdDevButton->OnClick.Add([](UI::EventParams &) {
            SCBDInGameLayerState::SetPanel(SCBDInGameLayerState::Panel::DEV);
        });
''', 'remove DEV PopupScreen push')

def hide_visibility(text, var):
    start = f'    if ({var}) {{\n'; a = text.find(start)
    if a < 0: raise SystemExit(f'visibility start missing: {var}')
    b = text.find('    }\n\n', a)
    if b < 0: raise SystemExit(f'visibility end missing: {var}')
    b += len('    }\n\n')
    if var == 'g_scbdMatchHUDButton':
        repl = f'''    if ({var}) {{
        {var}->SetVisibility((scbdTarget && !SCBDInGameLayerState::Open()) ? UI::V_VISIBLE : UI::V_GONE);
    }}

'''
    else:
        repl = f'''    if ({var}) {{
        {var}->SetVisibility(UI::V_GONE);
    }}

'''
    return text[:a] + repl + text[b:]

for var in ('g_scbdInspectorButton','g_scbdAvatarButton','g_scbdMatchHUDButton','g_scbdRankMenuButton','g_scbdDevButton','g_scbdNativeTestButton'):
    s = hide_visibility(s, var)

touch_anchor = 'bool EmuScreen::touch(const TouchInput &touch) {\n'
if s.count(touch_anchor) != 1: raise SystemExit('touch anchor mismatch')
touch_helper = r'''static bool HandleSCBDLayerTouch(const TouchInput &touch, float sw, float sh) {
    using namespace SCBDInGameLayerState;
    if (SwallowUntilUp()) {
        if (touch.flags & TouchInputFlags::UP) SetSwallowUntilUp(false);
        return true;
    }
    if (!Open()) return false;
    if (touch.flags & (TouchInputFlags::CANCEL | TouchInputFlags::RELEASE_ALL)) { EndRankDrag(); return true; }
    const Panel panel = CurrentPanel();
    if (panel == Panel::RANK && RankDragging() && (touch.flags & TouchInputFlags::MOVE)) {
        const Rect list = RankListRect(sw, sh); const float rowH = 36.0f;
        DragRankTo(touch.y, std::max(0.0f, RankRowCount() * rowH - list.h)); return true;
    }
    if (touch.flags & TouchInputFlags::UP) { EndRankDrag(); return true; }
    if (!(touch.flags & TouchInputFlags::DOWN)) return true;
    if (HeaderCloseRect(sw, sh).Contains(touch.x, touch.y)) { CloseAndSwallow(); return true; }
    if (panel != Panel::MENU && HeaderBackRect(sw, sh).Contains(touch.x, touch.y)) { EndRankDrag(); SetPanel(Panel::MENU); return true; }
    if (panel == Panel::MENU) {
        for (int i = 0; i < 6; ++i) if (MenuButtonRect(i, sw, sh).Contains(touch.x, touch.y)) {
            if (i == 0) SetPanel(Panel::RANK);
            if (i == 1) SetPanel(Panel::DEV);
            if (i == 2) { SCBDAvatarState::SetEnabled(true); SetAvatarTestEnabled(true); SetPanel(Panel::AVATAR_TEST); }
            if (i == 3) SCBDNativeHUD::ToggleMatchHud();
            if (i == 4) SCBDAvatarState::Toggle();
            if (i == 5) CloseAndSwallow();
            return true;
        }
        return true;
    }
    if (panel == Panel::RANK) {
        for (int i = 0; i < 4; ++i) if (RankTabRect(i, sw, sh).Contains(touch.x, touch.y)) { SetRankTab(i); EndRankDrag(); return true; }
        if (RankListRect(sw, sh).Contains(touch.x, touch.y)) BeginRankDrag(touch.y);
        return true;
    }
    if (panel == Panel::DEV) {
        auto &cfg = SCBDNativeHUD::Cfg(); bool changed = false;
        for (int row = 0; row < 4; ++row) {
            if (DevMinusRect(row, sw, sh).Contains(touch.x, touch.y)) { if (row == 0) cfg.matchY -= 10; if (row == 1) cfg.matchPanelWidth -= 20; if (row == 2) cfg.matchPanelOpacity -= 15; if (row == 3) cfg.matchFontPct -= 2; changed = true; }
            if (DevPlusRect(row, sw, sh).Contains(touch.x, touch.y)) { if (row == 0) cfg.matchY += 10; if (row == 1) cfg.matchPanelWidth += 20; if (row == 2) cfg.matchPanelOpacity += 15; if (row == 3) cfg.matchFontPct += 2; changed = true; }
        }
        if (DevRowRect(4, sw, sh).Contains(touch.x, touch.y)) { SCBDNativeHUD::ToggleTestData(); changed = true; }
        if (DevSaveRect(sw, sh).Contains(touch.x, touch.y)) { SCBDNativeHUD::SaveConfig(); g_OSD.Show(OSDType::MESSAGE_INFO, "SCBD HUD config saved", 1.2f, "scbd_hud_saved"); return true; }
        if (DevBackRect(sw, sh).Contains(touch.x, touch.y)) { SCBDNativeHUD::SaveConfig(); SetPanel(Panel::MENU); return true; }
        if (changed) { SCBDNativeHUD::ClampConfig(); SCBDNativeHUD::SaveConfig(); }
        return true;
    }
    if (panel == Panel::AVATAR_TEST) {
        if (AvatarControlRect(0, sw, sh).Contains(touch.x, touch.y)) AdjustAvatarRadius(-2);
        else if (AvatarControlRect(1, sw, sh).Contains(touch.x, touch.y)) AdjustAvatarRadius(+2);
        else if (AvatarControlRect(2, sw, sh).Contains(touch.x, touch.y)) AdjustAvatarYOffset(-4);
        else if (AvatarControlRect(3, sw, sh).Contains(touch.x, touch.y)) AdjustAvatarYOffset(+4);
        else if (AvatarControlRect(4, sw, sh).Contains(touch.x, touch.y)) { if (ToggleAvatarTest()) SCBDAvatarState::SetEnabled(true); }
        else if (AvatarControlRect(5, sw, sh).Contains(touch.x, touch.y)) { ResetAvatarPreview(); SCBDAvatarState::SetEnabled(true); }
        return true;
    }
    return true;
}

'''
s = s.replace(touch_anchor, touch_helper + touch_anchor, 1)
body = 'bool EmuScreen::touch(const TouchInput &touch) {\n\tSystem_Notify(SystemNotification::ACTIVITY);\n\n'
if body not in s: raise SystemExit('touch body anchor missing')
s = s.replace(body, body + '\tconst Bounds &scbdBounds = screenManager()->getUIContext()->GetBounds();\n\tif (HandleSCBDLayerTouch(touch, scbdBounds.w, scbdBounds.h))\n\t\treturn true;\n\n', 1)
emu.write_text(s, encoding='utf-8')

# DebugOverlay: in-game layer, no screen stack, avatar placement test.
s = debug_text
s = replace_once(s, '#include "SCBD/SCBDNativeHUDConfig.h"\n', '#include "SCBD/SCBDNativeHUDConfig.h"\n#include "SCBD/SCBDInGameLayerState.h"\n', 'debug layer include')
s = replace_once(s, '    const float centerY = head.y - 10.0f;\n    const float radius = 28.0f;\n', '    const float centerY = head.y + static_cast<float>(SCBDInGameLayerState::AvatarYOffset());\n    const float radius = static_cast<float>(SCBDInGameLayerState::AvatarRadius());\n', 'avatar geometry')
s = replace_once(s, '        player == 1 ? "P1" : "P2",\n        centerX,\n        centerY,\n', '        SCBDInGameLayerState::AvatarTestEnabled() ? (player == 1 ? "TINA" : "EHBUDDEN") : (player == 1 ? "P1" : "P2"),\n        centerX,\n        centerY,\n', 'avatar test label')
s = replace_once(s, '    if (cfg.autoHideMatchHudInRankMenu && RankMenuOpen())\n        return;\n', '    if (cfg.autoHideMatchHudInRankMenu && (RankMenuOpen() || SCBDInGameLayerState::Open()))\n        return;\n', 'hide match hud during layer')

layer_draw = r'''
static void DrawSCBDLayerButton(UIContext *ctx, FontID font, const SCBDInGameLayerState::Rect &r, const char *text, uint32_t bg) {
    ctx->Flush(); ctx->BeginNoTex(); ctx->Draw()->Rect(r.x, r.y, r.w, r.h, bg); ctx->Draw()->Rect(r.x, r.y, r.w, 2.0f, 0x88FFFFFF);
    ctx->Flush(); ctx->Begin(); ctx->BindFontTexture(); ctx->Draw()->SetFontScale(0.40f, 0.40f);
    ctx->Draw()->DrawText(font, text, r.x + r.w * 0.5f, r.y + r.h * 0.5f, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
}

static void DrawSCBDInGameLayer(UIContext *ctx, FontID font, const Bounds &bounds) {
    using namespace SCBDInGameLayerState;
    if (!Open()) return;
    const float sw = bounds.w, sh = bounds.h; const Rect panel = MainPanel(sw, sh); const Panel page = CurrentPanel();
    ctx->Flush(); ctx->BeginNoTex();
    ctx->Draw()->Rect(bounds.x, bounds.y, bounds.w, bounds.h, 0xA8000000);
    ctx->Draw()->Rect(panel.x - 3, panel.y - 3, panel.w + 6, panel.h + 6, 0xCC38BDF8);
    ctx->Draw()->Rect(panel.x, panel.y, panel.w, panel.h, 0xF0181C26);
    ctx->Draw()->Rect(panel.x, panel.y, panel.w, 62, 0xFF202938);
    ctx->Flush(); ctx->Begin(); ctx->BindFontTexture(); ctx->Draw()->SetFontScale(0.52f, 0.52f);
    const char *title = page == Panel::RANK ? "SCBD RANKING" : page == Panel::DEV ? "SCBD DEV" : page == Panel::AVATAR_TEST ? "TEST AVATAR" : "SCBD CONTROL";
    ctx->Draw()->DrawText(font, title, panel.x + panel.w * 0.5f, panel.y + 30, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
    if (page != Panel::MENU) DrawSCBDLayerButton(ctx, font, HeaderBackRect(sw, sh), "< BACK", 0xDD2C3442);
    DrawSCBDLayerButton(ctx, font, HeaderCloseRect(sw, sh), "X", 0xDDAA3344);

    if (page == Panel::MENU) {
        const auto &cfg = SCBDNativeHUD::Cfg();
        const char *labels[6] = {"BXH","DEV","TEST AVATAR",cfg.matchHudVisible ? "MATCH HUD: ON" : "MATCH HUD: OFF",SCBDAvatarState::Enabled() ? "AVATAR: ON" : "AVATAR: OFF","CLOSE"};
        for (int i = 0; i < 6; ++i) DrawSCBDLayerButton(ctx, font, MenuButtonRect(i, sw, sh), labels[i], i == 2 ? 0xDD315A44 : i == 5 ? 0xDD74343E : 0xDD273244);
    }

    if (page == Panel::RANK) {
        static const char *tabs[4] = {"TOP TUAN","TOP THANG","TOP NHAN VAT","CHUOI WIN"}; const int active = RankTab();
        for (int i = 0; i < 4; ++i) DrawSCBDLayerButton(ctx, font, RankTabRect(i, sw, sh), tabs[i], i == active ? 0xEE2E6E93 : 0xCC2A3240);
        const Rect list = RankListRect(sw, sh); const float rowH = 36.0f, scroll = RankScroll(); const int total = RankRowCount(); const int first = std::max(0, static_cast<int>(scroll / rowH)); const float yoff = -(scroll - first * rowH);
        static const char *names[10] = {"TINA","EHBUDDEN","FLO","CHI_DUOT","VIEWER_A","VIEWER_B","PLAYER_88","TOP_GIFTER","SCBD_FAN","VIEWER_X"};
        static const char *chars[28] = {"ALGOL","AMY","ASTAROTH","CASSANDRA","CERVANTES","DAMPIERRE","HILDE","IVY","KILIK","KRATOS","LIZARDMAN","MAXI","MITSURUGI","NIGHTMARE","RAPHAEL","ROCK","SEONG_MI_NA","SETSUKA","SIEGFRIED","SOPHITIA","TAKI","TALIM","TIRA","VOLDO","XIANGHUA","YOSHIMITSU","YUN_SEONG","ZASALAMEL"};
        ctx->Flush(); ctx->BeginNoTex(); ctx->Draw()->Rect(list.x, list.y, list.w, list.h, 0xB810141C); ctx->Flush(); ctx->Begin(); ctx->BindFontTexture();
        for (int i = first; i < total; ++i) {
            const float y = list.y + yoff + (i - first) * rowH; if (y > list.y + list.h - 2) break;
            char line[256];
            if (active == 2) std::snprintf(line, sizeof(line), "%02d. %-12s : %s - %s - %s", i + 1, chars[i], names[i % 10], names[(i + 3) % 10], names[(i + 6) % 10]);
            else if (active == 3) std::snprintf(line, sizeof(line), "#%03d [AV] %-12s CURRENT:%d BEST:%d", i + 1, names[i % 10], (100 - i) % 11, std::max(1, 100 - i));
            else { int base = active == 0 ? 1820000 : 9850000, step = active == 0 ? 9250 : 37850; std::snprintf(line, sizeof(line), "#%03d [AV] %-12s %d", i + 1, names[i % 10], std::max(1, base - i * step)); }
            ctx->Flush(); ctx->BeginNoTex(); ctx->Draw()->Rect(list.x + 3, y + 1, list.w - 6, rowH - 2, (i % 2) ? 0x8C1D2430 : 0xA8252C38); ctx->Flush(); ctx->Begin(); ctx->BindFontTexture(); ctx->Draw()->SetFontScale(0.36f, 0.36f);
            ctx->Draw()->DrawText(font, line, list.x + 12, y + rowH * 0.5f, i < 3 ? 0xFF8CEBFF : 0xFFFFFFFF, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
        }
    }

    if (page == Panel::DEV) {
        const auto &cfg = SCBDNativeHUD::Cfg(); const char *names[5] = {"HUD Y","PANEL WIDTH","OPACITY","FONT %","TEST DATA"}; int values[5] = {cfg.matchY,cfg.matchPanelWidth,cfg.matchPanelOpacity,cfg.matchFontPct,cfg.testData ? 1 : 0};
        for (int i = 0; i < 5; ++i) {
            const Rect row = DevRowRect(i, sw, sh); char line[96]; if (i == 4) std::snprintf(line, sizeof(line), "%s : %s", names[i], values[i] ? "ON" : "OFF"); else std::snprintf(line, sizeof(line), "%s : %d", names[i], values[i]);
            ctx->Flush(); ctx->BeginNoTex(); ctx->Draw()->Rect(row.x, row.y, row.w, row.h, 0xB8242B38); ctx->Flush(); ctx->Begin(); ctx->BindFontTexture(); ctx->Draw()->SetFontScale(0.38f, 0.38f); ctx->Draw()->DrawText(font, line, row.x + 14, row.y + row.h * 0.5f, 0xFFFFFFFF, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
            if (i < 4) { DrawSCBDLayerButton(ctx, font, DevMinusRect(i, sw, sh), "-", 0xDD3A4352); DrawSCBDLayerButton(ctx, font, DevPlusRect(i, sw, sh), "+", 0xDD3A4352); }
        }
        DrawSCBDLayerButton(ctx, font, DevSaveRect(sw, sh), "SAVE", 0xDD315A44); DrawSCBDLayerButton(ctx, font, DevBackRect(sw, sh), "BACK", 0xDD3A4352);
    }

    if (page == Panel::AVATAR_TEST) {
        const float bodyY = panel.y + 165, x1 = panel.x + panel.w * 0.32f, x2 = panel.x + panel.w * 0.68f, radius = static_cast<float>(AvatarRadius()), avatarY = bodyY + static_cast<float>(AvatarYOffset());
        ctx->Flush(); ctx->BeginNoTex();
        for (int p = 0; p < 2; ++p) { float x = p ? x2 : x1; uint32_t fill = p ? 0xE06B78FF : 0xE04CCF70; ctx->Draw()->FillCircle(x, bodyY, 8, 24, 0xFFFFCC55); ctx->Draw()->Rect(x - 8, bodyY + 8, 16, 60, 0xBB98A5B5); ctx->Draw()->FillCircle(x, avatarY, radius + 4, 40, 0xD0000000); ctx->Draw()->FillCircle(x, avatarY, radius + 2, 40, 0xFFFFFFFF); ctx->Draw()->FillCircle(x, avatarY, radius, 40, fill); }
        ctx->Flush(); ctx->Begin(); ctx->BindFontTexture(); ctx->Draw()->SetFontScale(0.40f, 0.40f); ctx->Draw()->DrawText(font, "TINA", x1, avatarY, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII); ctx->Draw()->DrawText(font, "EHBUDDEN", x2, avatarY, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
        char status[128]; std::snprintf(status, sizeof(status), "LIVE:%s SIZE:%d Y:%d", AvatarTestEnabled() ? "ON" : "OFF", AvatarRadius(), AvatarYOffset()); ctx->Draw()->SetFontScale(0.31f, 0.31f); ctx->Draw()->DrawText(font, status, panel.x + panel.w * 0.5f, panel.y + panel.h - 184, 0xFFBFD0E0, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
        const char *controls[6] = {"SIZE -","SIZE +","Y UP","Y DOWN",AvatarTestEnabled() ? "LIVE TEST: ON" : "LIVE TEST: OFF","RESET"};
        for (int i = 0; i < 6; ++i) DrawSCBDLayerButton(ctx, font, AvatarControlRect(i, sw, sh), controls[i], i == 4 ? 0xDD315A44 : 0xDD2C3442);
    }
    ctx->Draw()->SetFontScale(1.0f, 1.0f); ctx->Flush(); ctx->RebindTexture();
}

'''
marker = 'static void DrawSCBDBoneMapper('
if s.count(marker) != 1: raise SystemExit('mapper marker mismatch')
s = s.replace(marker, layer_draw + marker, 1)
call = '    DrawSCBDMatchTop10HUD(ctx, ubuntu24, bounds);\n'
if s.count(call) != 1: raise SystemExit('Match HUD call mismatch')
s = s.replace(call, call + '    DrawSCBDInGameLayer(ctx, ubuntu24, bounds);\n', 1)
debug.write_text(s, encoding='utf-8')

with info.open('a', encoding='utf-8') as f:
    f.write('\nV0.5.0 HOTFIX5 IN-GAME LAYER\n- no PopupScreen push for SCBD layer\n- one SCBD launcher; old overlapping SCBD buttons hidden\n- modal touch blocked from PSP controls until UP\n- Top100 continuous drag scroll; 28 characters x Top3\n- DEV live settings saved to scbd_native_hud.ini\n- Avatar Test preview + live tracked mock names + size/Y controls\n')

print('PSP Live FloGB V0.5.0 Hotfix5 patch applied successfully.')
