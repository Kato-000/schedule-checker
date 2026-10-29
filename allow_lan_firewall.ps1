# スマホ用の入口（ポート8766）を、自宅LAN内からだけ受け付けるようにWindowsファイアウォールを設定する
# 管理者として実行: PowerShellを右クリック「管理者として実行」→
#   powershell -ExecutionPolicy Bypass -File allow_lan_firewall.ps1
# 解除: 同じコマンドに -Remove を付ける

param([switch]$Remove)
$ErrorActionPreference = "Stop"
$Name = "ScheduleChecker LAN (8766)"

$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $admin) {
    Write-Host "管理者として実行してください（PowerShellを右クリック →「管理者として実行」）。" -ForegroundColor Red
    exit 1
}

Get-NetFirewallRule -DisplayName $Name -ErrorAction SilentlyContinue | Remove-NetFirewallRule
if ($Remove) {
    Write-Host "ファイアウォールの設定を解除しました。"
    exit 0
}

# 同じネットワーク内（LocalSubnet）から、「プライベート」ネットワークのときだけ許可
New-NetFirewallRule -DisplayName $Name -Direction Inbound -Protocol TCP -LocalPort 8766 `
    -RemoteAddress LocalSubnet -Profile Private -Action Allow | Out-Null
Write-Host "ポート8766を、自宅LAN内（プライベートネットワーク）からだけ許可しました。" -ForegroundColor Green

$profiles = Get-NetConnectionProfile | Select-Object Name, NetworkCategory
$public = $profiles | Where-Object { $_.NetworkCategory -eq "Public" }
if ($public) {
    Write-Host ""
    Write-Host "注意: 次のネットワークが「パブリック」になっているため、このままではスマホから接続できません:" -ForegroundColor Yellow
    $public | ForEach-Object { Write-Host "  $($_.Name)" }
    Write-Host "自宅のネットワークなら、設定 > ネットワークとインターネット > (Wi-Fi/イーサネット) で「プライベート」に変更してください。"
}
