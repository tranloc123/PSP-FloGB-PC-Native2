from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_5_2.py <ppsspp_repo>")

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
    a = text.find(start)
    if a < 0:
        raise SystemExit(f"{label}: start marker missing")
    b = text.find(end, a + len(start))
    if b < 0:
        raise SystemExit(f"{label}: end marker missing")
    return text[:a] + replacement + text[b:]

debug = require("UI/DebugOverlay.cpp")
info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")
s = debug.read_text(encoding="utf-8")

for marker in (
    "DrawSCBDMatchTop5HUD",
    "TEST AVATAR BXH",
    '"TOP TUAN","TOP THANG","TOP NHAN VAT","CHUOI WIN"',
    '"#%03d [AV] %-12s %d"',
    '"%02d. %-12s : %s - %s - %s"',
):
    if marker not in s:
        raise SystemExit(f"V0.5.1 prerequisite missing in DebugOverlay.cpp: {marker}")

# -----------------------------------------------------------------------------
# Mock avatar render layer. These slots deliberately use deterministic initials
# and colors today so V0.5.2 can validate layout. The next live bridge can swap
# the circle contents for downloaded TikTok avatar textures without moving text.
# -----------------------------------------------------------------------------
helper = r'''struct SCBDRankAvatarMock {
    const char *name;
    const char *initial;
    uint32_t color;
};

static const SCBDRankAvatarMock kSCBDRankUsers[10] = {
    {"TINA",       "T", 0xE04CCF70},
    {"EHBUDDEN",   "E", 0xE06B78FF},
    {"FLO",        "F", 0xE0D96A63},
    {"CHI_DUOT",   "C", 0xE08E7BD8},
    {"VIEWER_A",   "A", 0xE05DB8C7},
    {"VIEWER_B",   "B", 0xE0C18A54},
    {"PLAYER_88",  "88",0xE08BA56A},
    {"TOP_GIFTER", "G", 0xE09D6FCB},
    {"SCBD_FAN",   "S", 0xE05F96D2},
    {"VIEWER_X",   "X", 0xE0C85B79},
};

static const uint32_t kSCBDCharacterColors[28] = {
    0xFF566C86,0xFFB98A6E,0xFF87494A,0xFFB89063,0xFF6D6A58,0xFF6D7288,0xFF9A5B58,
    0xFF7F6799,0xFF7B604B,0xFF9A4B45,0xFF68835D,0xFF675982,0xFF8E6352,0xFF66546C,
    0xFF6D7B91,0xFF826A55,0xFF6D8C9D,0xFF8B6B8F,0xFF6B7A91,0xFFAA886A,0xFF805B72,
    0xFF5D8790,0xFF80606B,0xFF625B74,0xFF9A6B57,0xFF6B7959,0xFF5F7589,0xFF715D82,
};

static uint32_t SCBDRankNumberColor(int rank) {
    if (rank == 1) return 0xFFFFD86A;
    if (rank == 2) return 0xFFD9E2EA;
    if (rank == 3) return 0xFFE3A472;
    return 0xFFFFFFFF;
}

static void DrawSCBDRankAvatar(
    UIContext *ctx,
    FontID font,
    const SCBDRankAvatarMock &user,
    float cx,
    float cy,
    float radius
) {
    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->FillCircle(cx, cy, radius + 2.0f, 28, 0xCC000000);
    ctx->Draw()->FillCircle(cx, cy, radius + 1.0f, 28, 0xFFE8C86A);
    ctx->Draw()->FillCircle(cx, cy, radius, 28, user.color);
    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();
    ctx->Draw()->SetFontScale(radius <= 10.0f ? 0.24f : 0.28f, radius <= 10.0f ? 0.24f : 0.28f);
    ctx->Draw()->DrawText(font, user.initial, cx, cy, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
}

static void DrawSCBDCharacterPortraitSlot(
    UIContext *ctx,
    FontID font,
    const char *character,
    int index,
    float x,
    float y,
    float w,
    float h
) {
    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->Rect(x, y, w, h, kSCBDCharacterColors[index % 28]);
    ctx->Draw()->Rect(x, y, w, 2.0f, 0x99FFFFFF);
    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();
    char shortName[3] = { character[0], character[1] ? character[1] : '\0', '\0' };
    ctx->Draw()->SetFontScale(0.30f, 0.30f);
    ctx->Draw()->DrawText(font, shortName, x + w * 0.5f, y + h * 0.5f, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
}

'''

marker = "static void DrawSCBDInGameLayer("
if s.count(marker) != 1:
    raise SystemExit(f"V0.5.2 DrawSCBDInGameLayer marker count = {s.count(marker)}")
s = s.replace(marker, helper + marker, 1)

rank_block = r'''    if (page == Panel::RANK) {
        static const char *tabs[4] = {"TOP TUAN","TOP THANG","TOP NHAN VAT","CHUOI WIN"};
        const int active = RankTab();
        for (int i = 0; i < 4; ++i)
            DrawSCBDLayerButton(ctx, font, RankTabRect(i, sw, sh), tabs[i], i == active ? 0xEE9B7427 : 0xCC2A3240);

        const Rect list = RankListRect(sw, sh);
        const float rowH = 36.0f;
        const float scroll = RankScroll();
        const int total = RankRowCount();
        const int first = std::max(0, static_cast<int>(scroll / rowH));
        const float yoff = -(scroll - first * rowH);
        static const char *chars[28] = {
            "ALGOL","AMY","ASTAROTH","CASSANDRA","CERVANTES","DAMPIERRE","HILDE",
            "IVY","KILIK","KRATOS","LIZARDMAN","MAXI","MITSURUGI","NIGHTMARE",
            "RAPHAEL","ROCK","SEONG_MI_NA","SETSUKA","SIEGFRIED","SOPHITIA","TAKI",
            "TALIM","TIRA","VOLDO","XIANGHUA","YOSHIMITSU","YUN_SEONG","ZASALAMEL"
        };

        ctx->Flush();
        ctx->BeginNoTex();
        ctx->Draw()->Rect(list.x, list.y, list.w, list.h, 0xB810141C);
        ctx->Flush();
        ctx->Begin();
        ctx->BindFontTexture();

        for (int i = first; i < total; ++i) {
            const float y = list.y + yoff + (i - first) * rowH;
            if (y > list.y + list.h - 2.0f)
                break;
            if (y + rowH < list.y)
                continue;

            const float cy = y + rowH * 0.5f;
            const uint32_t rowColor = (i % 2) ? 0x8C1D2430 : 0xA8252C38;
            ctx->Flush();
            ctx->BeginNoTex();
            ctx->Draw()->Rect(list.x + 3.0f, y + 1.0f, list.w - 6.0f, rowH - 2.0f, rowColor);
            ctx->Flush();
            ctx->Begin();
            ctx->BindFontTexture();

            char rankText[12];
            std::snprintf(rankText, sizeof(rankText), "%d", i + 1);
            ctx->Draw()->SetFontScale(0.36f, 0.36f);
            ctx->Draw()->DrawText(font, rankText, list.x + 12.0f, cy, SCBDRankNumberColor(i + 1), ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);

            if (active == 2) {
                // Approved Top Character layout:
                // rank | character portrait slot + name | avatar+viewer x3
                const float portraitX = list.x + 46.0f;
                const float portraitW = 38.0f;
                const float portraitH = rowH - 4.0f;
                DrawSCBDCharacterPortraitSlot(ctx, font, chars[i], i, portraitX, y + 2.0f, portraitW, portraitH);

                ctx->Draw()->SetFontScale(0.34f, 0.34f);
                ctx->Draw()->DrawText(font, chars[i], portraitX + portraitW + 10.0f, cy, 0xFFFFFFFF, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);

                const float usersStart = list.x + std::min(250.0f, list.w * 0.31f);
                const float userColumnW = (list.x + list.w - usersStart - 8.0f) / 3.0f;
                for (int slot = 0; slot < 3; ++slot) {
                    const int userIndex = (i + slot * 3) % 10;
                    const SCBDRankAvatarMock &user = kSCBDRankUsers[userIndex];
                    const float colX = usersStart + userColumnW * slot;
                    const float avatarX = colX + 13.0f;
                    DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 10.5f);
                    ctx->Draw()->SetFontScale(0.30f, 0.30f);
                    ctx->Draw()->DrawTextRect(
                        font,
                        user.name,
                        colX + 29.0f,
                        y + 4.0f,
                        userColumnW - 32.0f,
                        rowH - 8.0f,
                        0xFFFFFFFF,
                        ALIGN_VCENTER | FLAG_DYNAMIC_ASCII
                    );
                }
            } else {
                // Week / Month / Win Streak:
                // plain rank | avatar | username | value aligned to the right.
                const SCBDRankAvatarMock &user = kSCBDRankUsers[i % 10];
                const float avatarX = list.x + 58.0f;
                DrawSCBDRankAvatar(ctx, font, user, avatarX, cy, 11.0f);

                ctx->Draw()->SetFontScale(0.34f, 0.34f);
                ctx->Draw()->DrawText(font, user.name, list.x + 78.0f, cy, 0xFFFFFFFF, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);

                char valueText[64];
                if (active == 3) {
                    const int best = std::max(1, 100 - i);
                    std::snprintf(valueText, sizeof(valueText), "%d WIN", best);
                } else {
                    const int base = active == 0 ? 1820000 : 9850000;
                    const int step = active == 0 ? 9250 : 37850;
                    std::snprintf(valueText, sizeof(valueText), "%d", std::max(1, base - i * step));
                }
                ctx->Draw()->SetFontScale(0.34f, 0.34f);
                ctx->Draw()->DrawText(font, valueText, list.x + list.w - 14.0f, cy, 0xFFFFD77A, ALIGN_RIGHT | ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
            }
        }
    }

'''

s = replace_between(
    s,
    "    if (page == Panel::RANK) {\n",
    "    if (page == Panel::DEV) {\n",
    rank_block,
    "replace global ranking layout with avatar layout",
)

# Make sure old placeholder formatting is gone from the live in-game rank layer.
for forbidden in (
    '"#%03d [AV] %-12s %d"',
    '"#%03d [AV] %-12s CURRENT:%d BEST:%d"',
    '"%02d. %-12s : %s - %s - %s"',
):
    if forbidden in s:
        raise SystemExit(f"V0.5.2 forbidden legacy rank format survived: {forbidden}")

for required in (
    "DrawSCBDRankAvatar",
    "DrawSCBDCharacterPortraitSlot",
    'std::snprintf(rankText, sizeof(rankText), "%d", i + 1);',
    '"%d WIN"',
    "userColumnW * slot",
):
    if required not in s:
        raise SystemExit(f"V0.5.2 required layout marker missing: {required}")

debug.write_text(s, encoding="utf-8")

with info.open("a", encoding="utf-8") as f:
    f.write(
        "\nPSP Live FloGB V0.5.2 Global Ranking Avatar Layout\n"
        "Rank numbers: plain 1..100, no # and no leading zero padding\n"
        "Week/Month/Win: rank + circular avatar slot + username + right-aligned value\n"
        "Character: approved layout with character portrait slot/name + 3 viewer avatar/name columns\n"
        "Mock avatar slots are deterministic and reserved for future TikTok live avatar textures\n"
        "V0.5.1 transparent Top5 battle HUD remains unchanged\n"
    )

print("PSP Live FloGB V0.5.2 Global Ranking Avatar Layout patch applied successfully.")
