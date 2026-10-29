# 予定チェッカーを、Windowsにログオンしたとき自動で起動するように登録する
#   - バックエンド: タスクスケジューラ（画面なしで常駐。朝のまとめもここで作られる）
#   - ウィジェット: スタートアップにショートカットを置く
# 使い方: PowerShell で  powershell -ExecutionPolicy Bypass -File register_autostart.ps1
# 解除:   powershell -ExecutionPolicy Bypass -File register_autostart.ps1 -Remove

param(
    [switch]$Remove,
    [string]$AppPath = ""
)

$ErrorActionPreference = "Stop"
$TaskName = "ScheduleChecker Backend"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Pythonw = Join-Path $Backend ".venv\Scripts\pythonw.exe"
$Startup = [Environment]::GetFolderPath("Startup")
$Shortcut = Join-Path $Startup "予定チェッカー.lnk"

if ($Remove) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $Shortcut -ErrorAction SilentlyContinue
    Write-Host "自動起動の登録を解除しました。"
    exit 0
}

if (-not (Test-Path $Pythonw)) {
    Write-Host "先に backend\setup_backend.bat を実行してください。" -ForegroundColor Red
    exit 1
}

# バックエンド（ログオン時、画面なしで起動。止まったら1分後に再起動）
$action = New-ScheduledTaskAction -Execute $Pythonw -Argument "-m app" -WorkingDirectory $Backend
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "予定チェッカーのバックエンド（127.0.0.1:8765）" -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "バックエンドを登録し、起動しました。"

# ウィジェット（インストール先を探してスタートアップに置く）
if (-not $AppPath) {
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "ScheduleChecker\ScheduleChecker.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\ScheduleChecker\ScheduleChecker.exe"),
        (Join-Path $Root "frontend\src-tauri\target\release\ScheduleChecker.exe")
    )
    $AppPath = $candidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if ($AppPath -and (Test-Path $AppPath)) {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($Shortcut)
    $lnk.TargetPath = $AppPath
    $lnk.WorkingDirectory = Split-Path -Parent $AppPath
    $lnk.Save()
    Write-Host "ウィジェットをスタートアップに登録しました: $AppPath"
} else {
    Write-Host "ウィジェットのアプリが見つかりませんでした。インストール後に -AppPath でexeの場所を指定して再実行してください。" -ForegroundColor Yellow
}
