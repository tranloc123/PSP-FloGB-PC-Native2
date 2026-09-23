# FloGB Windows Engine

V1.1.0 đã chuẩn bị vị trí `engine/PPSSPPWindows64.exe` để PSP FloGB ưu tiên chạy engine tích hợp.

Nếu file này tồn tại, app tự dùng nó và bỏ qua PPSSPP path bên ngoài.
Nếu chưa tồn tại, app chạy chế độ COMPAT với một PPSSPPWindows64.exe do người dùng chọn để test Combat Core trước.

Mục tiêu port native là đưa các thay đổi PPSSPP Android của PSP Live FloGB V0.5.9E sang Windows build để UI native/HUD APK trở thành một phần của engine Windows, không cần overlay Electron cho các menu cuối cùng.

Tham chiếu patch Android nằm ở `port_reference/apply_psp_live_flogb_v0_5_8c_android_reference.py`.
