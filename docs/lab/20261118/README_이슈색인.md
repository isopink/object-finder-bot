# 11/18 실습 이슈 색인 (분석용)

Jetson `~/object-finder-bot/robot/logs/` 전체 (17개 실행분)를 `logs/`에 넣었습니다.
시간은 Jetson 시각(KST). 각 이슈마다 **어느 로그를 보면 되는지**와 **고친 패치**를 적었습니다.

## 폴더 구성
| 경로 | 내용 |
|---|---|
| `logs/` | 실습 중 모든 스크립트 로그 |
| `patches/0001~0003-*.patch` | 수정 코드 (main 0a7df73 기준, `git apply`) |
| `6조_1118_실습결과.pdf` | 결과 보고서 (측정값, 문제 16개) |
| `1120_실행순서.pdf` | 11/20 실습 순서 |

## 이슈 → 로그 → 패치
| # | 이슈 | 로그 | 패치 / 파일 |
|---|---|---|---|
| 1 | `ros-foxy-ros-base not found` (Foxy가 packages.ros.org에서 빠짐) | `20261118_102911`, `103500` install_foxy.log | 0001 `install_foxy_jetson.sh` (스냅샷 사용) |
| 2 | 스냅샷 저장소 `NO_PUBKEY AD19BAB3CBF125EA` / not signed | `103500` install_foxy.log | 0001: 키 자동 추가 + 지문 확인 |
| 3 | 키 추가 후에도 not found (실패 기록 때문에 Packages 미수신 + `grep -q` pipefail) | `103716`, `103918` install_foxy.log | 0001: 오래된 목록 삭제, `grep -q` 제거 |
| 4 | 설치 성공 (8 OK) | `104058`, `104310` | — |
| 5 | `Failed connection with Devices` (OpenCR 펌웨어가 ROS 2용 아님) | `112608`, `112727`, `112854` bringup.log | 펌웨어 업데이트로 해결 (README `tar -xzf` 수정은 0001) |
| 6 | LDS_MODEL=LDS-02인데 `hlds_laser_publisher`(LDS-01) 실행 → `/scan` 없음 | 모든 bringup.log 앞부분 (`LDS_MODEL=LDS-02` 다음 줄에 hlds) | 0001: `robot/launch/robot_ld08.launch.py` + bringup.sh 자동 선택 |
| 7 | bringup 정상(Run!) 후 **11:53부터** `Failed to read [There is no status packet!]` 8,154줄 (배터리 분리 시점) | `113101` bringup.log (1.1 MB) | 재시작으로 해결. 배터리 연결 상태 주의 |
| 8 | `check_stage1`: `no /odom` (실제로는 발행 중) — pipefail + `head` → BrokenPipeError | `113259`, `113431` check_stage1.log | 0001 `env.sh` `ofb_wait_topic` |
| 9 | `/odom rate unknown`, `/scan rate unknown` — `timeout` SIGTERM으로 hz 출력 유실 | `113600` check_stage1.log | 0001 `env.sh` `ofb_topic_hz` (`-s INT`) |
| 10 | battery 0.07 V, 회전 0° (배터리 방전) | `113600` check_stage1.log | 충전 필요 |
| 11 | 두 번째 bringup 거부 (`turtlebot3_ros already running`, `no /dev/ttyUSB0` — USB 번호 변경) | `114650` bringup.log | 프로세스 정리 + USB 재연결 |
| 12 | `import objmem` 실패 (conda에서 PYTHONPATH 미반영) | `115322` check_stage4.log | `pip install -e . --no-deps`로 해결, 0001 힌트 수정 |
| 13 | worker 로딩 중 **`NvMapMemAllocInternalTagged: 1074810371 error 12`** (약 1 GB GPU 할당 실패, 비치명적) | `115322` worker.log 100행 | 메모리 여유 확보 필요 (아래 표) |
| 14 | `/detect_embed` 최대 8034 ms (첫 호출 워밍업), tile만 검출 | `115543` check_stage4.log | 0001 `worker_probe.py` 워밍업 1회 제외 |
| 15 | `only 1322 MB available` (worker가 이미 떠 있는 상태에서 검사) | `115706` check_stage4.log | 0001 `check_stage4.sh` |
| 16 | `/dev/opencr` → `bus/usb/...` (tty 아님) | (수동 확인) | 0001 udev `SUBSYSTEM=="tty"` |

## 측정값 (로그 기준)
| 항목 | 값 | 로그 |
|---|---|---|
| `/detect_embed` (C920, detectNet+CLIP, 워밍업 후) | 평균 130 ms, 최대 158 ms | `115706` |
| `/embed_text` | 21 ms | `115706` |
| `/verify 'a cup'` | found=True, prob=1.00, 1723 ms | `115706` |
| `/scan` (LDS-02, ld08_driver 수동 실행) | 9.2 Hz | (터미널 측정, 로그 없음) |

## 메모리 (free -m, MB)
| 시점 | used | available | 로그 |
|---|---|---|---|
| bringup + LiDAR + VS Code 원격 | 1963 | 4617 | `115322` |
| + worker 로딩 중 | 4837 | 1740 | `115543` |
| + worker 완료 (C920) | 5289 | **1322** | `115706` |

- worker 하나가 약 **3.3 GB** (PyTorch CLIP + TensorRT detectNet이 cuBLAS/cuDNN을 각자 올림: TRT 쪽 +116, +296, +117 MB — `115322` worker.log 76~103행)
- 여기에 Nav2, objmem 노드, D455가 더해지면 남는 양 약 0.2~0.6 GB (추정) → **음성(Whisper)은 노트북에서** 처리하기로 함

## 로그에 없는 것
- `ros2 launch ld08_driver ld08.launch.py` 수동 실행 기록 (Jetson `~/.ros/log/2026-11-18-12-*`에 있음)
- 수동으로 친 명령 결과 (`ros2 topic hz`, `apt-cache policy` 등)는 보고서 PDF에 정리
