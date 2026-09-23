from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_5_7a.py <ppsspp_repo>")

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


winner = require("SCBD/SCBDNativeWinner.h")
debug = require("UI/DebugOverlay.cpp")
emu = require("UI/EmuScreen.cpp")
info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")

winner_text = winner.read_text(encoding="utf-8")
debug_text = debug.read_text(encoding="utf-8")
emu_text = emu.read_text(encoding="utf-8")

for marker in (
    "enum class Phase : int",
    "BeginWinnerPick",
    "ShowPickSuccess",
    "ShowTimeout",
    "std::chrono::milliseconds(5500)",
    "std::chrono::milliseconds(15000)",
):
    if marker not in winner_text:
        raise SystemExit(f"V0.5.7A Winner prerequisite missing: {marker}")

for marker in (
    "DrawSCBDNativeWinnerLayer",
    "SCBDWinnerCharacterAtlasIndex",
    "PICK THANH CONG!",
    "RANDOM 30",
    "WINNER TEST",
    "INPUT LAB",
    "DrawSCBDMatchTop5HUD",
):
    if marker not in debug_text:
        raise SystemExit(f"V0.5.7A DebugOverlay prerequisite missing: {marker}")

for marker in (
    "Panel::WINNER_TEST",
    "SCBDNativeWinner::BeginWinnerPick",
    'SCBDNativeWinner::ShowPickSuccess(14, "KRATOS")',
):
    if marker not in emu_text:
        raise SystemExit(f"V0.5.7A EmuScreen prerequisite missing: {marker}")

# -----------------------------------------------------------------------------
# 1) Winner state machine V2.
#    IMPORTANT: timeout NEVER chooses a character. It only shows GAME RANDOM,
#    then closes. The game/random-selection controller owns the random result.
# -----------------------------------------------------------------------------
winner_v2 = r'''#pragma once

#include <algorithm>
#include <chrono>
#include <mutex>
#include <string>

namespace SCBDNativeWinner {

inline constexpr int kWinnerIntroMs = 2200;
inline constexpr int kPickTimeoutMs = 15000;
inline constexpr int kPickSuccessMs = 3200;
inline constexpr int kTimeoutNoticeMs = 1800;

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
    int score = 35420;
    int characterId = 0;
    std::string character;
    std::chrono::steady_clock::time_point deadline{};
};

struct Snapshot {
    Phase phase = Phase::NONE;
    std::string username;
    int team = 1;
    int score = 0;
    int characterId = 0;
    std::string character;
    int remainingMs = 0;
};

inline State &GetState() {
    static State s;
    return s;
}

inline void BeginWinnerPick(const char *username, int team, int score = 35420) {
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    s.username = (username && *username) ? username : "TOP1";
    s.team = team == 2 ? 2 : 1;
    s.score = std::max(0, score);
    s.characterId = 0;
    s.character.clear();
    s.phase = Phase::WINNER;
    s.deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(kWinnerIntroMs);
}

inline void ShowPickSuccess(int characterId, const char *character) {
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    s.characterId = std::clamp(characterId, 1, 28);
    s.character = (character && *character) ? character : "CHARACTER";
    s.phase = Phase::PICK_SUCCESS;
    s.deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(kPickSuccessMs);
}

inline void ShowTimeout() {
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    s.characterId = 0;
    s.character.clear();
    s.phase = Phase::TIMEOUT;
    s.deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(kTimeoutNoticeMs);
}

inline void Cancel() {
    State &s = GetState();
    std::lock_guard<std::mutex> guard(s.mutex);
    s.phase = Phase::NONE;
    s.characterId = 0;
    s.character.clear();
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
        s.deadline = now + std::chrono::milliseconds(kPickTimeoutMs);
    } else if (s.phase == Phase::PICK) {
        // Visual only. The overlay does NOT pick a random fighter.
        // Existing game/random selection logic is responsible for Random.
        s.characterId = 0;
        s.character.clear();
        s.phase = Phase::TIMEOUT;
        s.deadline = now + std::chrono::milliseconds(kTimeoutNoticeMs);
    } else {
        s.phase = Phase::NONE;
        s.characterId = 0;
        s.character.clear();
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
    out.score = s.score;
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
winner.write_text(winner_v2, encoding="utf-8")

# -----------------------------------------------------------------------------
# 2) WINNER V2 LAB controls. Add explicit timeout test and correct KRATOS to 10.
# -----------------------------------------------------------------------------
old_touch = r'''    if (panel == Panel::WINNER_TEST) {
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
'''
new_touch = r'''    if (panel == Panel::WINNER_TEST) {
        if (WinnerButtonRect(0, sw, sh).Contains(touch.x, touch.y)) {
            SCBDNativeWinner::BeginWinnerPick("TINA", 1, 35420);
            CloseAndSwallow();
        } else if (WinnerButtonRect(1, sw, sh).Contains(touch.x, touch.y)) {
            SCBDNativeWinner::BeginWinnerPick("EHBUDDEN", 2, 41880);
            CloseAndSwallow();
        } else if (WinnerButtonRect(2, sw, sh).Contains(touch.x, touch.y)) {
            SCBDNativeWinner::BeginWinnerPick("TINA", 1, 35420);
            SCBDNativeWinner::ShowPickSuccess(10, "KRATOS");
            CloseAndSwallow();
        } else if (WinnerButtonRect(3, sw, sh).Contains(touch.x, touch.y)) {
            SCBDNativeWinner::BeginWinnerPick("TINA", 1, 35420);
            SCBDNativeWinner::ShowTimeout();
            CloseAndSwallow();
        } else if (WinnerButtonRect(4, sw, sh).Contains(touch.x, touch.y)) {
            SCBDNativeWinner::Cancel();
            SetPanel(Panel::MENU);
        }
        return true;
    }
'''
emu_text = replace_once(emu_text, old_touch, new_touch, "upgrade Winner V2 lab touch actions")
emu.write_text(emu_text, encoding="utf-8")

# -----------------------------------------------------------------------------
# 3) Winner test panel text/buttons.
# -----------------------------------------------------------------------------
old_panel = r'''    if (page == Panel::WINNER_TEST) {
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
'''
new_panel = r'''    if (page == Panel::WINNER_TEST) {
        ctx->Draw()->SetFontScale(0.33f, 0.33f);
        ctx->Draw()->DrawText(
            font,
            "WINNER VISUAL V2 LAB | Web Winner V5 van la fallback LIVE",
            panel.x + panel.w * 0.5f,
            panel.y + 76.0f,
            0xFFBFD0E0,
            ALIGN_HCENTER | FLAG_DYNAMIC_ASCII
        );
        const char *winnerTests[5] = {
            "TEST FULL FLOW - P1 / TINA",
            "TEST FULL FLOW - P2 / EHBUDDEN",
            "TEST LOCKED IN - 10 KRATOS",
            "TEST TIME OUT - GAME RANDOM",
            "CANCEL NATIVE WINNER"
        };
        for (int i = 0; i < 5; ++i) {
            uint32_t bg = 0xDD674A28;
            if (i == 2) bg = 0xDD315A44;
            if (i == 3) bg = 0xDD6A5425;
            if (i == 4) bg = 0xDD74343E;
            DrawSCBDLayerButton(ctx, font, WinnerButtonRect(i, sw, sh), winnerTests[i], bg);
        }
    }
'''
debug_text = replace_once(debug_text, old_panel, new_panel, "upgrade Winner V2 test panel")
debug_text = replace_once(
    debug_text,
    'page == Panel::WINNER_TEST ? "NATIVE WINNER TEST" :',
    'page == Panel::WINNER_TEST ? "WINNER V2 LAB" :',
    "rename Winner test page",
)

# -----------------------------------------------------------------------------
# 4) Premium Winner Visual V2 renderer.
# -----------------------------------------------------------------------------
renderer_v2 = r'''static void DrawSCBDWinnerPortraitGrid(
    UIContext *ctx,
    FontID font,
    float x,
    float y,
    float w,
    float h,
    int selectedId
) {
    static const char *kCharacters[28] = {
        "ALGOL","AMY","ASTAROTH","CASSANDRA","CERVANTES","DAMPIERRE","HILDE",
        "IVY","KILIK","KRATOS","LIZARDMAN","MAXI","MITSURUGI","NIGHTMARE",
        "RAPHAEL","ROCK","SEONG_MI_NA","SETSUKA","SIEGFRIED","SOPHITIA","TAKI",
        "TALIM","TIRA","VOLDO","XIANGHUA","YOSHIMITSU","YUN_SEONG","ZASALAMEL"
    };
    constexpr int kCols = 14;
    constexpr int kRows = 2;
    const float gap = 3.0f;
    const float tileW = (w - gap * (kCols - 1)) / static_cast<float>(kCols);
    const float tileH = (h - gap) / static_cast<float>(kRows);

    for (int i = 0; i < 28; ++i) {
        const int col = i % kCols;
        const int row = i / kCols;
        const float tx = x + col * (tileW + gap);
        const float ty = y + row * (tileH + gap);
        const bool selected = selectedId == i + 1;

        ctx->Flush();
        ctx->BeginNoTex();
        if (selected) {
            ctx->Draw()->Rect(tx - 3.0f, ty - 3.0f, tileW + 6.0f, tileH + 6.0f, 0xFFFFC447);
            ctx->Draw()->Rect(tx - 1.0f, ty - 1.0f, tileW + 2.0f, tileH + 2.0f, 0xFF6A4510);
        } else {
            ctx->Draw()->Rect(tx - 1.0f, ty - 1.0f, tileW + 2.0f, tileH + 2.0f, 0xA06B542B);
        }
        ctx->Flush();
        ctx->Begin();
        ctx->BindFontTexture();

        DrawSCBDCharacterPortraitSlot(
            ctx,
            font,
            kCharacters[i],
            i,
            tx,
            ty,
            tileW,
            std::max(18.0f, tileH - 14.0f)
        );

        char num[8];
        std::snprintf(num, sizeof(num), "%d", i + 1);
        ctx->Draw()->SetFontScale(0.20f, 0.20f);
        ctx->Draw()->DrawText(
            font,
            num,
            tx + tileW * 0.5f,
            ty + tileH - 6.0f,
            selected ? 0xFFFFD86A : 0xFFFFFFFF,
            ALIGN_CENTER | FLAG_DYNAMIC_ASCII
        );
    }
}

static void DrawSCBDWinnerCountdown(
    UIContext *ctx,
    FontID font,
    float cx,
    float cy,
    int remainingMs
) {
    static const float dx[16] = {
        0.0f, 0.383f, 0.707f, 0.924f, 1.0f, 0.924f, 0.707f, 0.383f,
        0.0f,-0.383f,-0.707f,-0.924f,-1.0f,-0.924f,-0.707f,-0.383f
    };
    static const float dy[16] = {
       -1.0f,-0.924f,-0.707f,-0.383f, 0.0f, 0.383f, 0.707f, 0.924f,
        1.0f, 0.924f, 0.707f, 0.383f, 0.0f,-0.383f,-0.707f,-0.924f
    };
    const float fraction = std::clamp(
        static_cast<float>(remainingMs) / static_cast<float>(SCBDNativeWinner::kPickTimeoutMs),
        0.0f,
        1.0f
    );
    const int lit = static_cast<int>(fraction * 16.0f + 0.5f);
    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->FillCircle(cx, cy, 43.0f, 40, 0xCC111319);
    for (int i = 0; i < 16; ++i) {
        const uint32_t c = i < lit ? 0xFFFFC447 : 0x665A4A2A;
        ctx->Draw()->FillCircle(cx + dx[i] * 52.0f, cy + dy[i] * 52.0f, 4.3f, 16, c);
    }
    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();
    const int tenths = std::max(0, remainingMs / 100);
    char timer[32];
    std::snprintf(timer, sizeof(timer), "%d.%ds", tenths / 10, tenths % 10);
    ctx->Draw()->SetFontScale(0.50f, 0.50f);
    ctx->Draw()->DrawText(font, timer, cx, cy, remainingMs <= 5000 ? 0xFFFFB15B : 0xFFFFE2A0, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
}

static void DrawSCBDNativeWinnerLayer(UIContext *ctx, FontID font, const Bounds &bounds) {
    const SCBDNativeWinner::Snapshot s = SCBDNativeWinner::Read();
    if (s.phase == SCBDNativeWinner::Phase::NONE)
        return;

    const uint32_t teamColor = s.team == 2 ? 0xE05B365F : 0xE02E6D43;
    const uint32_t teamGlow = s.team == 2 ? 0xFFDB6A7F : 0xFF62D675;
    const char initial[2] = {s.username.empty() ? '?' : s.username[0], '\0'};

    // Dim gameplay while keeping fighters + Top5 visible beneath the modal.
    ctx->Flush();
    ctx->BeginNoTex();
    ctx->Draw()->Rect(bounds.x, bounds.y, bounds.w, bounds.h, 0x98000000);
    ctx->Flush();

    if (s.phase == SCBDNativeWinner::Phase::WINNER) {
        const float progress = std::clamp(
            1.0f - static_cast<float>(s.remainingMs) / static_cast<float>(SCBDNativeWinner::kWinnerIntroMs),
            0.0f,
            1.0f
        );
        const float bannerW = std::min(bounds.w * 0.82f, 1040.0f);
        const float bannerH = std::min(bounds.h * 0.54f, 390.0f);
        const float x = bounds.x + (bounds.w - bannerW) * 0.5f;
        const float y = bounds.y + (bounds.h - bannerH) * 0.5f;
        const float cx = x + bannerW * 0.5f;
        const float sweepX = x + 30.0f + (bannerW - 60.0f) * progress;

        ctx->BeginNoTex();
        ctx->Draw()->Rect(x - 5.0f, y - 5.0f, bannerW + 10.0f, bannerH + 10.0f, 0xD9C08A28);
        ctx->Draw()->Rect(x, y, bannerW, bannerH, 0xF21B1712);
        ctx->Draw()->Rect(x + 12.0f, y + 12.0f, bannerW - 24.0f, 7.0f, 0xCCFFC95A);
        ctx->Draw()->Rect(x + 26.0f, y + 92.0f, bannerW - 52.0f, 124.0f, teamColor);
        ctx->Draw()->Rect(sweepX - 7.0f, y + 74.0f, 14.0f, 170.0f, 0xAAFFE49B);
        ctx->Flush();
        ctx->Begin();
        ctx->BindFontTexture();

        char victory[64];
        std::snprintf(victory, sizeof(victory), "P%d VICTORY", s.team);
        ctx->Draw()->SetFontScale(0.92f, 0.92f);
        ctx->Draw()->DrawText(font, victory, cx, y + 148.0f, 0xFFFFD86A, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->SetFontScale(0.42f, 0.42f);
        ctx->Draw()->DrawText(font, "TOP 1 WINNER", cx, y + 236.0f, 0xFFFFE9B0, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);

        const float avatarX = cx - 98.0f;
        const float avatarY = y + 304.0f;
        ctx->Flush();
        ctx->BeginNoTex();
        ctx->Draw()->FillCircle(avatarX, avatarY, 42.0f, 40, 0xFFB9822C);
        ctx->Draw()->FillCircle(avatarX, avatarY, 38.0f, 40, teamColor);
        ctx->Flush();
        ctx->Begin();
        ctx->BindFontTexture();
        ctx->Draw()->SetFontScale(0.54f, 0.54f);
        ctx->Draw()->DrawText(font, initial, avatarX, avatarY, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
        char user[128];
        std::snprintf(user, sizeof(user), "@%s", s.username.c_str());
        ctx->Draw()->SetFontScale(0.58f, 0.58f);
        ctx->Draw()->DrawText(font, user, avatarX + 66.0f, avatarY, 0xFFFFE3A1, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
    } else if (s.phase == SCBDNativeWinner::Phase::PICK) {
        const float cardW = std::min(bounds.w * 0.88f, 1080.0f);
        const float cardH = std::min(bounds.h * 0.84f, 635.0f);
        const float x = bounds.x + (bounds.w - cardW) * 0.5f;
        const float y = bounds.y + (bounds.h - cardH) * 0.5f;
        const float cx = x + cardW * 0.5f;

        ctx->BeginNoTex();
        ctx->Draw()->Rect(x - 4.0f, y - 4.0f, cardW + 8.0f, cardH + 8.0f, 0xD9C08A28);
        ctx->Draw()->Rect(x, y, cardW, cardH, 0xF51A1714);
        ctx->Draw()->Rect(x, y, cardW, 65.0f, 0xF42A2119);
        ctx->Draw()->Rect(x + 22.0f, y + 78.0f, cardW - 44.0f, 156.0f, 0xB7241D17);
        ctx->Flush();
        ctx->Begin();
        ctx->BindFontTexture();

        ctx->Draw()->SetFontScale(0.62f, 0.62f);
        ctx->Draw()->DrawText(font, "TOP 1 WINNER", cx, y + 34.0f, 0xFFFFD86A, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);

        const float avatarX = x + 104.0f;
        const float avatarY = y + 156.0f;
        ctx->Flush();
        ctx->BeginNoTex();
        ctx->Draw()->FillCircle(avatarX, avatarY, 57.0f, 44, 0xFFB9822C);
        ctx->Draw()->FillCircle(avatarX, avatarY, 52.0f, 44, teamColor);
        ctx->Draw()->FillCircle(avatarX, avatarY + 50.0f, 15.0f, 24, 0xFF31210E);
        ctx->Flush();
        ctx->Begin();
        ctx->BindFontTexture();
        ctx->Draw()->SetFontScale(0.68f, 0.68f);
        ctx->Draw()->DrawText(font, initial, avatarX, avatarY, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->SetFontScale(0.25f, 0.25f);
        ctx->Draw()->DrawText(font, "#1", avatarX, avatarY + 50.0f, 0xFFFFD86A, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);

        char user[128];
        std::snprintf(user, sizeof(user), "@%s", s.username.c_str());
        ctx->Draw()->SetFontScale(0.55f, 0.55f);
        ctx->Draw()->DrawText(font, user, x + 188.0f, y + 126.0f, 0xFFFFFFFF, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
        char team[64];
        std::snprintf(team, sizeof(team), "TEAM P%d", s.team);
        ctx->Draw()->SetFontScale(0.32f, 0.32f);
        ctx->Draw()->DrawText(font, team, x + 188.0f, y + 166.0f, teamGlow, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);
        char score[64];
        std::snprintf(score, sizeof(score), "SCORE  %d", s.score);
        ctx->Draw()->SetFontScale(0.34f, 0.34f);
        ctx->Draw()->DrawText(font, score, x + 188.0f, y + 202.0f, 0xFFFFD86A, ALIGN_VCENTER | FLAG_DYNAMIC_ASCII);

        ctx->Draw()->SetFontScale(0.40f, 0.40f);
        ctx->Draw()->DrawText(font, "BAN DUOC QUYEN CHON NHAN VAT TRAN TIEP THEO", cx, y + 272.0f, 0xFFFFE5AF, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->SetFontScale(0.50f, 0.50f);
        ctx->Draw()->DrawText(font, "/pick 1-28", cx, y + 316.0f, 0xFFFFFFFF, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);

        DrawSCBDWinnerCountdown(ctx, font, cx, y + 385.0f, s.remainingMs);

        const float gridX = x + 26.0f;
        const float gridY = y + cardH - 128.0f;
        const float gridW = cardW - 52.0f;
        DrawSCBDWinnerPortraitGrid(ctx, font, gridX, gridY, gridW, 102.0f, 0);
    } else if (s.phase == SCBDNativeWinner::Phase::PICK_SUCCESS) {
        const float cardW = std::min(bounds.w * 0.78f, 920.0f);
        const float cardH = std::min(bounds.h * 0.78f, 570.0f);
        const float x = bounds.x + (bounds.w - cardW) * 0.5f;
        const float y = bounds.y + (bounds.h - cardH) * 0.5f;
        const float cx = x + cardW * 0.5f;

        ctx->BeginNoTex();
        ctx->Draw()->Rect(x - 5.0f, y - 5.0f, cardW + 10.0f, cardH + 10.0f, 0xE0C99132);
        ctx->Draw()->Rect(x, y, cardW, cardH, 0xF4191612);
        ctx->Draw()->Rect(x + 18.0f, y + 18.0f, cardW - 36.0f, 66.0f, 0xD93A2B17);
        ctx->Flush();
        ctx->Begin();
        ctx->BindFontTexture();
        ctx->Draw()->SetFontScale(0.76f, 0.76f);
        ctx->Draw()->DrawText(font, "LOCKED IN", cx, y + 51.0f, 0xFFFFD86A, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);

        const int atlasIndex = SCBDWinnerCharacterAtlasIndex(s.character, s.characterId);
        const float portraitW = std::min(280.0f, cardW * 0.34f);
        const float portraitH = 255.0f;
        const float portraitX = cx - portraitW * 0.5f;
        const float portraitY = y + 105.0f;

        ctx->Flush();
        ctx->BeginNoTex();
        ctx->Draw()->Rect(portraitX - 7.0f, portraitY - 7.0f, portraitW + 14.0f, portraitH + 14.0f, 0xFFFFC447);
        ctx->Draw()->FillCircle(portraitX - 18.0f, portraitY + 20.0f, 4.0f, 16, 0xFFFFC447);
        ctx->Draw()->FillCircle(portraitX + portraitW + 22.0f, portraitY + 56.0f, 5.0f, 16, 0xFFFFE2A0);
        ctx->Draw()->FillCircle(portraitX - 26.0f, portraitY + 145.0f, 3.0f, 16, 0xFFFFE2A0);
        ctx->Draw()->FillCircle(portraitX + portraitW + 18.0f, portraitY + 190.0f, 4.0f, 16, 0xFFFFC447);
        ctx->Flush();
        ctx->Begin();
        ctx->BindFontTexture();
        DrawSCBDCharacterPortraitSlot(ctx, font, s.character.c_str(), atlasIndex, portraitX, portraitY, portraitW, portraitH);

        ctx->Draw()->SetFontScale(0.62f, 0.62f);
        ctx->Draw()->DrawText(font, s.character.c_str(), cx, y + 392.0f, 0xFFFFD86A, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
        char picked[192];
        std::snprintf(picked, sizeof(picked), "Picked by @%s  |  TEAM P%d", s.username.c_str(), s.team);
        ctx->Draw()->SetFontScale(0.32f, 0.32f);
        ctx->Draw()->DrawText(font, picked, cx, y + 426.0f, 0xFFFFFFFF, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);

        const float gridX = x + 24.0f;
        const float gridY = y + cardH - 105.0f;
        DrawSCBDWinnerPortraitGrid(ctx, font, gridX, gridY, cardW - 48.0f, 82.0f, s.characterId);
    } else if (s.phase == SCBDNativeWinner::Phase::TIMEOUT) {
        const float cardW = std::min(bounds.w * 0.60f, 720.0f);
        const float cardH = std::min(bounds.h * 0.54f, 390.0f);
        const float x = bounds.x + (bounds.w - cardW) * 0.5f;
        const float y = bounds.y + (bounds.h - cardH) * 0.5f;
        const float cx = x + cardW * 0.5f;

        ctx->BeginNoTex();
        ctx->Draw()->Rect(x - 5.0f, y - 5.0f, cardW + 10.0f, cardH + 10.0f, 0xD8B78335);
        ctx->Draw()->Rect(x, y, cardW, cardH, 0xF21A1714);
        ctx->Draw()->Rect(x + 18.0f, y + 18.0f, cardW - 36.0f, 64.0f, 0xD945321D);
        ctx->Draw()->FillCircle(cx, y + 205.0f, 67.0f, 48, 0xFF2B251D);
        ctx->Draw()->FillCircle(cx, y + 205.0f, 61.0f, 48, 0xFF6A542D);
        ctx->Flush();
        ctx->Begin();
        ctx->BindFontTexture();

        ctx->Draw()->SetFontScale(0.70f, 0.70f);
        ctx->Draw()->DrawText(font, "TIME OUT", cx, y + 50.0f, 0xFFFFD86A, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->SetFontScale(1.08f, 1.08f);
        ctx->Draw()->DrawText(font, "?", cx, y + 205.0f, 0xFFFFFFFF, ALIGN_CENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->SetFontScale(0.55f, 0.55f);
        ctx->Draw()->DrawText(font, "GAME RANDOM", cx, y + 302.0f, 0xFFFFE2A0, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
        ctx->Draw()->SetFontScale(0.29f, 0.29f);
        ctx->Draw()->DrawText(font, "SOULCALIBUR TU CHON NHAN VAT - APK KHONG QUYET DINH KET QUA", cx, y + 344.0f, 0xFFBFD0E0, ALIGN_HCENTER | FLAG_DYNAMIC_ASCII);
    }

    ctx->Draw()->SetFontScale(1.0f, 1.0f);
    ctx->Flush();
    ctx->RebindTexture();
}

'''
debug_text = replace_between(
    debug_text,
    "static void DrawSCBDNativeWinnerLayer(",
    "static void DrawSCBDBoneMapper(",
    renderer_v2,
    "replace native Winner V1 renderer with Winner Visual V2",
)
debug.write_text(debug_text, encoding="utf-8")

# -----------------------------------------------------------------------------
# 5) Final fail-fast checks.
# -----------------------------------------------------------------------------
winner_final = winner.read_text(encoding="utf-8")
debug_final = debug.read_text(encoding="utf-8")
emu_final = emu.read_text(encoding="utf-8")

required = (
    (winner_final, "kWinnerIntroMs = 2200"),
    (winner_final, "kPickTimeoutMs = 15000"),
    (winner_final, "Visual only. The overlay does NOT pick a random fighter."),
    (emu_final, 'ShowPickSuccess(10, "KRATOS")'),
    (emu_final, "SCBDNativeWinner::ShowTimeout();"),
    (debug_final, "P1 VICTORY" if False else "P%d VICTORY"),
    (debug_final, "TOP 1 WINNER"),
    (debug_final, "DrawSCBDWinnerCountdown"),
    (debug_final, "DrawSCBDWinnerPortraitGrid"),
    (debug_final, "LOCKED IN"),
    (debug_final, "GAME RANDOM"),
    (debug_final, "APK KHONG QUYET DINH KET QUA"),
    (debug_final, "WINNER VISUAL V2 LAB"),
    (debug_final, "TEST TIME OUT - GAME RANDOM"),
)
for text, marker in required:
    if marker not in text:
        raise SystemExit(f"V0.5.7A generated source missing marker: {marker}")

for forbidden in (
    "RANDOM 30",
    'ShowPickSuccess(14, "KRATOS")',
    "PICK THANH CONG!",
):
    if forbidden in debug_final or forbidden in emu_final:
        raise SystemExit(f"V0.5.7A forbidden legacy marker survived: {forbidden}")

# Frozen functionality must remain present.
for marker in (
    "SCBDVirtualInput::Process();",
    "DrawSCBDMatchTop5HUD",
    "SCBD_LEGACY_MEMORY_INSPECTOR_VISIBLE = false",
    "kSCBDRankFrameTuning[7]",
    "radius * 0.78f",
):
    if marker not in debug_final:
        raise SystemExit(f"V0.5.7A regression: stable marker missing: {marker}")

with info.open("a", encoding="utf-8") as f:
    f.write(
        "\nPSP Live FloGB V0.5.7A Native Winner Visual V2\n"
        "Winner Intro: cinematic P1/P2 VICTORY + Top1 reveal, 2.2 seconds\n"
        "Pick Phase: Top1 card + team/score + /pick 1-28 + segmented 15-second countdown\n"
        "Pick grid: 28 existing SCBD character portraits shown inside native APK layer\n"
        "Locked In: selected portrait + selected slot + picker/team presentation\n"
        "Timeout: TIME OUT -> GAME RANDOM only; overlay NEVER chooses the random result\n"
        "Random result remains owned by Soulcalibur/existing Random selection controller\n"
        "KRATOS test slot corrected from legacy 14 to atlas slot 10\n"
        "Input Core V1 and V0.5.6 ranking/HUD visuals preserved unchanged\n"
        "Web Winner V5 remains the live fallback; bridge cutover is not part of V0.5.7A\n"
    )

print("PSP Live FloGB V0.5.7A Native Winner Visual V2 patch applied successfully.")
