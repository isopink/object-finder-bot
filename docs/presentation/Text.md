---
title: "Where Is My Cup?"
subtitle: "Now You'll Never Forget Where You Put Things"
eyebrow: "2026 Fall · Intelligent Robotics"
speaker: "Speaker : S.Lee"
date: "December 10, 2026"
footer-left: "Team 6 · Intelligent Robotics, UOS"
footer-center: "Where Is My Cup?"
---

<!-- 원고 규칙: Rules.md. 슬라이드 글자는 키워드만, 설명은 > 노트로. -->
<!-- 빈 자리: [[사진 n]] / [[영상 n]] = 나중에 채울 사진·영상, [ ___ ] = 나중에 채울 숫자. 목록은 사진 소싱 가이드.md -->

# Title

> 인사, 팀 소개. "오늘은 물건을 기억하고 찾아가는 로봇 이야기입니다."

---
## Outline

- Part 1 : Motivation & System
- Part 2 : Theory in Practice
- Part 3 : Troubleshooting
- Part 4 : Results

> 네 부분으로 진행. 2부(이론)와 3부(트러블슈팅)가 중심.

---
## I Always Forget Where I Put Things
### Where did I leave my **cup**?

- Cup, laptop, charger
- I saw it — but **where**?

[[사진 1]]
(오른쪽 절반: 책상 위 컵 사진, 데모데이에 촬영)

>> What if a robot remembered for me?

> 실제 경험으로 시작. 분명 봤는데 어디였는지 기억이 안 난다.

---
## A Robot That Remembers
### See → Ask → Go

(그림: 카드 3장 — See: drive around, remember what & where / Ask: "Where is the cup?" / Go: drive there, look again)

>> Remember with **probability**, not certainty

> 돌아다니면서 본 물건을 위치와 함께 기억(멈출 때뿐 아니라 직진 중에도). 말로 물으면 그 자리로 가서 다시 확인. 핵심은 "확률로 기억한다" → 2부로 연결.

---
## System Overview
### From one question to one cup

(그림: 가운데 가로축 = 진행 단계 0. Remember(점선, 사전 주행) → 1. Ask → 2. Rank → 3. Drive → 4. Re-check → 5. Report. 각 단계 위에 Software 노드, 아래에 Middleware → Hardware 노드를 세로선으로 연결. 맨 아래 OS 띠. Software: NanoOWL · CLIP, objmem while driving / faster-whisper / CLIP text × belief / gridnav (4 commands), AMCL on Cartographer map / look ±15° × 3, NanoOWL + CLIP / map view (orange path), live video. Hardware: D455f depth, Jetson GPU / Laptop mic / Jetson Xavier NX / LDS-02 · OpenCR / D455f / Laptop. 직접 만든 노드는 마룬: CLIP × belief, gridnav, re-check)

>> **Maroon** = what we built

> 가운데 파란 축이 진행 단계. 0단계(점선)는 질문 전에 돌아다니며 기억해 두는 단계: D455f depth로 물체 위치를 재고, 직진 중에도 기억(회전 중만 건너뜀). 질문은 노트북 faster-whisper → SSH → /query. CLIP × 믿음으로 순위. 이동은 Cartographer 지도 위에서 AMCL로 위치를 잡고 gridnav(직진·좌90°·우90°·정지 네 가지 명령)로. 도착하면 좌우 15°씩 3번 둘러보고 NanoOWL+CLIP으로 재확인. 결과는 지도 화면(기억, 주황 경로)과 실시간 영상으로 봄. 마룬이 직접 만든 부분.

---
## From Camera to Map
### Pixel + depth → one point on the map

$$ \mathbf{p}_{cam} = Z\,K^{-1}\,[\,u,\ v,\ 1\,]^{\top} $$
$$ \mathbf{p}_{map} = A\,B\,\mathbf{p}_{cam}, \qquad T = \begin{bmatrix} R & \mathbf{t} \\ \mathbf{0}^{\top} & 1 \end{bmatrix} $$

(그림: Pixel (u, v, Z) —K⁻¹→ Camera —B→ Robot —A→ Map)

- K : f_x **615** (placeholder) → **387** (measured)

>> Homogeneous coordinates: one matrix per hop

> 첫 식(역투영)은 강의 밖 우리 추가분. 둘째 식은 강의의 Combining Transformations 그대로. A = AMCL 로봇 자세, B = 카메라 장착 위치(실측). K의 함정(트러블슈팅 33): 설정 파일의 fx 615는 D435 기준 임시값이었고, D455F 640×480 실측은 386.98(시야각 79.2°). 임시값을 그대로 썼으면 좌우 방향이 약 60% 어긋났을 것.

---
## Is the Cup Still There?
### Static state binary Bayes filter, in log odds

|||
**Is it there?**
$$ l_t = l_{t-1} + \log \frac{p(z \mid \text{present})}{p(z \mid \text{absent})} $$
- Seen: **+2.08**
- In view, not seen: **−1.50**
- Objects move → prediction step
|||
**Which one?**
$$ \text{score}_i = \operatorname{softmax}\!\left(\frac{\cos(\text{CLIP}(q),\, e_i)}{T}\right)\cdot p_i $$
- Top 3 → visit in order

>> Seen raises the belief, missing lowers it

> 강의(L06)의 static state binary Bayes filter와 같은 필터. p(z|present)=0.8, p(z|absent)=0.1 → 보면 ln 8, 못 보면 ln(2/9). 시간 감쇠는 강의 밖 추가분: 물건은 "world is static" 가정을 깨므로 예측 단계를 넣음. 오른쪽: CLIP 유사도 × 존재 확률.

---
## Where Exactly Is It?
### Kalman filter correction — the cup does not move

$$ K_t = \bar{\Sigma}_t\,(\bar{\Sigma}_t + Q_t)^{-1} $$
$$ \mu_t = \bar{\mu}_t + K_t\,(z_t - \bar{\mu}_t) \qquad \Sigma_t = (I - K_t)\,\bar{\Sigma}_t $$

(그림: 1D 가우시안 세 개 — 기억 N(8, 4), 새 관측 N(6, 1), 합친 결과 N(6.4, 0.8). "It's a weighted mean")

>> Every look shrinks Σ

> 강의 칼만 필터의 correction step에서 C_t = I, 예측은 그대로(물체는 정지). 측정 노이즈는 강의 표기대로 Q_t, 멀수록 커짐. 그림은 강의 1D 예제 숫자. Q_t를 실제보다 작게 잡으면 생기는 일은 Case 4.

---
## Mapping and Localization
### Graph-based SLAM, then Monte Carlo Localization

|||
**Mapping**
![[room_l4_full.png]]
![[room_l4_aisle.png]]
- Graph-based SLAM · loop closure
- Unknown ≠ free → aisle map for **planning only**
|||
**Localization (AMCL = MCL)**
(그림: Predict — odometry motion model → Weight — likelihood field → Resample — low variance)
[[사진 2]]
(AMCL 파티클이 모이는 화면 캡처, 데모데이)

>> Known map → errors stop piling up

> Cartographer = 강의 Three Traditional Paradigms 중 graph-based. 2D LiDAR는 책상 윗판을 못 보고, 회색(unknown)을 빈 곳으로 읽으면 안 됨 → 실제 지나간 통로만 남긴 지도를 따로 만듦. 단, 통로 지도는 경로 계획에만 쓰고 AMCL에는 원본 지도를 줌(이유는 Case 2). AMCL은 강의의 MCL 그대로.

---
## 40 Problems at a Glance
### Grouped by layer

(그림: 막대 4개 — Software 21, Hardware 7, Network & tools 7, Middleware 5. 막대 옆에 대표 사례 키워드)

>> Find the layer first, then the bug

> 트러블슈팅 기록 40건을 층별로 분류. Software 21: 6, 10, 11, 12, 15, 18, 22, 24, 25, 26, 28~32, 34~38, 40 / Hardware 7: 7, 8, 13, 16, 17, 27, 33 / Network & tools 7: 1~5, 9, 39 / Middleware 5: 14, 19, 20, 21, 23 (나중에 켠 노드가 /odom을 못 찾던 DDS 문제 포함). 1~33번은 이전 개수(15/7/6/5)에 맞게 분류, 34~40번을 더함. 다음 여섯 장에서 대표 사례.

---
## Case 1 : The Map That Wouldn't Turn
### The wheels turned, odometry did not

![[map_straight.png]]
(그림: 표 — Wheels +29° / odom +0.0° → heading from wheels: +28.4°)
$$ \theta = \int \omega\, dt, \qquad \omega = \frac{v_r - v_l}{l} $$
- LiDAR mounted 180° → rotate the scan

>> Check odometry before blaming SLAM

> ㄱ자로 운전했는데 지도는 일자(11/25). 원인 1: 로봇 드라이버의 odom 방향이 멈춤. 11/25(바퀴 +97.7°, IMU +91.7°, odom 0°), 11/27, 11/28 세 번 반복. 11/28 시험: 바퀴는 29° 돌았는데 odom은 +0.0°. 바퀴 각도(/joint_states)는 항상 맞았음 → 바퀴 각도로 odom을 직접 계산(differential drive, wheel_odom.py) → +28.4°(바퀴 계산 29°), 이후 주행 내내 정상. 원인 2(11/27): LiDAR가 판 위에 180° 반대로 달려 있었음. 앞 0.44 m 물체가 185°에 보였고, 10.7 cm 전진하자 그 물체가 10.5 cm 가까워짐 → 0°가 로봇 뒤를 보고 있었음 → 스캔을 소프트웨어로 180° 돌림. 둘 다 고친 뒤 room_l4: 벽 직선, 출발점 복귀 오차 0.14 m.

---
## Case 2 : Right Map, Wrong Place
### AMCL on the aisle-only map → 1.8 m off

![[room_l4_aisle.png]]
![[room_l4_full.png]]
$$ w_t^{[m]} = p\big(z_t \mid x_t^{[m]},\, m\big) $$
- Aisle map: walls everywhere → **every pose fits**
- Scan on walls : AMCL pose **38%** vs re-localized **86%**
- Fix: **full map** → AMCL, aisle map → planning

>> A map that fits everywhere tells nothing

> 증상: 몇 m 주행 뒤 지도 화면의 로봇이 실제와 다른 책상 줄에 있음(1.8 m 차이). 그 위치로 기억한 컵도 엉뚱한 곳에 찍힘. 원인: AMCL에 통로만 남긴 지도를 줌. 통로 밖이 전부 벽이라 likelihood field에서 어느 파티클이든 스캔이 잘 맞아 보임 → 가중치가 고만고만 → 사실상 바퀴 기록만 따라감. 확인: 현재 스캔을 원본 지도 전체에 맞춰 봄. AMCL이 믿는 위치에서는 스캔의 38%만 벽에 닿고, 다시 찾은 위치에서는 86%. 해결: 위치 추정은 원본 지도, 경로 계획만 통로 지도. 주행 후 AMCL과 스캔 맞춤 차이 3 cm, 2°. 위치 보정 도구 relocalize.sh: 처음 위치를 몰라도 스캔을 지도 전체에 맞춰 위치를 찾고 AMCL에 알려 줌(9초). 로봇을 들어 옮긴 뒤에도 사용. (트러블슈팅 34)

---
## Case 3 : Only 90° Turns
### Every turn adds heading error

(그림: 직진 계획선 vs Δθ 틀어진 실제 선, 옆 오차 e⊥)
$$ e_{\perp} \approx s \cdot \sin \Delta\theta $$
- 5 m: 1° → **9 cm**, 5° → **44 cm**

|||
**Mapping — teleop4**
straight · 90° · stop
|||
**Navigation — gridnav**
A* grid path · closed loop on AMCL
3 / 3 queries reached (11/28)

>> Every turn adds error — so every turn is exactly 90°

> 강의 odometry motion model: 회전할 때마다 방향 오차(α), 이동 거리가 그걸 옆 오차로 키움. 그래서 지도 그릴 때도, 찾아갈 때도 직진과 정확한 90° 회전만. 위치는 AMCL(지도 기준)이라 바퀴 오차가 쌓이지 않음. 배경: Nav2는 좁은 통로에서 경로를 못 만들거나 목표 0.31 m 앞에서 포기했고, 복구 동작(제자리 회전)이 좁은 곳에서 위험. gridnav: 통로 지도 위에 A*로 직진과 90° 꺾임만 있는 경로 → AMCL 자세를 보며 "축 방향으로 회전 → 모서리까지 직진" 반복. 보내는 명령은 직진, 좌90°, 우90°, 정지 네 가지뿐. 11/28 실제 로봇에서 질문 3개 모두 도착(꺾임 2~3번 경로).

---
## Case 4 : One Cup, Many Memories
### Q_t smaller than reality → one cup splits

(그림: 같은 컵을 두 위치에서 본 관측 두 개. 왼쪽 "Q_t too small": 작은 타원 두 개가 겹치지 않아 기억 2개 / 오른쪽 "Q_t realistic": 큰 타원 안에 둘 다 → 기억 1개)
$$ d = \sqrt{(z_t - \mu)^{\top} (\Sigma + Q_t)^{-1} (z_t - \mu)} \;\le\; \gamma $$
- Two boxes per cup (IoU ≈ 0.5)
- σ_bearing 0.03 → **0.06** rad, γ 3.0 → **4.0**

>> An overconfident Q_t splits one object

> 증상(11/28): 같은 컵이 10~20 cm 간격으로 기억 2~3개. 원인 1: NanoOWL이 컵 몸통과 빨대까지 포함한 컵을 각각 상자로 냄. 두 상자 IoU 약 0.5라 기존 기준(0.7)으로는 둘 다 남음 → IoU 0.5 + 작은 상자가 80% 이상 큰 상자 안이면 제거. 원인 2(이론과 연결): 새 관측을 기존 기억과 같은 물체로 볼지는 마할라노비스 거리 d로 정함. 관측 잡음 Q_t(방향 1.7°, 거리 2 cm)가 실제 오차(AMCL 방향만 1~2°, 여기에 장착 오차)보다 작아서, 다른 위치에서 본 같은 컵을 "다른 물체"로 판단. → σ_bearing 0.03→0.06 rad, σ_range 0.02→0.05 m, 기준 γ 3.0→4.0, CLIP 유사도 기준 0.80→0.75. 효과는 한 번의 주행에서만 확인(한계 장). 이 자리에 있던 DDS 사례(나중에 켠 노드가 서로 못 들음, 23번)는 10장 Middleware에서 말로만 언급.

---
## Case 5 : Design Changed by Constraints
### C920 → D455f : bearing-only → range-bearing

(그림: 왼쪽 C920 — 통로에서 거의 평행한 두 시선, 시선 방향으로 긴 오차 타원 / 오른쪽 D455f — 한 번에 거리+방향, 작은 타원)

- detectNet → **NanoOWL** (clear bottle missed)
- Whisper → **laptop** (4.2 / 6.8 GB)
- GPU out of memory on restart → drop **1.3 GB** file cache

>> A direction is not a position

> 강의 Range-Bearing Model: 방향 측정은 시선에 수직인 방향만 잡아 줌. 통로에서는 두 시선이 거의 평행 → 3 m 앞 물체가 약 0.5 m 오차. D455f는 한 번에 위치. (같은 시기에 카메라 장착 방향도 바로잡음.) 메모리 한계(워커 약 4.2 GB / 전체 6.8 GB)로 음성인식은 노트북으로. 같은 메모리 문제의 다른 얼굴: 워커를 다시 켜면 TensorRT 엔진이 GPU 메모리를 못 받음. 모델 파일을 읽으며 생긴 파일 캐시 1.3 GB가 원인(Jetson은 CPU와 GPU가 메모리를 같이 쓰고, GPU 할당기는 캐시를 못 씀) → 모델을 읽는 동안 캐시를 비워서 재부팅 없이 재시작.

---
## Case 6 : Raising the Eye
### Stock camera too low for desk tops → camera mast

(그림: 옆에서 본 그림 — 책상 위 컵, 낮은 기본 카메라의 시선은 책상 옆면에 막힘(마룬 점선), 기둥 위 카메라(0.815 m)의 시선은 책상 위 컵에 닿음(블루). 기본 높이 [ ___ m ])
- Mast in the LiDAR plane? **Not seen** → no filter
- Wobbles → stiffer mast, skip turns
- Mast hits desks → goals in aisles only

>> Check what the sensor sees before adding a fix

> 기본 카메라 자리는 너무 낮아 책상 윗면이 안 보임(목표 물체는 책상 위 컵·노트북) → 카메라를 기둥 위로 올림. 높이는 실측 0.815 m(수평 장착), 이 값이 2부 From Camera to Map의 B(카메라 → 로봇 변환)에 들어감. 기본 높이는 [ ___ m ]. 올리니까 생긴 문제 셋. (1) 기둥이 LiDAR 스캔 평면에 서 있으면 로봇이 자기 자신을 장애물로 볼 수 있음 → 가까운 점 지우는 필터(OFB_SCAN_MIN)를 미리 만들어 둠. 그런데 줄자 대신 LiDAR 데이터로 먼저 확인: 세워 둔 채 스캔 60개, 0.418 m 안쪽에 반복해서 찍히는 점 없음, 값이 안 오는 빔도 245개 중 1개 → 가는 기둥은 안 보임 → 필터 끔(트러블슈팅 16). (2) C920(약 160 g)이 기둥 위에서 흔들림 → 기둥 보강(17번). 무게중심이 높아져 회전 중에는 사진이 번지므로 회전 중에는 기억하지 않음(37번). (3) 책상 밑으로 들어가면 기둥이 부딪힘 → 목표 지점은 통로에만.

---
## Measured on the Robot
### First full run : see → remember → ask → drive → re-check (11/28)

(그림: 숫자 4개 — 3 / 3 queries found / 0.84 · 0.67 · 0.87 confidence (cup, laptop, cup) / 0.08 s detection + depth per frame / 10 fps live view)

![[mapview_final.png]]
(왼쪽: 마지막 지도 화면 — 기억, 주황 경로, goal)

[[영상 1]]
(오른쪽: 데모데이 "Where is the cup?" → 이동 → 찾음)

- Demo Day : [ ___ / ___ ]

> 11/28 새벽 실제 로봇에서 처음으로 전체 흐름 성공. 질문 3개 모두 found: 컵 93초 확신도 0.84, 노트북 112초(+42초) 확신도 0.67, 컵 100초 확신도 0.87. 지도 화면: 주황 선이 gridnav 경로(직진과 90° 꺾임만), 점이 기억(색 = 존재 확률). 0.08초는 검출+거리 한 장(11/24), 실시간 영상 초당 10장(11/28). 데모데이 영상 재생. 데모데이 성공 횟수는 결과로 채움.

---
## Why Probabilistic Memory Helps
### After moving objects (simulation, 5 seeds × 20 queries)

(그림: 막대 — moved object top-1: probabilistic 100% vs similarity only 50%, visits per query 1.00 vs 1.80)

[[영상 2]]
(데모데이: 컵을 옮긴 뒤 같은 질문 → 예전 자리 실패 → 새 자리)

>> Lowering the old belief finds the new place

> 장난감 세계 시뮬레이션: 위치가 완벽해서 절대값보다 비교가 의미. 옮긴 물체는 확률 메모리가 한 번에 찾음. 데모 영상으로 실제 확인.

---
## Limitations and Lessons

|||
**Limitations**
- Monitor detected as a **laptop**
- Merge fix checked in **one run** only
- 2D LiDAR : aisles only, desk tops unseen
|||
**Lessons**
- Check the layer below first
- Simple motion in tight spaces
- Keep uncertainty explicit — and **honest**

Future work : VIO (not tried)

>> Thank you

> 한계: (1) 실습실 모니터가 "a laptop"으로 잡혀 노트북 기억이 여러 개 생김(11/28 노트북 기억 19개 중 대부분) → 질문 때 모니터로 갈 수 있음. (2) 같은 물체가 기억 여러 개로 나뉘던 문제의 수정 효과는 한 번의 주행으로만 확인. (3) 2D LiDAR라 통로만 다니고 책상 윗판은 못 봄. 투명한 컵은 depth가 깨짐. 향후 과제: VIO(카메라+IMU 위치 추정)는 시도하지 않았음. 배운 점 셋. "honest" = Case 4: Q_t를 실제 오차만큼 크게. 질문 받는 동안 이 화면 유지.

---
## References

- [1] S. Thrun, W. Burgard, and D. Fox, *Probabilistic Robotics*. MIT Press, 2005.
- [2] A. Radford et al., "Learning transferable visual models from natural language supervision," in *Proc. ICML*, 2021.
- [3] M. Minderer et al., "Simple open-vocabulary object detection with vision transformers," in *Proc. ECCV*, 2022.
- [4] W. Hess, D. Kohler, H. Rapp, and D. Andor, "Real-time loop closure in 2D LIDAR SLAM," in *Proc. ICRA*, 2016.
- [5] S. Macenski, F. Martín, R. White, and J. Ginés Clavero, "The Marathon 2: A navigation system," in *Proc. IROS*, 2020.
- [6] A. Radford et al., "Robust speech recognition via large-scale weak supervision," in *Proc. ICML*, 2023.
- [7] Intelligent Robotics lecture slides, University of Seoul, Fall 2026.

> 참고 문헌.
