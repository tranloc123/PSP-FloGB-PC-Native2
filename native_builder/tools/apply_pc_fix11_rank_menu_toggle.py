from __future__ import annotations

from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('Usage: apply_pc_fix11_rank_menu_toggle.py <ppsspp_repo>')

REPO = Path(sys.argv[1]).resolve()
state = REPO / 'SCBD' / 'SCBDInGameLayerState.h'
emu = REPO / 'UI' / 'EmuScreen.cpp'
debug = REPO / 'UI' / 'DebugOverlay.cpp'
info = REPO / 'PSP_LIVE_FLOGB_BUILD_INFO.txt'

for p in (state, emu, debug):
    if not p.exists():
        raise SystemExit(f'FIX11 missing generated file: {p}')


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    src = path.read_text(encoding='utf-8')
    count = src.count(old)
    if count != 1:
        raise SystemExit(f'FIX11 {label}: expected 1 occurrence, found {count}')
    path.write_text(src.replace(old, new, 1), encoding='utf-8')
    print(f'FIX11 {label}: PASS')


def insert_before_once(path: Path, marker: str, addition: str, label: str) -> None:
    src = path.read_text(encoding='utf-8')
    count = src.count(marker)
    if count != 1:
        raise SystemExit(f'FIX11 {label}: expected 1 marker, found {count}')
    path.write_text(src.replace(marker, addition + marker, 1), encoding='utf-8')
    print(f'FIX11 {label}: PASS')


print('=== PSP FloGB FIX11: NATIVE RANK MENU + RELIABLE CLOSE ===')

# 1) Add dedicated BXH menu state.
replace_once(
    state,
    'enum class Panel : int { NONE = 0, MENU = 1, RANK = 2, DEV = 3, AVATAR_TEST = 4, WINNER_TEST = 5, INPUT_TEST = 6 };',
    'enum class Panel : int { NONE = 0, MENU = 1, RANK = 2, DEV = 3, AVATAR_TEST = 4, WINNER_TEST = 5, INPUT_TEST = 6, RANK_MENU = 7 };',
    'extend panel enum with RANK_MENU',
)
replace_once(
    state,
    '    if (v < 0 || v > 6) v = 0;',
    '    if (v < 0 || v > 7) v = 0;',
    'extend panel clamp',
)

rank_rects = r'''inline Rect RankMenuChoiceRect(int i, float sw, float sh) {
    Rect p = MainPanel(sw, sh);
    const float gap = 14.0f;
    const float bw = (p.w - gap * 3.0f) * 0.5f;
    const float bh = 72.0f;
    const int col = i % 2;
    const int row = i / 2;
    return {p.x + gap + col * (bw + gap), p.y + 102.0f + row * (bh + gap), bw, bh};
}
inline Rect RankFooterBackRect(float sw, float sh) {
    Rect p = MainPanel(sw, sh);
    return {p.x + 22.0f, p.y + p.h - 58.0f, 200.0f, 42.0f};
}
inline Rect RankFooterCloseRect(float sw, float sh) {
    Rect p = MainPanel(sw, sh);
    return {p.x + p.w - 162.0f, p.y + p.h - 58.0f, 140.0f, 42.0f};
}
'''
insert_before_once(
    state,
    'inline int RankRowCount() { return RankTab() == 2 ? 28 : 100; }',
    rank_rects,
    'rank menu/footer rectangles',
)

# 2) Touch routing.
replace_once(
    emu,
    '            if (i == 0) SetPanel(Panel::RANK);',
    '            if (i == 0) SetPanel(Panel::RANK_MENU);',
    'main BXH opens rank menu',
)
replace_once(
    emu,
    '    if (panel != Panel::MENU && HeaderBackRect(sw, sh).Contains(touch.x, touch.y)) { EndRankDrag(); SetPanel(Panel::MENU); return true; }',
    '''    if (panel != Panel::MENU && HeaderBackRect(sw, sh).Contains(touch.x, touch.y)) {
        EndRankDrag();
        SetPanel(panel == Panel::RANK ? Panel::RANK_MENU : Panel::MENU);
        return true;
    }''',
    'header BACK routing',
)

rank_menu_touch = r'''    if (panel == Panel::RANK_MENU) {
        for (int i = 0; i < 4; ++i) {
            if (RankMenuChoiceRect(i, sw, sh).Contains(touch.x, touch.y)) {
                SetRankTab(i);
                EndRankDrag();
                SetPanel(Panel::RANK);
                return true;
            }
        }
        if (RankMenuChoiceRect(4, sw, sh).Contains(touch.x, touch.y)) {
            SetPanel(Panel::MENU);
            return true;
        }
        if (RankMenuChoiceRect(5, sw, sh).Contains(touch.x, touch.y)) {
            CloseAndSwallow();
            return true;
        }
        return true;
    }
'''
insert_before_once(
    emu,
    '    if (panel == Panel::RANK) {\n',
    rank_menu_touch,
    'rank menu touch handler',
)
replace_once(
    emu,
    '''    if (panel == Panel::RANK) {
        for (int i = 0; i < 4; ++i) if (RankTabRect(i, sw, sh).Contains(touch.x, touch.y)) { SetRankTab(i); EndRankDrag(); return true; }
        if (RankListRect(sw, sh).Contains(touch.x, touch.y)) BeginRankDrag(touch.y);
        return true;
    }''',
    '''    if (panel == Panel::RANK) {
        if (RankFooterBackRect(sw, sh).Contains(touch.x, touch.y)) {
            EndRankDrag();
            SetPanel(Panel::RANK_MENU);
            return true;
        }
        if (RankFooterCloseRect(sw, sh).Contains(touch.x, touch.y)) {
            EndRankDrag();
            CloseAndSwallow();
            return true;
        }
        if (RankListRect(sw, sh).Contains(touch.x, touch.y))
            BeginRankDrag(touch.y);
        return true;
    }''',
    'rank page footer navigation',
)

# 3) Renderer: do not depend on the outer title expression at all.
# Insert a real BXH submenu immediately before Panel::RANK.
rank_menu_draw = r'''    if (page == Panel::RANK_MENU) {
        ctx->Draw()->SetFontScale(0.42f, 0.42f);
        ctx->Draw()->DrawText(
            font,
            "MENU BANG XEP HANG",
            panel.x + panel.w * 0.5f,
            panel.y + 84.0f,
            0xFFFFD86A,
            ALIGN_CENTER | FLAG_DYNAMIC_ASCII
        );
        const char *rankMenuLabels[6] = {
            "TOP TUAN",
            "TOP THANG",
            "TOP NHAN VAT",
            "CHUOI WIN",
            "< QUAY LAI MENU",
            "DONG"
        };
        for (int i = 0; i < 6; ++i) {
            const uint32_t bg = i == 5 ? 0xDD74343E : i == 4 ? 0xDD3A4352 : 0xDD273244;
            DrawSCBDLayerButton(ctx, font, RankMenuChoiceRect(i, sw, sh), rankMenuLabels[i], bg);
        }
    }

'''
insert_before_once(
    debug,
    '    if (page == Panel::RANK) {\n',
    rank_menu_draw,
    'rank menu renderer',
)

# Replace the complete category-header area of Panel::RANK structurally.
src = debug.read_text(encoding='utf-8')
rank_start = src.find('    if (page == Panel::RANK) {\n')
dev_start = src.find('    if (page == Panel::DEV) {\n', rank_start)
if rank_start < 0 or dev_start < 0:
    raise SystemExit('FIX11 native RANK renderer: structural RANK/DEV boundary missing')

rank_block = src[rank_start:dev_start]
list_marker = '        const Rect list = RankListRect(sw, sh);\n'
list_pos = rank_block.find(list_marker)
if list_pos < 0:
    raise SystemExit('FIX11 native RANK renderer: RankListRect marker missing')

opening = '    if (page == Panel::RANK) {\n'
if not rank_block.startswith(opening):
    raise SystemExit('FIX11 native RANK renderer: unexpected block opening')

rank_header = r'''    if (page == Panel::RANK) {
        static const char *rankTitles[4] = {"TOP TUAN","TOP THANG","TOP NHAN VAT","CHUOI WIN"};
        const int active = RankTab();
        ctx->Draw()->SetFontScale(0.40f, 0.40f);
        ctx->Draw()->DrawText(
            font,
            rankTitles[active],
            panel.x + panel.w * 0.5f,
            panel.y + 88.0f,
            0xFFFFD86A,
            ALIGN_CENTER | FLAG_DYNAMIC_ASCII
        );

'''
rank_block = rank_header + rank_block[list_pos:]

# Append reliable footer controls before the outer Panel::RANK closing brace.
outer_close = rank_block.rfind('    }\n\n')
if outer_close < 0:
    raise SystemExit('FIX11 native RANK renderer: outer closing brace missing')
footer = r'''        DrawSCBDLayerButton(ctx, font, RankFooterBackRect(sw, sh), "< QUAY LAI BXH", 0xDD3A4352);
        DrawSCBDLayerButton(ctx, font, RankFooterCloseRect(sw, sh), "DONG", 0xDD74343E);
'''
rank_block = rank_block[:outer_close] + footer + rank_block[outer_close:]

debug.write_text(src[:rank_start] + rank_block + src[dev_start:], encoding='utf-8')
print('FIX11 replace native RANK renderer: PASS')

# 4) Preflight.
s_state = state.read_text(encoding='utf-8')
s_emu = emu.read_text(encoding='utf-8')
s_debug = debug.read_text(encoding='utf-8')

checks = [
    ('state', s_state, ['RANK_MENU = 7', 'RankMenuChoiceRect', 'RankFooterBackRect', 'RankFooterCloseRect']),
    ('emu', s_emu, ['SetPanel(Panel::RANK_MENU)', 'panel == Panel::RANK_MENU', 'RankFooterBackRect', 'RankFooterCloseRect']),
    ('debug', s_debug, ['MENU BANG XEP HANG', 'rankMenuLabels[6]', 'rankTitles[4]', '< QUAY LAI BXH', 'RankFooterCloseRect']),
]
for name, text, needles in checks:
    missing = [x for x in needles if x not in text]
    if missing:
        raise SystemExit(f'FIX11 preflight missing in {name}: {missing}')

if 'DrawSCBDLayerButton(ctx, font, RankTabRect' in s_debug:
    raise SystemExit('FIX11 old clickable rank tab strip survived')

if info.exists():
    with info.open('a', encoding='utf-8') as f:
        f.write(
            '\nPSP FloGB FIX11 ROBUST V3\n'
            'SCBD MENU -> BXH MENU -> one ranking page\n'
            'Rank page footer: BACK TO BXH + CLOSE\n'
            'Header X remains immediate close\n'
            'No outer title anchor dependency\n'
        )

print('FIX11 SOURCE PREFLIGHT PASS')
print('Rank menu: TOP WEEK / TOP MONTH / CHARACTER / WIN STREAK')
print('Close paths: header X + footer DONG + back to BXH')
print('=== FIX11 PASS ===')
