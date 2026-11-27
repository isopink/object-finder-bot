---
title: "Where Is My Cup?"
subtitle: "Probabilistic Object Memory on a Real Robot"
eyebrow: "2026 Fall · Intelligent Robotics"
speaker: "Speaker : S.Lee"
date: "December 10, 2026"
footer-left: "Team 6 · Intelligent Robotics, UOS"
footer-center: "Where Is My Cup?"
cover-image: "mapview_final.png"
cover-caption: "The robot's memory and path after asking “Where is the cup?” (real robot, 11/28)"
---

<!-- 원고 규칙: Rules.md (v2.0 논문 리뷰 형식 DESIGN.md 9장, v3.0 흑백 톤: **굵게**는 검정, ==강조==만 마룬, DESIGN.md 10장). 슬라이드 글자는 키워드만, 설명은 > 노트로. -->
<!-- 빈 자리: [[사진 n]] / [[영상 n]] = 나중에 채울 사진·영상, [ ___ ] = 나중에 채울 숫자. 목록은 사진 소싱 가이드.md -->
<!-- 번호: Fig. 1~12, Table 1~4, 식 (1)~(10). 사진 칸: 사진 1~5, 영상 2~3. 대본에서 "식 (4)", "Fig. 9"처럼 부른다. -->

# Title

> 표지 오른쪽은 프로젝트 대표 이미지(11/28 실제 주행 직후 지도 화면, 로봇 사진이 생기면 cover-image만 바꿈). 인사, 팀 소개. "오늘은 논문 한 편을 리뷰하듯, 우리 로봇을 문제 정의 → 방법 → 실험 → 실패 분석 순서로 발표하겠습니다."

---
§ Overview
## Where Is the Cup?
### One question → drive → re-check → found (real robot, 11/28)

(a) Run
[[영상 3]]
(실제 로봇 11/28 01:35: "Where is the cup?" → 이동 → 좌우 확인 → found)
(b) Map view after the run
![[mapview_final.png]]

Fig. 1. (a) The robot answers a spoken query. (b) Memories (dots, color = belief), planned path (orange) and goal.

>> How did it know where the cup was?

> 설명 없이 영상부터. 11/28 새벽 01:35, "Where is the cup?" 한 문장 → 100초 이동 → 도착 후 좌우 둘러보기 → found(확신도 0.87). 오른쪽은 그 직후 지도 화면: 점이 기억(색 = 존재 확률), 주황 선이 이동 경로. "로봇은 컵이 어디 있는지 어떻게 알았을까요? 오늘은 그 답과, 그 답이 실제 로봇에서 어떻게 틀렸는지를 이야기합니다."

---
§1 Introduction
## Problem and Contributions
### Find a remembered object from one spoken query

(그림: 카드 3장 — Input: spoken query q, map m, memory M built while driving / Output: drive to the object, report found or not / Constraints: narrow aisles, 2D LiDAR, Jetson 8 GB)

- **Probabilistic object memory** : Bayes + Kalman
- **4-command navigation** for narrow aisles
- **Failure analysis** of 40 real-robot problems

[[사진 1]]
(오른쪽: 실습실 장면 — 통로의 로봇, 책상 위 컵)

>> Remember with **probability**, not certainty

> 문제: 돌아다니며 본 물건을 기억했다가, 말로 물으면 그 자리로 가서 확인. 입력은 질문 q, 지도 m, 주행 중 쌓은 기억 M. 출력은 그 물건 앞까지 이동하고 found / not found 보고. 제약은 좁은 통로, 2D LiDAR, Jetson 8 GB(워커 약 4.2 GB / 전체 6.8 GB). 기여 세 가지: (1) "있나?"는 베이즈 필터, "어디?"는 칼만 필터로 기억, (2) 좁은 통로용 네 가지 명령 이동, (3) 실제 로봇에서 만난 문제 40건의 분석.

---
§2 Formulation
## Each Memory : What, Where, How Sure
### Rank by meaning × belief

(그림: 지도 위 기억 3개 — 각 기억은 점(μ_i)과 오차 타원(Σ_i), 점 색 = 존재 확률 p_i, 태그 e_i. 오른쪽 범례: e_i = CLIP image embedding (what) / μ_i, Σ_i = position, Kalman (where) / l_i = log-odds belief (how sure))
$$ \text{score}_i = \operatorname{softmax}_i\!\left(\frac{\cos(\text{CLIP}(q),\, e_i)}{T}\right)\cdot p_i, \qquad p_i = 1 - \frac{1}{1 + e^{\,l_i}} $$ (1)

Fig. 2. A memory item. A query is ranked by text-image similarity [2] times belief; the top 3 are visited in order.

>> Rank by meaning × belief

> 기억 하나 = 무엇(CLIP 이미지 임베딩 e_i), 어디(위치 μ_i와 공분산 Σ_i, 칼만 필터), 얼마나 확실(로그 오즈 l_i, 베이즈 필터). 질문 q가 오면 CLIP 텍스트 임베딩과의 코사인 유사도를 softmax로 바꾸고 존재 확률 p_i를 곱해 순위 → 상위 3개를 차례로 방문. 이후 §3에서 e_i, μ_i/Σ_i, l_i를 각각 어떻게 갱신하는지.

---
§3 Method
## System Overview
### From one question to one cup

(그림: 가운데 가로축 = 진행 단계 0. Remember(점선, 사전 주행) → 1. Ask → 2. Rank → 3. Drive → 4. Re-check → 5. Report. 각 단계 위에 Software 노드, 아래에 Middleware → Hardware 노드. 맨 아래 OS 띠. Software: NanoOWL · CLIP, objmem while driving / faster-whisper / CLIP text × belief / gridnav (4 commands), AMCL on Cartographer map / look ±15° × 3, NanoOWL + CLIP / map view (orange path), live video. Hardware: D455f depth, Jetson GPU / Laptop mic / Jetson Xavier NX / LDS-02 · OpenCR / D455f / Laptop. 직접 만든 노드는 마룬)

Fig. 3. Pipeline. Maroon (the only accent color) = what we built; the rest is off-the-shelf [3], [4], [6].

>> Off-the-shelf perception, our own memory and motion

> 가운데 파란 축이 진행 단계. 0단계(점선)는 질문 전에 돌아다니며 기억해 두는 단계: D455f depth로 물체 위치를 재고, 직진 중에도 기억(회전 중만 건너뜀). 질문은 노트북 faster-whisper → SSH → /query. CLIP × 믿음으로 순위(식 1). 이동은 Cartographer 지도 위에서 AMCL로 위치를 잡고 gridnav(직진·좌90°·우90°·정지 네 가지 명령)로. 도착하면 좌우 15°씩 3번 둘러보고 NanoOWL+CLIP으로 재확인. 마룬이 직접 만든 부분.

---
§3.1 Method
## From Camera to Map
### Pixel + depth → one point on the map

(a) Detection + depth
![[d455_nanoowl.jpg]]
(b) One matrix per hop
(그림: Pixel (u, v, Z) —K⁻¹→ Camera —B→ Robot —A→ Map)
$$ \mathbf{p}_{cam} = Z\,K^{-1}\,[\,u,\ v,\ 1\,]^{\top} $$ (2)
$$ \mathbf{p}_{map} = A\,B\,\mathbf{p}_{cam}, \qquad T = \begin{bmatrix} R & \mathbf{t} \\ \mathbf{0}^{\top} & 1 \end{bmatrix} $$ (3)

Fig. 4. (a) NanoOWL [3] box with D455f depth (11/24). (b) Back-projection, then homogeneous transforms [7].

>> Homogeneous coordinates: one matrix per hop

> (a) 11/24 실측 화면: NanoOWL 상자 + D455f 거리. 검출+거리 한 장 약 0.08초. (b) 식 (2) 역투영은 강의 밖 우리 추가분. 식 (3)은 강의의 Combining Transformations 그대로. A = AMCL 로봇 자세, B = 카메라 장착 위치(실측), K = 카메라 내부 값. B와 K를 재지 않으면 어떻게 되는지는 §5 Case 1.

---
§3.2 Method
## Is the Cup Still There?
### Static state binary Bayes filter, in log odds [1]

$$ l_t = l_{t-1} + \log \frac{p(z \mid \text{present})}{p(z \mid \text{absent})} $$ (4)
- Seen : **+2.08**
- In view, not seen : **−1.50**
- Objects move → prediction step (decay)

(그림: 예시 — 존재 확률 p를 관측마다 그린 계단 그래프. seen, seen → p 0.89, 0.98 / 컵을 옮긴 뒤 miss 3번 → 0.94, 0.76, 0.42. p = 0.5 점선)

Fig. 5. Example sequence: two looks, then the cup is moved — three misses bring p below 0.5.

>> Seen raises the belief, missing lowers it

> 강의(L06)의 static state binary Bayes filter와 같은 필터. p(z|present)=0.8, p(z|absent)=0.1 → 보면 ln 8 = +2.08, 시야 안인데 못 보면 ln(2/9) = −1.50. 그림은 이 두 값으로 계산한 예시(l: 0 → 2.08 → 4.16 → 2.66 → 1.16 → −0.34). 시간 감쇠는 강의 밖 추가분: 물건은 "world is static" 가정을 깨므로 예측 단계를 넣음.

---
§3.3 Method
## Where Exactly Is It?
### Kalman filter correction — the cup does not move [1]

$$ K_t = \bar{\Sigma}_t\,(\bar{\Sigma}_t + Q_t)^{-1} $$ (5)
$$ \mu_t = \bar{\mu}_t + K_t\,(z_t - \bar{\mu}_t) $$ (6)
$$ \Sigma_t = (I - K_t)\,\bar{\Sigma}_t $$ (7)

(그림: 1D 가우시안 세 개 — 기억 N(8, 4), 새 관측 N(6, 1), 합친 결과 N(6.4, 0.8))

Fig. 6. 1D example from the lecture [7]: the fused estimate is a weighted mean.

>> Every look shrinks Σ

> 강의 칼만 필터의 correction step에서 C_t = I, 예측은 그대로(물체는 정지). 측정 잡음은 강의 표기대로 Q_t, 멀수록 커짐(거리 σ = a + b·r², 방향 σ = r·σ_bearing). 그림은 강의 1D 예제 숫자. 새 관측을 어느 기억에 합칠지는 마할라노비스 거리로 정함 → Q_t를 실제보다 작게 잡으면 생기는 일은 §5 Case 4.

---
§3.4 Method
## Localization and Navigation
### Two maps, two jobs : full map → AMCL, aisle map → planning

(그림: 블록도 — Cartographer [4] (graph-based SLAM) → Full map(그림) → AMCL = MCL (predict · weight · resample) → pose / Full map → make_nav_map → Aisle map(그림) → gridnav: A*, 90° corners only → 4 commands: forward · left 90° · right 90° · stop → arrive: look ±15° × 3 → re-check. AMCL pose → gridnav 폐루프)
$$ e_{\perp} \approx s \cdot \sin \Delta\theta $$ (8)

Fig. 7. Localization uses the full map; planning uses only the aisles. Eq. (8): every turn adds heading error, so every turn is exactly 90°.

>> Known map → errors stop piling up

> Cartographer = 강의 Three Traditional Paradigms 중 graph-based. 2D LiDAR는 책상 윗판을 못 보고, 회색(unknown)을 빈 곳으로 읽으면 안 됨 → 실제 지나간 통로만 남긴 지도를 따로 만듦. 단, 통로 지도는 경로 계획에만 쓰고 AMCL에는 원본 지도를 줌(이유는 Case 3). AMCL은 강의의 MCL 그대로. 식 (8)은 강의 odometry motion model: 회전할 때마다 방향 오차, 이동 거리가 그걸 옆 오차로 키움(5 m: 1° → 9 cm, 5° → 44 cm). Nav2는 좁은 통로에서 경로를 못 만들거나 목표 0.31 m 앞에서 포기 → gridnav: A*로 직진과 90° 꺾임만 있는 경로, AMCL 자세를 보며 "축 방향으로 회전 → 모서리까지 직진" 반복. 보내는 명령은 네 가지뿐.

---
§4 Experiments
## Real-Robot Run (11/28)
### First full run : see → remember → ask → drive → re-check

[[사진 3]]
(Table 1 위: 실험에 쓴 로봇 — 0.815 m 기둥, D455f, LDS-02가 보이게)

Table 1. Setup.
| | |
|---|---|
| Robot | TurtleBot3 Waffle Pi |
| Compute | Jetson Xavier NX · ROS 2 Foxy |
| Camera | RealSense D455f, 640×480, 0.815 m |
| LiDAR / map | LDS-02 · room_l4, 13.9 × 7.8 m |
| Objects | cup, laptop |

Table 2. Queries (planned path turns, drive time, belief at the found object).
| Query | Turns | Time | p | Result |
|---|---|---|---|---|
| cup | 2 | 93 s | 0.84 | found |
| laptop | 3 | 112 s (+42 s) | 0.67 | found |
| cup | 3 | 100 s | 0.87 | found |
| Demo Day (12/03) | | | | [ ___ / ___ ] |

>> ==3 / 3== found on the first full run

> 11/28 새벽 실제 로봇에서 처음으로 전체 흐름 성공. 질문 3개 모두 found: 00:43 컵 93초 확신도 0.84(경로 +x → −y → +x, 꺾임 2번), 01:31 노트북 112초 + 42초 확신도 0.67(꺾임 3번), 01:35 컵 100초 확신도 0.87(꺾임 3번). 실시간 영상 초당 10장. 데모데이(12/03) 결과로 마지막 줄을 채움.

---
§4 Experiments
## Ablation in Simulation
### Toy world, 5 seeds × 20 queries — compare, do not read absolute values

(a) Search : which memory?
(그림: 막대 — top-1: CLIP 95.0% vs label match 43.0%)
(b) After moving 4 objects
(그림: 막대 — moved object top-1: probabilistic 100% vs similarity only 50%, visits per query 1.00 vs 1.80)
[[영상 2]]
(데모데이: 컵을 옮긴 뒤 같은 질문 → 예전 자리 실패 → 새 자리)

Fig. 8. (a) Text-image similarity beats label matching. (b) Lowering the old belief finds the moved object on the first visit.

>> Lowering the old belief finds the new place

> 장난감 세계 시뮬레이션(depth 카메라 설정): 위치가 완벽하고 가림이 없어서 절대값보다 비교가 의미. (a) 검색: CLIP 95.0% vs 라벨 일치 43.0%(top-1). CLIP이 틀린 5%는 "phone charger"를 물으면 phone이 1등. (b) 물체 4개를 옮기고 다시 순찰한 뒤: 확률 메모리는 옮긴 물체를 첫 방문에 100% 찾고(질문당 방문 1.00), 유사도만 쓰면 50%(1.80). 데모데이 영상으로 실제 확인.

---
§5 Failure Analysis
## 40 Problems, 4 Broken Assumptions
### Most real-robot bugs broke an assumption of the theory

(그림: 가로 누적 막대 하나 — Software 21 / Hardware 7 / Network & tools 7 / Middleware 5)

Table 3. Four cases and the assumption each one broke.
| Case | Symptom | Broken assumption | Theory |
|---|---|---|---|
| 1 Sensing | camera can't see desk tops | B, K are known | camera model, Eq. (2)–(3) |
| 2 Odometry | L-shaped drive → straight map | odom follows the wheels | motion model, Eq. (8) |
| 3 Localization | pose 1.8 m off | the map is informative | MCL weights, Eq. (9) |
| 4 Association | one cup → 3 memories | Q_t matches real noise | Kalman, Eq. (10) |

>> Find the layer first, then the bug

> 트러블슈팅 기록 40건을 층별로 분류. Software 21: 6, 10, 11, 12, 15, 18, 22, 24, 25, 26, 28~32, 34~38, 40 / Hardware 7: 7, 8, 13, 16, 17, 27, 33 / Network & tools 7: 1~5, 9, 39 / Middleware 5: 14, 19, 20, 21, 23(나중에 켠 노드가 /odom을 못 찾던 DDS 문제 포함). 1~33번은 이전 개수(15/7/6/5)에 맞게 분류, 34~40번을 더함. 그중 이론의 가정을 깬 네 사례를 다음 네 장에서 (a) 증상 → (b) 진단 → (c) 해결 순서로. 그 밖에 설계를 바꾼 것: 음성인식은 메모리 한계로 노트북으로, 워커 재시작 시 GPU 메모리 부족은 파일 캐시 1.3 GB를 모델 로딩 중 비워서 해결.

---
§5 Failure Analysis
## Case 1 : Sensing — B and K
### Stock camera too low, bearing-only camera, placeholder intrinsics

(a) Camera too low → mast
[[사진 4]]
(로봇 옆모습, 기둥)
(그림: 옆에서 본 로봇 — 기본 카메라 시선은 책상 옆면에 막힘, 기둥 위 카메라(0.815 m)는 책상 위 컵을 봄. 기본 높이 [ ___ m ])
(b) Bearing-only → range-bearing
(그림: C920 — 통로에서 거의 평행한 두 시선, 길쭉한 오차 타원 / D455f — 한 번에 거리+방향)
(c) Placeholder K
(그림: 시야각 부채꼴 두 개 — fx 615 → 55° (implied) vs fx 386.98 → 79.2° (measured))

Fig. 9. (a) A 0.815 m mast enters B. (b) Two near-parallel sight lines leave ≈ 0.5 m error along the line. (c) A placeholder f_x skews every bearing by ≈ 60%.

>> Measure B and K — never assume them

> 가정: 식 (2)–(3)의 K와 B를 안다. (a) 기본 카메라 자리는 너무 낮아 책상 윗면이 안 보임 → 기둥 위로 올림, 높이 실측 0.815 m(수평). 기둥이 LiDAR에 잡힐까 봐 필터를 만들어 뒀지만 LiDAR 데이터로 먼저 확인: 스캔 60개, 0.418 m 안쪽에 반복해서 찍히는 점 없음 → 필터 끔(16번). C920(약 160 g)이 흔들려 기둥 보강(17번). (b) 강의 Range-Bearing Model: 방향만 재는 C920은 통로에서 두 시선이 거의 평행 → 3 m 앞 물체가 약 0.5 m 오차 → D455f로 거리까지. (c) 설정 파일의 fx 615는 D435 기준 임시값, D455F 640×480 실측 386.98(시야각 79.2°). 임시값이면 좌우 방향이 약 60% 어긋남(33번). 55°는 fx 615와 폭 640에서 계산한 시야각.

---
§5 Failure Analysis
## Case 2 : Odometry — The Map That Wouldn't Turn
### The wheels turned, odometry did not

(a) Symptom
![[map_straight.png]]
(b) Diagnosis
(그림: 표 — Wheels +29° / odom (driver) ==+0.0°==. 아래: 위에서 본 로봇, 앞의 물체가 LiDAR 185°에 보임)
(c) Fix
![[room_l4_full.png]]
- heading from wheels : +28.4°
- rotate the scan 180°

Fig. 10. (a) L-shaped drive, straight map (11/25). (b) Odometry froze; the LiDAR was mounted backwards. (c) After both fixes: straight walls, 0.14 m loop error.

>> Check odometry before blaming SLAM

> 가정: 식 (8)의 motion model은 odom이 바퀴를 따라간다고 봄. (a) ㄱ자로 운전했는데 지도는 일자(11/25). (b) 원인 1: 로봇 드라이버의 odom 방향이 멈춤. 11/25(바퀴 +97.7°, IMU +91.7°, odom 0°), 11/27, 11/28 세 번 반복. 11/28: 바퀴 29° 회전에 odom +0.0°, 바퀴 각도(/joint_states)는 항상 맞음. 원인 2(11/27): LiDAR가 180° 반대로 달림. 앞 0.44 m 물체가 185°에 보였고, 10.7 cm 전진하자 10.5 cm 가까워짐 → 0°가 로봇 뒤. (c) 바퀴 각도로 odom을 직접 계산(differential drive) → +28.4°(바퀴 계산 29°), 스캔은 소프트웨어로 180° 돌림. 결과 room_l4: 13.9 × 7.8 m, 벽 직선, 출발점 복귀 오차 0.14 m.

---
§5 Failure Analysis
## Case 3 : Localization — Right Map, Wrong Place
### AMCL on the aisle-only map → ==1.8 m== off

(a) Symptom
![[room_l4_aisle.png]]
(b) Diagnosis
$$ w_t^{[m]} = p\big(z_t \mid x_t^{[m]},\, m\big) $$ (9)
(그림: 막대 — scan on walls: AMCL pose 38% vs re-localized 86%)
(c) Fix
[[사진 2]]
(RViz: 원본 지도 위에 AMCL 파티클이 모인 화면)

Fig. 11. (a) The aisle map was given to AMCL: walls everywhere. (b) Every particle fits, so weights carry no information. (c) Full map → AMCL, aisle map → planning only; residual 3 cm, 2°.

>> A map that fits everywhere tells nothing

> 가정: 식 (9)의 likelihood field가 파티클을 구별해 준다. (a) 몇 m 주행 뒤 지도 화면의 로봇이 실제와 다른 책상 줄(1.8 m 차이), 그 위치로 기억한 컵도 엉뚱한 곳. AMCL에 통로만 남긴 지도를 줬음. (b) 통로 밖이 전부 벽이라 어느 파티클이든 스캔이 잘 맞아 보임 → 가중치가 고만고만 → 사실상 바퀴 기록만 따라감. 확인: 현재 스캔을 원본 지도 전체에 맞춰 봄. AMCL이 믿는 위치는 스캔의 38%만 벽에 닿고, 다시 찾은 위치는 86%. (c) 위치 추정은 원본 지도, 경로 계획만 통로 지도. 주행 후 AMCL과 스캔 맞춤 차이 3 cm, 2°. 위치 보정 도구 relocalize.sh: 처음 위치를 몰라도 스캔을 지도 전체에 맞춰 AMCL에 알려 줌(9초). (트러블슈팅 34)

---
§5 Failure Analysis
## Case 4 : Association — One Cup, Many Memories
### Q_t smaller than reality → one cup splits

(a) Symptom
[[사진 5]]
(실시간 영상: 컵 하나에 상자 두 개 — 몸통 / 빨대까지)
(그림: 같은 컵을 두 위치에서 봄 — 작은 타원 두 개가 겹치지 않아 기억 2개)
(b) Diagnosis
$$ d = \sqrt{(z_t - \mu)^{\top} (\Sigma + Q_t)^{-1} (z_t - \mu)} \;\le\; \gamma $$ (10)
(c) Fix
Table 4. Parameters before → after.
| | before | after |
|---|---|---|
| box IoU (dedup) | 0.7 | 0.5 |
| σ_bearing (rad) | 0.03 | 0.06 |
| σ_range (m) | 0.02 | 0.05 |
| gate γ | 3.0 | 4.0 |

Fig. 12. (a) One cup became 2–3 memories 10–20 cm apart. (b) With Q_t too small, the gate (10) rejects the same cup seen from elsewhere. (c) Q_t raised to the real error.

>> An overconfident Q_t splits one object

> 가정: 식 (5)의 Q_t가 실제 잡음과 같다. (a) 11/28: 같은 컵이 10~20 cm 간격으로 기억 2~3개. (b) 원인 1: NanoOWL이 컵 몸통과 빨대까지 포함한 컵을 각각 상자로 냄, 두 상자 IoU 약 0.5라 기존 기준 0.7로는 둘 다 남음. 원인 2: 새 관측을 같은 물체로 볼지는 식 (10)의 마할라노비스 거리. Q_t(방향 1.7°, 거리 2 cm)가 실제 오차(AMCL 방향만 1~2°, 여기에 장착 오차)보다 작아서 다른 위치에서 본 같은 컵을 "다른 물체"로 판단. (c) 표 4: IoU 0.5(작은 상자가 80% 이상 큰 상자 안이면 제거), σ_bearing 0.03→0.06 rad, σ_range 0.02→0.05 m, γ 3.0→4.0, CLIP 유사도 기준 0.80→0.75. 효과는 한 번의 주행에서만 확인(한계).

---
§6 Conclusion
## Limitations and Conclusion

|||
**Limitations**
- Monitor detected as a **laptop**
- Merge fix checked in **one run** only
- 2D LiDAR : aisles only, desk tops unseen
|||
**Conclusion**
- Probabilistic memory works on a real robot : **3 / 3**
- Most bugs broke an **assumption** of the theory
- Keep uncertainty explicit — and **honest**

Future work : VIO (not tried)

>> Thank you

> 한계: (1) 실습실 모니터가 "a laptop"으로 잡혀 노트북 기억이 여러 개(11/28 노트북 기억 19개 중 대부분) → 질문 때 모니터로 갈 수 있음. (2) 같은 물체가 기억 여러 개로 나뉘던 문제의 수정 효과는 한 번의 주행으로만 확인. (3) 2D LiDAR라 통로만 다니고 책상 윗판은 못 봄. 투명한 컵은 depth가 깨짐. 결론: 확률 기억은 실제 로봇에서 동작(3/3), 문제 대부분은 이론의 가정(B·K, odom, 지도, Q_t)이 깨진 것, 불확실성은 명시적으로 그리고 실제만큼 크게. 향후 과제: VIO(카메라+IMU 위치 추정)는 시도하지 않았음. 질문 받는 동안 이 화면 유지.

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
