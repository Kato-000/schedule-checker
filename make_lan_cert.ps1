# スマホ（自宅LAN）からHTTPSで開くための証明書を作る（mkcert を使用）
# 使い方: powershell -ExecutionPolicy Bypass -File make_lan_cert.ps1
# PCのIPアドレスが変わったときも、もう一度実行してください。

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$CertDir = Join-Path $Root "backend\data\certs"
New-Item -ItemType Directory -Force -Path $CertDir | Out-Null

if (-not (Get-Command mkcert -ErrorAction SilentlyContinue)) {
    Write-Host "mkcert をインストールします..."
    winget install --id FiloSottile.mkcert -e --accept-source-agreements --accept-package-agreements
    $env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + `
                [System.Environment]::GetEnvironmentVariable("Path", "User")
    if (-not (Get-Command mkcert -ErrorAction SilentlyContinue)) {
        Write-Host "mkcert が見つかりません。PowerShellを開き直してから、もう一度実行してください。" -ForegroundColor Red
        exit 1
    }
}

# このPC専用の認証局を作ってWindowsに登録（初回のみ確認画面が出ます）
mkcert -install

# 自宅LANのIPv4アドレス（プライベートアドレスのみ）
$ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)' -and $_.PrefixOrigin -ne 'WellKnown' } |
    Select-Object -ExpandProperty IPAddress
if (-not $ips) {
    Write-Host "自宅LANのIPアドレスが見つかりません。Wi-Fiや有線LANにつながっているか確認してください。" -ForegroundColor Red
    exit 1
}
$names = @($ips) + @($env:COMPUTERNAME, "localhost")
mkcert -cert-file (Join-Path $CertDir "lan.pem") -key-file (Join-Path $CertDir "lan-key.pem") @names

$caroot = (mkcert -CAROOT).Trim()
Write-Host ""
Write-Host "証明書を作りました: $CertDir" -ForegroundColor Green
Write-Host "スマホで開くURL:"
foreach ($ip in $ips) { Write-Host "  https://${ip}:8766" }
Write-Host ""
Write-Host "スマホ側の準備（初回のみ）:"
Write-Host "  1. 次のファイルをスマホに送る（メールに添付、USB、クラウドドライブなど）:"
Write-Host "     $caroot\rootCA.pem"
Write-Host "  2. iPhone: ファイルを開いてプロファイルをインストール →"
Write-Host "     設定 > 一般 > 情報 > 証明書信頼設定 で mkcert をオンにする"
Write-Host "     Android: 設定 > セキュリティ > 暗号化と認証情報 > 証明書のインストール > CA証明書"
Write-Host "  ※ rootCA-key.pem は絶対に送らないでください（このPCの秘密の鍵です）"
Write-Host ""
Write-Host "最後に、予定チェッカーの設定画面で「スマホから開けるようにする」をオンにしてください。"
