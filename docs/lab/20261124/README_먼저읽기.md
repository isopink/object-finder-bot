# 11/24 실습 결과 + 패치 (6조)

## 1. 오늘 한 것
| 항목 | 결과 |
|---|---|
| 음성인식 (C920 마이크 + Whisper base.en, Jetson GPU) | ✅ "Where is the banana?" 정확히 인식 (약 0.8초). 단어 힌트(initial_prompt)를 넣어야 짧은 단어가 정확해짐 |
| 물체 인식: detectNet vs **NanoOWL** | ✅ **NanoOWL 채택 추천.** detectNet은 투명 물병과 상자를 못 찾았고 어깨를 "bed"로 착각함 (사진 1, 2) |
| **D455 + NanoOWL + 거리** | ✅ 물병과 모니터를 찾고 거리(m)까지 측정 (사진 3), 프레임당 약 0.08초 |
| 워커에 NanoOWL 연결 | ✅ `/verify "a water bottle"` found=True, prob 0.76. 테스트 14개 통과 |
| 메모리 | 워커(CLIP + NanoOWL + D455) 약 4.2GB / 전체 6.8GB → **Whisper까지 Jetson에 올리면 부족** → 음성은 **노트북**에서 |
| 노트북 음성 프로그램 | ✅ 노트북 마이크 → Whisper(노트북 CPU) → SSH → Jetson `/query` 도착 확인 |
| Jetson 보조배터리 | ❌ 안 켜짐. PB220(75W) + **12V** 트리거 케이블. 원인 미확정 (잔량, 포트, 플러그 굵기 확인 필요). 다음엔 **20V 트리거**로 시도 |
| 로봇 바퀴 | ❌ 제자리에서 돌기만 함 → 재조립 중 (모터 선, OpenCR 포트 확인) |

## 2. 패치 적용 (레포 폴더에서)
```bash
git am patches/0001-*.patch patches/0002-*.patch
git push
```
그다음 Jetson에서 `cd ~/object-finder-bot && git pull`

| 패치 | 내용 | 실기 확인 |
|---|---|---|
| 0001 NanoOWL | `--detector owl` (`OFB_DETECTOR=owl ./robot/worker.sh depth`), find_object.py 옵션, env_probe, README | ✅ 확인 |
| 0002 LiDAR 기둥 무시 | 카메라 기둥이 LiDAR에 장애물로 잡히는 문제. `OFB_SCAN_MIN=0.20 ./robot/bringup.sh`처럼 쓰면 그 거리보다 가까운 점을 지움 (기본값 0 = 꺼짐) | ⚠️ **아직 로봇에서 안 돌려 봄** |

0002를 쓰기 전에 줄자로 잴 것:
- ① LiDAR 중심에서 가장 먼 기둥까지 거리
- ② LiDAR 중심에서 로봇 앞 끝까지 거리
- → OFB_SCAN_MIN은 **① < 값 < ②**로 정하기

## 3. 노트북 음성 프로그램 (`laptop_voice/`)
- `음성질문.cmd` 더블클릭. 처음 한 번은 자동 설치(약 100MB)
- Enter → 말하기, 또는 **질문을 타자로 입력해도 전송됨** (1차 데모용)
- Jetson 주소 기본값: `device06@192.168.1.206` (SSH 키 로그인 필요). 다르면 `--host user@ip`
- 실습실 와이파이에서 모델 다운로드가 막히면 `lab-ca.pem`을 홈 폴더에 두기 (자동 사용)

## 4. 주의
- **투명 물체는 D455 거리가 틀림** (물병이 2.4m인데 3.6~3.9m로 나옴, 적외선이 통과함) → 데모 물체는 **불투명한 것** (바나나, 가방, 컵, 상자)
- 카메라는 **아래로 10~15°** 기울이기 (위를 보면 책상 물체가 화면 아래 끝에 걸려서 놓침)
- 로봇이 책상 밑으로 들어가면 카메라 기둥이 부딪힘 → 순찰과 목표 지점은 통로에만 찍기, 또는 지도에서 책상을 검게 칠하기

## 5. 다음 실습 순서
1. 로봇 조립 → 바퀴 확인 (`check_stage1.sh`)
2. 기둥 거리 재고 `OFB_SCAN_MIN` 정하기
3. 카메라 장착 위치 측정 (높이, 앞뒤, 기울기)
4. 지도 (`slam.sh` + teleop) → Nav2 (`nav.sh`, `check_stage3.sh`)
5. 전체 실행 (`OFB_DETECTOR=owl`) + 노트북 음성으로 질문 → **메모리 실측**
