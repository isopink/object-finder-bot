# 말로 물어보는 물건 찾기 로봇

> "Where is the blue mug?" → 로봇이 기억을 검색해 그 물건이 있던 곳으로 데려간다.

TurtleBot3 Waffle Pi가 공간을 돌아다니며 본 **책상 위 물체**를 **CLIP 임베딩 + 지도상 위치 + 관측 시각**으로 기억한다. 사용자가 영어 문장으로 물체를 묘사하면, 텍스트-이미지 유사도로 가장 그럴듯한 기억을 찾아 그 위치로 자율 주행한다.

서울시립대학교 2026-2학기 지능형로봇 수업의 2인 팀 프로젝트이다.

## 핵심 아이디어: 확률적 물체 기억

정해진 클래스만 찾는 검출기와 달리, "a red tumbler", "a black charger next to the laptop" 같은 자유로운 묘사로 검색한다 (open-vocabulary). 기억 하나마다 아래 값을 저장하고 확률적으로 갱신한다.

| 저장하는 값 | 갱신 방법 |
|-------------|-----------|
| 위치 평균 `μ = (x, y)`, 공분산 `Σ` | 같은 물체를 다시 보면 **Kalman Filter**로 융합 |
| CLIP 이미지 임베딩 `e` | 물체 crop에서 추출 (OpenCLIP ViT-B/32, FP16) |
| 존재 신뢰도 `p` | 봤는데 있음/없음에 따라 **베이즈 업데이트**, 시간이 지나면 감쇠 |
| 마지막 관측 시각 `t_last` | 시간 감쇠 계산에 사용 |

검색 점수는 `질의-기억 유사도(softmax) × 존재 신뢰도`이다. 점수가 높은 후보부터 방문하고, 도착하면 현재 화면에서 다시 확인한다. 없으면 신뢰도를 낮추고 다음 후보로 간다.

수식과 설계 근거는 [기획안](기획안/말로%20물어보는%20물건%20찾기%20로봇.md)에 있다.

## 시스템 구성

```
[와플파이 (Raspberry Pi)]                          [Jetson Xavier NX (원격)]
 LiDAR ──────────────┐                            ┌─ SLAM(slam_toolbox) / AMCL / Nav2
 오도메트리 ──────────┤                            ├─ 물체 검출 (detectNet / YOLO, TensorRT)
 C920 (압축 영상) ────┼── ROS 2 (실습실 Wi-Fi) ──▶ ├─ 물체 거리: RealSense 깊이
 RealSense (깊이) ────┘                            ├─ CLIP 임베딩 추출 (FP16)
 모터 제어 ◀──────────────────────────────────── ├─ 확률적 물체 기억 DB
                                                   └─ 질의: 영어 텍스트 (+ Whisper 음성)
```

| 모듈 | 사용 기술 |
|------|-----------|
| 지도 작성 / 위치 추정 / 주행 | slam_toolbox, AMCL (Particle Filter), Nav2 |
| 물체 검출 | detectNet(SSD-Mobilenet-v2) 또는 YOLO (TensorRT) |
| 물체 위치 | 깊이 역투영 → 카메라 → base_link → map 좌표 변환 |
| 물체 기억 / 검색 | CLIP, Kalman Filter, 베이즈 업데이트 |

지도 작성·위치 추정·주행은 검증된 패키지를 쓰고, 이 프로젝트의 기여는 물체 기억과 검색 모듈에 둔다.

## 장비

- TurtleBot3 Waffle Pi (LiDAR, OpenCR, Raspberry Pi)
- NVIDIA Jetson Xavier NX (ASUS PE1000N, 8 GB) — Ubuntu 20.04, JetPack 5.1.5
- Logitech C920 웹캠, Intel RealSense (깊이)
- 카메라 거치대: 와플파이 기본 카메라 높이로는 책상 위가 보이지 않아 카메라를 높여 장착

## 폴더 안내

| 폴더 | 내용 |
|------|------|
| [`slam/`](slam/README.md) | ROS 2 SLAM 스크립트: Gazebo 시뮬레이션, 실제 로봇 검증, rosbag 녹화·재생, 지도 저장 |
| [`vision/`](vision/) | Jetson에서 도는 비전 코드: CLIP 속도·메모리 측정, 카메라 + detectNet + CLIP 기억/검색 |
| [`기획안/`](기획안/말로%20물어보는%20물건%20찾기%20로봇.md) | 설계 문서: 수식, 일정, 평가 지표, 위험 요소 |

## 실행

### 지도 작성 (`slam/`)

집에서는 Gazebo 시뮬레이션으로, 실습실에서는 실제 로봇으로 같은 스크립트를 쓴다. 설치와 사용법은 [`slam/README.md`](slam/README.md)에 있다.

```bash
cd slam
./scripts/sim_slam.sh slam_toolbox world      # Gazebo + SLAM + RViz
./scripts/save_map.sh sim_world_toolbox       # 지도 저장
```

### 물건 기억·검색 (`vision/`)

로봇 없이 Jetson과 카메라만으로 비전 파트를 돌려 보는 버전이다. 물체 위치를 지도 좌표 대신 화면 상자로 저장한다.

```bash
cd vision
python clip_jetson_test.py --fp16     # CLIP 처리 시간, GPU 메모리 측정
python jetson_find_object.py          # 브라우저 http://<JETSON_IP>:8554 에서 영상 확인
```

터미널 명령:

| 명령 | 동작 |
|------|------|
| `s` | 지금 화면에서 검출된 물체를 기억 |
| `t` | 화면을 3x3 조각으로 잘라 기억 (검출기가 모르는 물건용) |
| `q a black bag` | 기억에서 문장과 가장 비슷한 물체 찾기 |
| `f a black bag` | 지금 화면에서 바로 찾기 |

## 진행 상황

| 단계 | 내용 | 코드 |
|------|------|------|
| 지도 작성 | SLAM 스크립트 (시뮬레이션, 실제 로봇 검증, rosbag) | `slam/` |
| 비전 | Jetson에서 CLIP 동작 확인, 화면 기준 기억·검색 | `vision/` |
| 기억·지도 투영 | 물체 위치를 지도 좌표로 변환, AMCL·Nav2 주행 | 진행 중 |
| 통합 | 질의 → 후보 이동 → 재확인 루프, 확률 기억 갱신 | 예정 |
| 확장 | Whisper 음성 질의, 옮겨진 물체 재탐색 | 예정 |

## 팀

| 이름 | 역할 |
|------|------|
| 이석민 | 로봇·주행 (SLAM, Nav2, 좌표 변환) |
| 이동하 | 비전·AI (검출, CLIP, 물체 기억) |
