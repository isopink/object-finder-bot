# Laptop tools

`로봇창열기.cmd` (double-click, Windows): opens every window used while driving and filming.

| Window | What |
|---|---|
| teleop (left pane) | `robot/panes/teleop.sh`: the four-key teleop (`w` straight, `a`/`d` 90 degree turns, `s` stop and cancel a search, `q` quit; Enter starts it again). Silent while idle, so it can stay open while the robot drives by itself. |
| navigation (top right) | `robot/panes/navlog.sh`: finder (query, candidates, result), four-command navigator (plan, result), observations that saw something |
| battery (bottom right) | `robot/panes/volt.sh`: live voltage |
| browser tab 1 | `http://<jetson>:8555/` map with the robot pose and the remembered objects |
| browser tab 2 | `http://<jetson>:8601/` live camera with detection boxes (green) and the re-check result (yellow) |

Needs: the laptop on the lab Wi-Fi, SSH key login to the Jetson, `start_all.sh` running there.
Without Windows Terminal (`wt`) it opens three separate windows instead of panes.
The voice question window is separate: `scripts/laptop_voice/음성질문.cmd`.
