@echo off
chcp 65001 >nul
rem One click: every window for driving and watching the robot.
rem   Windows Terminal: teleop (left), navigation log (top right), battery voltage (bottom right)
rem   Browser: map with the robot and the remembered objects (8555), live camera with boxes (8601)
rem The laptop must be on the rcv-robot Wi-Fi and start_all.sh must be running on the Jetson.
set HOST=device06@192.168.1.206
set IP=192.168.1.206
set P=object-finder-bot/robot/panes
ssh -n -o BatchMode=yes -o ConnectTimeout=6 %HOST% true <nul >nul 2>nul
if not "%errorlevel%"=="0" (
  echo [FAIL] Jetson %IP% 에 접속이 안 됩니다. 노트북 Wi-Fi가 rcv-robot 인지, Jetson이 켜져 있는지 확인하세요.
  pause
  exit /b 1
)
where wt >nul 2>nul
if errorlevel 1 (
  start "teleop" cmd /k ssh -t %HOST% bash %P%/teleop.sh
  start "navigation" cmd /k ssh -t %HOST% bash %P%/navlog.sh
  start "battery" cmd /k ssh -t %HOST% bash %P%/volt.sh
) else (
  wt -w new --title teleop ssh -t %HOST% bash %P%/teleop.sh ; split-pane -V -s 0.5 --title navigation ssh -t %HOST% bash %P%/navlog.sh ; split-pane -H -s 0.35 --title battery ssh -t %HOST% bash %P%/volt.sh ; move-focus left
)
start "" http://%IP%:8555/
start "" http://%IP%:8601/
