from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("Usage: apply_psp_live_flogb_v0_4_1.py <ppsspp_repo>")

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

# V0.4 must already be applied.
bone = require("SCBD/SCBDBoneMapper.h")
s = bone.read_text(encoding="utf-8")

old_constants = '''// Static EBOOT global fighter-pointer VAs:
//   P1 = *[0x00004A28]
//   P2 = *[0x00004A2C]
inline constexpr u32 kP1FighterPtrAddress = kModuleBase + 0x00004A28;
inline constexpr u32 kP2FighterPtrAddress = kModuleBase + 0x00004A2C;
'''

new_constants = '''// ULUS-10457 PRX relocation result:
// References to 0x4A28/0x4A2C use HI16 relocation info 0x00010005,
// meaning the low offsets are relative to LOAD[1] (DATA), whose VA is 0x003B5000.
// Therefore the runtime global-pointer storage locations are:
//   P1 = 0x08804000 + 0x003B5000 + 0x00004A28 = 0x08BBDA28
//   P2 = 0x08804000 + 0x003B5000 + 0x00004A2C = 0x08BBDA2C
inline constexpr u32 kDataLoadVA = 0x003B5000;
inline constexpr u32 kP1FighterPtrAddress =
    kModuleBase + kDataLoadVA + 0x00004A28;
inline constexpr u32 kP2FighterPtrAddress =
    kModuleBase + kDataLoadVA + 0x00004A2C;

// The DATA relocation entries at offsets 0x4A28/0x4A2C point into LOAD[1]:
//   0x19140 -> P1 fighter 0x08BD2140
//   0x2FE00 -> P2 fighter 0x08BE8E00
// Their difference is exactly the known fighter stride 0x16CC0.
// Known HP addresses independently validate fighter + 0x1150C:
//   0x08BD2140 + 0x1150C = 0x08BE364C
//   0x08BE8E00 + 0x1150C = 0x08BFA30C
inline constexpr u32 kExpectedP1Fighter = 0x08BD2140;
inline constexpr u32 kExpectedP2Fighter = 0x08BE8E00;
'''

s = replace_once(
    s,
    old_constants,
    new_constants,
    "SCBDBoneMapper fighter globals",
)
bone.write_text(s, encoding="utf-8")

info = require("PSP_LIVE_FLOGB_BUILD_INFO.txt")
info.write_text(
    "PSP Live FloGB V0.4.1 Fighter Pointer Hotfix\\n"
    "Target: Soulcalibur Broken Destiny ULUS-10457\\n"
    "Package: com.scbd.vieweremulator\\n"
    "Base: V0.3 Inspector + V0.4 Bone Mapper preserved\\n"
    "Corrected global pointer storage: P1@08BBDA28 P2@08BBDA2C\\n"
    "Expected fighter objects: P1@08BD2140 P2@08BE8E00 stride 00016CC0\\n"
    "HP cross-check: fighter+1150C -> 08BE364C / 08BFA30C\\n"
    "Bone layout unchanged: fighter+2B4 -> array, stride 40h, XYZ +30/+34/+38\\n"
    "Camera hook unchanged from V0.4\\n",
    encoding="utf-8",
)

print("PSP Live FloGB V0.4.1 fighter-pointer hotfix applied successfully.")
