from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_5_3.py <ppsspp_repo>")

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
    "DrawSCBDCharacterPortraitSlot",
    "kSCBDCharacterColors[28]",
    "Approved Top Character layout",
    "DrawSCBDRankAvatar",
    "DrawSCBDMatchTop5HUD",
):
    if marker not in s:
        raise SystemExit(f"V0.5.2 prerequisite missing: {marker}")

include_anchor = '#include "Common/Render/DrawBuffer.h"\n'
if '#include "Common/Render/ManagedTexture.h"\n' not in s:
    s = replace_once(
        s,
        include_anchor,
        include_anchor + '#include "Common/Render/ManagedTexture.h"\n',
        "add ManagedTexture include",
    )

new_portrait_renderer = r"""static Draw::Texture *g_scbdCharacterPortraitAtlas = nullptr;
static bool g_scbdCharacterPortraitAtlasAttempted = false;

static Draw::Texture *GetSCBDCharacterPortraitAtlas(UIContext *ctx) {
    if (!g_scbdCharacterPortraitAtlas && !g_scbdCharacterPortraitAtlasAttempted) {
        g_scbdCharacterPortraitAtlasAttempted = true;
        g_scbdCharacterPortraitAtlas = CreateTextureFromFile(
            ctx->GetDrawContext(),
            "scbd/characters/character_portraits_atlas.png",
            ImageFileType::PNG,
            false,
            2048,
            1024
        );
    }
    return g_scbdCharacterPortraitAtlas;
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
    ctx->Draw()->Rect(x - 2.0f, y - 2.0f, w + 4.0f, h + 4.0f, 0xB0000000);
    ctx->Draw()->Rect(x - 1.0f, y - 1.0f, w + 2.0f, h + 2.0f, 0xFFE2B657);
    ctx->Draw()->Rect(x, y, w, h, 0xFF151515);
    ctx->Flush();

    Draw::Texture *atlas = GetSCBDCharacterPortraitAtlas(ctx);
    if (atlas) {
        constexpr int kCols = 7;
        constexpr int kRows = 4;
        const int safeIndex = std::clamp(index, 0, 27);
        const int col = safeIndex % kCols;
        const int row = safeIndex / kCols;
        const float u1 = static_cast<float>(col) / static_cast<float>(kCols);
        const float v1 = static_cast<float>(row) / static_cast<float>(kRows);
        const float u2 = static_cast<float>(col + 1) / static_cast<float>(kCols);
        const float v2 = static_cast<float>(row + 1) / static_cast<float>(kRows);

        ctx->Begin();
        ctx->GetDrawContext()->BindTexture(0, atlas);
        ctx->Draw()->DrawTexRect(
            x, y, x + w, y + h,
            u1, v1, u2, v2,
            0xFFFFFFFF
        );
        ctx->Flush();
        ctx->RebindTexture();
        ctx->BindFontTexture();
        return;
    }

    ctx->BeginNoTex();
    ctx->Draw()->Rect(x, y, w, h, kSCBDCharacterColors[index % 28]);
    ctx->Flush();
    ctx->Begin();
    ctx->BindFontTexture();
    char shortName[3] = {
        character[0],
        character[1] ? character[1] : '\0',
        '\0'
    };
    ctx->Draw()->SetFontScale(0.30f, 0.30f);
    ctx->Draw()->DrawText(
        font,
        shortName,
        x + w * 0.5f,
        y + h * 0.5f,
        0xFFFFFFFF,
        ALIGN_CENTER | FLAG_DYNAMIC_ASCII
    );
}

"""

s = replace_between(
    s,
    "static void DrawSCBDCharacterPortraitSlot(\n",
    "static void DrawSCBDInGameLayer(",
    new_portrait_renderer,
    "replace placeholder character portrait renderer",
)

s = replace_once(
    s,
    "                const float portraitW = 38.0f;\n",
    "                const float portraitW = 56.0f;\n",
    "increase character portrait width",
)

s = replace_once(
    s,
    "                const float usersStart = list.x + std::min(250.0f, list.w * 0.31f);\n",
    "                const float usersStart = list.x + std::min(275.0f, list.w * 0.34f);\n",
    "move viewer columns after larger character portrait",
)

for required in (
    "character_portraits_atlas.png",
    "CreateTextureFromFile(",
    "DrawTexRect(",
    "constexpr int kCols = 7;",
    "const float portraitW = 56.0f;",
):
    if required not in s:
        raise SystemExit(f"V0.5.3 generated source missing: {required}")

debug.write_text(s, encoding="utf-8")

with info.open("a", encoding="utf-8") as f:
    f.write(
        "\nPSP Live FloGB V0.5.3 Character Portrait Integration\n"
        "Top Character: 28 portrait assets replace colored initial boxes\n"
        "Asset system: one 7x4 texture atlas for low texture-switch overhead\n"
        "Atlas path: assets/scbd/characters/character_portraits_atlas.png\n"
        "Portrait layout: wider gold-framed portrait tile + character name\n"
        "Viewer avatar system remains mock-only in this version\n"
        "V0.5.1 transparent battle Top5 and V0.5.2 ranking layouts preserved\n"
    )

print("PSP Live FloGB V0.5.3 Character Portrait Integration patch applied successfully.")
