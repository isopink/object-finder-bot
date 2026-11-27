# 11/27 지도와 Nav2 (동하)

트러블슈팅 23~26번에 자세한 내용. 오늘 처음으로 **지도 위 Nav2 왕복**이 됐다.

## 오늘 된 순서 (재부팅 후 그대로 따라 하기)
1. Jetson 켜고 `timedatectl`에서 시계 동기화 확인 (19번)
2. OpenCR 리셋: USB 뽑기, 스위치 OFF 5초, ON(도레미), 10초 손대지 않기, USB 꽂기
3. 모든 창에서 같은 설정: `export OFB_DDS_WIDE=1 OFB_ODOM_IMU=0`
4. `./robot/bringup.sh` (회전은 바퀴 기준, 18번)
5. `./robot/slam.sh cartographer` + `python3 robot/lib/live_map.py` (브라우저 `http://<jetson-ip>:8556/`)
6. `./robot/teleop.sh`로 통로를 천천히 왕복, 출발점에 처음 방향으로 복귀
7. 저장: `./robot/save_map.sh room_l3`, yaml의 `image:`를 파일 이름만 남기기
8. Nav2용 사본: Cartographer가 켜진 채로 `/trajectory_node_list`를 JSON으로 받아 `python3 robot/lib/make_nav_map.py robot/maps/room_l3.yaml --path <json> --radius 0.5`
9. SLAM 끄고 `./robot/nav.sh room_l3_nav`, `./robot/set_initial_pose.sh 0 0 0`
10. `./robot/goto.sh 1.0 0 0`, `./robot/goto.sh 0 0 0`

3번의 두 옵션은 오늘은 `/tmp` 설정 파일로 손으로 했다. 이 커밋으로 레포에 들어감 (Jetson에서는 아직 레포 버전으로 실행해 보지 않음).

## 결과
| 항목 | 결과 |
|---|---|
| 회전 기록 | 제자리 90° 명령에 /odom +90.9°, +91.1° |
| 지도 `room_l3` | Cartographer, 30.2 m², 벽 한 줄 |
| Nav2용 `room_l3_nav` | 통로만 4.3 m² |
| Nav2 | 1 m 앞 12초(오차 0.09 m), 복귀 26초(오차 0.10 m) |

## 아직
1. 비전(NanoOWL 워커 + objmem 노드)과 함께 실행, 메모리 실측
2. 카메라가 로봇 뒤쪽 (`w` 반대쪽). 지금 데모 방식(물체를 봤던 자리로 돌아가기)에서는 동작하지만 `nodepth.yaml`의 `cam_*` 값은 맞지 않음
3. Jetson 갑자기 꺼짐 (전원 선)
