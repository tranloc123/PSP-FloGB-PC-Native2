from pathlib import Path

patcher = Path(__file__).with_name("apply_psp_live_flogb_v0_5_0.py")
s = patcher.read_text(encoding="utf-8")

start_marker = "controls_start = '        g_scbdHUDButton = root_->Add(\\n'\n"
end_marker = "old_visibility = '''    if (g_scbdHUDButton) {\n"

start = s.find(start_marker)
if start < 0:
    raise SystemExit("V0.5.0 hotfix: controls_start marker not found")

end = s.find(end_marker, start)
if end < 0:
    raise SystemExit("V0.5.0 hotfix: old_visibility marker not found")

replacement = r"""old_controls = r'''        g_scbdHUDButton = root_->Add(
            new Button(
                "RANK PANEL",
                new AnchorLayoutParams(150, 50, NONE, 10, 170, NONE)
            )
        );
        g_scbdHUDButton->SetScale(0.62f);
        g_scbdHUDButton->OnClick.Add([](UI::EventParams &) {
            const bool open = SCBDRankPanelState::ToggleOpen();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                open ? "Bang xep hang OPEN" : "Bang xep hang CLOSED",
                1.5f,
                "scbd_rank_panel_toggle"
            );
        });

        g_scbdRankTestButton = root_->Add(
            new Button(
                "TEST HIEN THI",
                new AnchorLayoutParams(150, 50, NONE, 10, 230, NONE)
            )
        );
        g_scbdRankTestButton->SetScale(0.62f);
        g_scbdRankTestButton->OnClick.Add([](UI::EventParams &) {
            const bool enabled = SCBDRankPanelState::ToggleTestData();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                enabled ? "Mock ranking data ON" : "Mock ranking data OFF",
                1.5f,
                "scbd_rank_test_toggle"
            );
        });

        g_scbdRankNextTabButton = root_->Add(
            new Button(
                "TAB >",
                new AnchorLayoutParams(150, 50, NONE, 10, 290, NONE)
            )
        );
        g_scbdRankNextTabButton->SetScale(0.62f);
        g_scbdRankNextTabButton->OnClick.Add([](UI::EventParams &) {
            const auto tab = SCBDRankPanelState::NextTab();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                SCBDRankPanelState::TabName(tab),
                1.2f,
                "scbd_rank_next_tab"
            );
        });

'''
new_controls = r'''        SCBDNativeHUD::EnsureLoaded();

        g_scbdMatchHUDButton = root_->Add(
            new Button(
                "MATCH HUD",
                new AnchorLayoutParams(150, 50, NONE, 10, 170, NONE)
            )
        );
        g_scbdMatchHUDButton->SetScale(0.62f);
        g_scbdMatchHUDButton->OnClick.Add([](UI::EventParams &) {
            const bool enabled = SCBDNativeHUD::ToggleMatchHud();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                enabled ? "Match Top10 HUD ON" : "Match Top10 HUD OFF",
                1.4f,
                "scbd_match_hud_toggle"
            );
        });

        g_scbdRankMenuButton = root_->Add(
            new Button(
                "RANK MENU",
                new AnchorLayoutParams(150, 50, NONE, 10, 230, NONE)
            )
        );
        g_scbdRankMenuButton->SetScale(0.62f);
        g_scbdRankMenuButton->OnClick.Add([this](UI::EventParams &) {
            screenManager()->push(new SCBDNativeRankScreen());
        });

        g_scbdDevButton = root_->Add(
            new Button(
                "DEV",
                new AnchorLayoutParams(150, 50, NONE, 10, 290, NONE)
            )
        );
        g_scbdDevButton->SetScale(0.62f);
        g_scbdDevButton->OnClick.Add([this](UI::EventParams &) {
            screenManager()->push(new SCBDNativeDevScreen());
        });

        g_scbdNativeTestButton = root_->Add(
            new Button(
                "TEST DATA",
                new AnchorLayoutParams(150, 50, NONE, 10, 350, NONE)
            )
        );
        g_scbdNativeTestButton->SetScale(0.62f);
        g_scbdNativeTestButton->OnClick.Add([](UI::EventParams &) {
            const bool enabled = SCBDNativeHUD::ToggleTestData();
            g_OSD.Show(
                OSDType::MESSAGE_INFO,
                enabled ? "SCBD TEST DATA ON" : "SCBD TEST DATA OFF",
                1.4f,
                "scbd_native_test_toggle"
            );
        });

'''
s = replace_once(
    s,
    old_controls,
    new_controls,
    "replace V0.4.6 ranking controls safely",
)

"""

patched = s[:start] + replacement + s[end:]
patcher.write_text(patched, encoding="utf-8")
print("Patched V0.5.0 control replacement to exact-block mode")
