@echo off
chcp 65001 >nul
rem バックエンドを起動する（動作確認用。普段は register_autostart.ps1 でログオン時に自動起動）
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo 先に setup_backend.bat を実行してください。
  pause
  exit /b 1
)
echo 予定チェッカーのバックエンドを起動します。止めるときはこの画面で Ctrl+C を押してください。
.venv\Scripts\python -m app
pause
