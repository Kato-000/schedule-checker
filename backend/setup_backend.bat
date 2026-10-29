@echo off
chcp 65001 >nul
rem 予定チェッカーのバックエンドを準備する（初回だけ）
cd /d %~dp0
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 -m venv .venv
) else (
  python -m venv .venv
)
if not exist .venv\Scripts\python.exe (
  echo Python が見つかりません。https://www.python.org/ から Python 3.11 以上を入れてください。
  pause
  exit /b 1
)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo 部品のインストールに失敗しました。上のエラーを確認してください。
  pause
  exit /b 1
)
rem 音声入力の部品（入らなくても、音声入力以外は使えます）
.venv\Scripts\python -m pip install -r requirements-voice.txt
if errorlevel 1 (
  echo.
  echo [注意] 音声入力の部品を入れられませんでした。音声入力以外はそのまま使えます。
  echo        Python 3.12 か 3.13 にすると入る場合があります。
)
echo.
echo 準備ができました。start_backend.bat で起動できます。
pause
