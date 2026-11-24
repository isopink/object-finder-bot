@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [설치] 처음 한 번만: 파이썬 가상환경과 Whisper를 설치합니다...
  rem Python 3.14 has no faster-whisper wheels yet (2026-11-24): prefer 3.12, 3.11, 3.10.
  py -3.12 -m venv .venv 2>nul || py -3.11 -m venv .venv 2>nul || py -3.10 -m venv .venv 2>nul || py -3 -m venv .venv
  .venv\Scripts\python -m pip install -q faster-whisper sounddevice certifi
)
.venv\Scripts\python ask_robot.py %*
pause
