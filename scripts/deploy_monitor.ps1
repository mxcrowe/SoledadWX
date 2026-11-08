# Deploy a freshly built Monitor from the build cache to bin\.
#
# The Monitor runs from bin\soledadwx-ui.exe (both shortcuts point there, with
# "Start in" = soledadwx-ui\src-tauri so it finds its .env). That keeps
# soledadwx-ui\src-tauri\target\ a pure cache: `cargo clean` can wipe it at any
# time without touching the running Monitor (decided 2026-11-08).
#
# One rollback is kept: the previous exe becomes bin\soledadwx-ui.prev.exe.
# A running exe can be renamed but not overwritten, so this works while the
# Monitor runs; Michael then quits it from the tray and relaunches from the
# shortcut. To roll back: quit, swap the two files' names, relaunch.
#
# Usage (PowerShell, after `npx tauri build --no-bundle` in soledadwx-ui):
#   D:\Dev\SoledadWX\scripts\deploy_monitor.ps1

$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$built = Join-Path $root 'soledadwx-ui\src-tauri\target\release\soledadwx-ui.exe'
$bin = Join-Path $root 'bin'
$exe = Join-Path $bin 'soledadwx-ui.exe'
$prev = Join-Path $bin 'soledadwx-ui.prev.exe'

if (-not (Test-Path $built)) { throw "No build at $built. Run: npx tauri build --no-bundle" }
if ((Test-Path $exe) -and ((Get-FileHash $exe).Hash -eq (Get-FileHash $built).Hash)) {
    "bin\ already holds this build; nothing to deploy."
    return
}
New-Item -ItemType Directory -Force $bin | Out-Null
if (Test-Path $exe) {
    # Fails (and stops here) if the old rollback is the one running.
    if (Test-Path $prev) { Remove-Item $prev -Confirm:$false }
    Rename-Item $exe 'soledadwx-ui.prev.exe'
}
Copy-Item $built $exe
"Deployed build of {0} to {1}." -f (Get-Item $built).LastWriteTime, $exe
"Next: quit the Monitor from the tray and relaunch it from the shortcut."
