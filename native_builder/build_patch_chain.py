name: Build PSP FloGB Native Unified V1.2.0 Windows

on:
  workflow_dispatch:

permissions:
  contents: read

env:
  PPSSPP_COMMIT: 03bb3e20fed8cbea4901c774a3245bc3fc2c0de0
  BUILD_CONFIGURATION: Release

jobs:
  build:
    name: Native engine + Unified EXE x64
    runs-on: windows-latest
    timeout-minutes: 150

    steps:
      - name: Checkout PSP FloGB source
        uses: actions/checkout@v7

      - name: Setup Python
        uses: actions/setup-python@v6
        with:
          python-version: '3.13'

      - name: Setup Node.js
        uses: actions/setup-node@v6
        with:
          node-version: '22'

      - name: Add MSBuild to PATH
        uses: microsoft/setup-msbuild@v3

      - name: Install native patch dependencies
        shell: pwsh
        run: python -m pip install --disable-pip-version-check pillow numpy

      - name: Clone pinned PPSSPP source
        shell: pwsh
        run: |
          if (Test-Path ppsspp) { Remove-Item -Recurse -Force ppsspp }
          git clone https://github.com/hrydgard/ppsspp.git ppsspp
          Set-Location ppsspp
          git checkout "$env:PPSSPP_COMMIT"
          git submodule update --init --recursive

      - name: Replay proven PSP FloGB APK patch chain
        shell: pwsh
        run: python native_builder/build_patch_chain.py ppsspp

      - name: Native source preflight
        shell: pwsh
        run: |
          $debug = Get-Content ppsspp/UI/DebugOverlay.cpp -Raw
          $bridge = Get-Content ppsspp/SCBD/SCBDNativeLiveBridge.h -Raw
          $winner = Get-Content ppsspp/SCBD/SCBDNativeWinner.h -Raw
          @(
            'SCBDVirtualInput::Process();',
            'DrawSCBDMatchTop5HUD',
            'WINNER FINAL V0.5.8C',
            'SCBDNativeLiveBridge::Process();',
            'DrawSCBDFinalHeroPortraitV059C'
          ) | ForEach-Object {
            if (-not $debug.Contains($_)) {
              throw "Missing source marker: $_"
            }
          }
          if (-not $bridge.Contains('WSAStartup')) {
            throw 'Windows Winsock bridge patch missing'
          }
          if (-not $winner.Contains('BeginWinnerPick')) {
            throw 'Winner/Pick core missing'
          }
          if ($debug.Contains('DrawTextW(')) {
            throw 'Windows incompatible DrawTextW survived patch chain'
          }
          if (-not $debug.Contains('#undef DrawText')) {
            throw 'Windows DrawText macro guard missing'
          }
          Write-Host 'Native source preflight PASS'

      - name: Stamp native Windows engine version
        shell: pwsh
        run: |
          @'
          const char *PPSSPP_GIT_VERSION = "PSP-FloGB-Native-Unified-1.2.0";
          #define PPSSPP_GIT_VERSION_NO_UPDATE 1
          '@ | Set-Content -Encoding ascii ppsspp/git-version.cpp

          @'
          #define PPSSPP_WIN_VERSION_STRING "1.20.4-FloGB-1.2.0"
          #define PPSSPP_WIN_VERSION_COMMA 1,20,4,120
          #define PPSSPP_WIN_VERSION_NO_UPDATE 1
          '@ | Set-Content -Encoding ascii ppsspp/Windows/win-version.h

      - name: Build PSP FloGB native emulator x64
        shell: pwsh
        run: msbuild ppsspp/Windows/PPSSPP.sln /m /p:TrackFileAccess=false /p:Configuration=$env:BUILD_CONFIGURATION /p:Platform=x64

      - name: Install native engine into Unified app
        shell: pwsh
        run: |
          if (Test-Path engine) { Remove-Item -Recurse -Force engine }
          New-Item -ItemType Directory -Force engine | Out-Null
          $exe = Get-ChildItem -Path ppsspp -Filter PPSSPPWindows64.exe -File -Recurse | Select-Object -First 1
          if (-not $exe) {
            throw 'PPSSPPWindows64.exe was not produced'
          }
          Copy-Item $exe.FullName engine/PPSSPPWindows64.exe
          Copy-Item -Recurse ppsspp/assets engine/assets
          @"
          PSP FloGB Native Engine bundled with Unified 1.2.0
          Base commit: $env:PPSSPP_COMMIT
          UDP native bridge: 127.0.0.1:8796
          Debugger: ws://127.0.0.1:9000/debugger
          "@ | Set-Content -Encoding utf8 engine/ENGINE_BUILD_INFO.txt
          if (-not (Test-Path engine/PPSSPPWindows64.exe)) {
            throw 'Engine copy failed'
          }

      - name: Install Electron dependencies
        shell: pwsh
        run: |
          npm config set ignore-scripts false
          npm install --foreground-scripts
          if (-not (Test-Path node_modules/electron/dist/electron.exe)) {
            Write-Host 'Electron binary missing after npm install, running postinstall directly...'
            node node_modules/electron/install.js
          }
          npx electron --version

      - name: Build one PSP FloGB Windows app - no publish
        shell: pwsh
        run: npm run dist -- --publish never

      - name: Verify packaged Native Engine exists
        shell: pwsh
        run: |
          $unpacked = Get-ChildItem -Path dist -Directory -Filter '*unpacked*' | Select-Object -First 1
          if (-not $unpacked) {
            throw 'win-unpacked output is missing'
          }
          $native = Get-ChildItem $unpacked.FullName -Filter PPSSPPWindows64.exe -Recurse |
            Where-Object { $_.FullName -match 'engine' } |
            Select-Object -First 1
          if (-not $native) {
            throw 'Packaged app is missing bundled Native Engine'
          }
          Write-Host "Bundled engine verified: $($native.FullName)"
          Get-ChildItem dist -File | Format-Table Name,Length

      - name: Upload PSP FloGB Native Unified V1.2.0
        uses: actions/upload-artifact@v7
        with:
          name: PSP-FloGB-Native-Unified-V1.2.0-Windows-x64
          path: |
            dist/*.exe
            dist/*unpacked*/**
          if-no-files-found: error
