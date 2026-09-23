# PSP FloGB PC Native Unified V1.2.0

## Khác V1.1.0 ở điểm quan trọng nhất

V1.1.0 vẫn có chế độ fallback sang PPSSPP gốc khi thư mục `engine/` chưa có binary. Vì vậy nó có thể mở đúng cửa sổ PPSSPP v1.20.4 nguyên bản như ảnh test.

**V1.2.0 bỏ fallback hoàn toàn.** Workflow build sẽ:

1. Clone PPSSPP source đúng commit dùng cho nhánh APK.
2. Replay chuỗi patch PSP Live FloGB đã phát triển trên Android.
3. Port Native Live Bridge từ POSIX socket sang Winsock trên Windows.
4. Build `PPSSPPWindows64.exe` đã patch bằng MSVC.
5. Copy engine + toàn bộ asset FloGB vào `engine/`.
6. Build Electron Control Center thành `PSP-FloGB-Native-Unified-1.2.0-x64.exe`.

Kết quả cuối là một gói Windows có **FloGB Native Engine đi kèm**, không yêu cầu tải/chọn PPSSPP gốc.

## Các phần lấy từ baseline APK

- Virtual PSP input.
- Match HUD / BXH native.
- Top 10 P1/P2.
- Rank Menu / Top100 / Top nhân vật / Chuỗi win theo source baseline.
- Winner → Pick UI native.
- `/pick 1..28` + portrait.
- Native UDP bridge `127.0.0.1:8796`.
- TikTok controller bên ngoài engine điều khiển Winner/Pick và game flow.
- Combat controller: anti-heal, HP thật, KO thật, State3/Victory, Outro, clean return, Character Select, P2 Random30.

## Gift Rule

Không tải cả catalog hàng nghìn quà. Quà mới được học khi LIVE nhìn thấy nó. Chỉ quà nào bấm Add Rule mới có action gameplay.

Rule hiện ưu tiên action game, không phải quy đổi điểm:

- PSP input.
- Heal team.
- Damage enemy.
- Set HP.
- Trigger Winner test.
- Video/effect.
- Chuỗi action + delay.

BXH support nội bộ vẫn tồn tại vì Winner Top1 cần dữ liệu ranking, nhưng nó không phải một action cấu hình gift.

## Cách build

Upload toàn bộ source này lên GitHub, giữ nguyên cấu trúc thư mục.

Vào:

`Actions → Build PSP FloGB Native Unified V1.2.0 Windows → Run workflow`

Build đầu có thể lâu vì phải clone + compile PPSSPP native x64.

Artifact cuối:

`PSP-FloGB-Native-Unified-V1.2.0-Windows-x64`

Trong artifact có installer/portable EXE từ `dist/`.

## Test đầu tiên sau build

1. Mở PSP FloGB Native Unified V1.2.0.
2. Chọn ISO Soulcalibur ULUS-10457.
3. Bấm **CHẠY PSP FLOGB NATIVE**.
4. App phải tự mở engine bundled, không có ô chọn PPSSPP ngoài.
5. Kiểm tra `Test-NetConnection 127.0.0.1 -Port 9000`.
6. Trong game kiểm tra Match HUD / Rank Menu / DEV / Winner UI native.
7. Sau khi UI engine PASS mới test anti-heal → KO → Outro → Pick full cycle.

Nếu workflow fail, gửi nguyên log của **step đỏ đầu tiên**. Không cần build đi build lại mù quáng.
