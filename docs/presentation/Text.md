---
title: "Where Is My Cup?"
subtitle: "A Robot That Remembers Where Things Are"
eyebrow: "2026 Fall · Intelligent Robotics"
speaker: "Speaker : Team 6"
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
### Where did I leave my **red cup**?

- Cup, charger, earphones
- I saw it — but **where**?

[[사진 1]]
(오른쪽 절반: 책상 위 빨간 컵 사진, 데모데이에 촬영)

>> What if a robot remembered for me?

> 실제 경험으로 시작. 분명 봤는데 어디였는지 기억이 안 난다.

---
## A Robot That Remembers
### See → Ask → Go

(그림: 카드 3장 — See: patrol, remember what & where / Ask: "Where is the red cup?" / Go: drive there, look again)

>> Remember with **probability**, not certainty

> 순찰하면서 본 물건을 위치와 함께 기억. 말로 물으면 그 자리로 가서 다시 확인. 핵심은 "확률로 기억한다" → 2부로 연결.

---
## System Overview
### From one question to one cup

(그림: 6단계 × 3층 표. 단계 Remember(회색, 사전 순찰) / Ask / Rank / Drive / Re-check / Report, 층 Software / Middleware / Hardware. 직접 만든 칸은 마룬: objmem, score, gridnav, re-check)

> 표를 왼쪽에서 오른쪽으로 한 번 훑기. 질문은 노트북 faster-whisper → SSH → /query. CLIP으로 순위, gridnav로 이동, 도착하면 NanoOWL+CLIP으로 재확인. 직접 만든 부분은 마룬.

---
## From Camera to Map
### Pixel + depth → one point on the map

$$ \mathbf{p}_{cam} = Z\,K^{-1}\,[\,u,\ v,\ 1\,]^{\top} $$
$$ \mathbf{p}_{map} = A\,B\,\mathbf{p}_{cam}, \qquad T = \begin{bmatrix} R & \mathbf{t} \\ \mathbf{0}^{\top} & 1 \end{bmatrix} $$

(그림: Pixel (u, v, Z) —K⁻¹→ Camera —B→ Robot —A→ Map)

>> Homogeneous coordinates: one matrix per hop

> 첫 식(역투영)은 강의 밖 우리 추가분. 둘째 식은 강의의 Combining Transformations 그대로. A = AMCL 로봇 자세, B = 카메라 장착 위치(실측).

---
## Is the Cup Still There?
### Static state binary Bayes filter, in log odds

|||
**Is it there?**
$$ l_t = l_{t-1} + \log \frac{p(z \mid \text{present})}{p(z \mid \text{absent})} $$
- Seen: **+2.08**
- In view, not seen: **−1.50**
- Cups move → prediction step
|||
**Which one?**
$$ \text{score}_i = \operatorname{softmax}\!\Big(\tfrac{\cos(\text{CLIP}(q),\, e_i)}{T}\Big)\cdot p_i $$
- Top 3 → visit in order

>> Seen raises the belief, missing lowers it

> 강의(L06)의 static state binary Bayes filter와 같은 필터. p(z|present)=0.8, p(z|absent)=0.1 → 보면 ln 8, 못 보면 ln(2/9). 시간 감쇠는 강의 밖 추가분: 컵은 "world is static" 가정을 깨므로 예측 단계를 넣음. 오른쪽: CLIP 유사도 × 존재 확률.

---
## Where Exactly Is It?
### Kalman filter correction — the cup does not move

$$ K_t = \bar{\Sigma}_t\,(\bar{\Sigma}_t + Q_t)^{-1} $$
$$ \mu_t = \bar{\mu}_t + K_t\,(z_t - \bar{\mu}_t) \qquad \Sigma_t = (I - K_t)\,\bar{\Sigma}_t $$

(그림: 1D 가우시안 세 개 — 기억 N(8, 4), 새 관측 N(6, 1), 합친 결과 N(6.4, 0.8). "It's a weighted mean")

>> Every look shrinks Σ

> 강의 칼만 필터의 correction step에서 C_t = I, 예측은 그대로(물체는 정지). 측정 노이즈는 강의 표기대로 Q_t, 멀수록 커짐. 그림은 강의 1D 예제 숫자.

---
## Mapping and Localization
### Graph-based SLAM, then Monte Carlo Localization

|||
**Mapping**
![[room_l4_full.png]]
![[room_l4_aisle.png]]
- Graph-based SLAM · loop closure
- Unknown ≠ free → aisles only
|||
**Localization (AMCL = MCL)**
(그림: Predict — odometry motion model → Weight — likelihood field → Resample — low variance)
[[사진 2]]
(AMCL 파티클이 모이는 화면 캡처, 데모데이)

>> Known map → errors stop piling up

> Cartographer = 강의 Three Traditional Paradigms 중 graph-based. 2D LiDAR는 책상 윗판을 못 보고, 회색(unknown)을 빈 곳으로 읽으면 안 됨 → 실제 지나간 통로만 남김. AMCL은 강의의 MCL 그대로.

---
## 26 Problems at a Glance
### Grouped by layer

(그림: 막대 4개 — Software 10, Lab network & tools 6, Hardware 5, Middleware 5. 막대 옆에 대표 사례 키워드)

>> Find the layer first, then the bug

> 트러블슈팅 기록 26건을 층별로 분류. 다음 네 장에서 대표 사례.

---
## Case 1 : The Map That Wouldn't Turn
### A 90° turn, 0° in odometry

![[map_straight.png]]
(그림: 표 — Wheels +97.7° / IMU +91.7° / odom 0° → heading from wheels: +91.6°)
$$ \theta = \int \omega\, dt, \qquad \omega = \frac{v_r - v_l}{l} $$

>> Check odometry before blaming SLAM

> ㄱ자로 운전했는데 지도는 일자. 원인은 SLAM이 아니라 odometry: 방향을 IMU로 계산하는 설정이 간헐적으로 0. 바퀴로 방향 계산(differential drive)하자 해결.

---
## Case 2 : Only 90° Turns
### Every turn adds heading error

(그림: 직진 계획선 vs Δθ 틀어진 실제 선, 옆 오차 e⊥)
$$ e_{\perp} \approx s \cdot \sin \Delta\theta $$
- 5 m: 1° → **9 cm**, 5° → **44 cm**

|||
**Mapping — teleop4**
straight · 90° · stop
|||
**Navigation — gridnav**
grid path · pose from AMCL
[ return error : ___ m ]

>> Every turn adds error — so every turn is exactly 90°

> 강의 odometry motion model: 회전할 때마다 방향 오차(α), 이동 거리가 그걸 옆 오차로 키움. 그래서 지도 그릴 때도, 찾아갈 때도 직진과 정확한 90° 회전만. 위치는 AMCL(지도 기준)이라 바퀴 오차가 쌓이지 않음. 복귀 오차는 데모데이 실측.

---
## Case 3 : Nodes That Couldn't Hear
### More processes → late nodes find nobody

(그림: 포트 칸 — 기본은 앞 몇 칸만 탐색, 나중에 켠 노드는 범위 밖 / 수정 후 40칸)

- Cause: loopback discovery probes **few ports**
- Fix: **one** wider DDS profile for all

>> Same symptom three times — fix the middleware, not the node

> 프로그램을 많이 켤수록 나중에 켠 노드가 /odom, /map을 못 찾음. Fast DDS가 루프백에서 앞번호 포트 몇 개만 두드리기 때문. 모든 프로세스에 같은 설정(40개 포트) → /odom 10초에 184개, 지도 저장 즉시 성공.

---
## Case 4 : Design Changed by Constraints
### C920 → D455f : bearing-only → range-bearing

(그림: 왼쪽 C920 — 통로에서 거의 평행한 두 시선, 시선 방향으로 긴 오차 타원 / 오른쪽 D455f — 한 번에 거리+방향, 작은 타원)

- detectNet → **NanoOWL** (clear bottle missed)
- Whisper → **laptop** (4.2 / 6.8 GB)

>> A direction is not a position

> 강의 Range-Bearing Model: 방향 측정은 시선에 수직인 방향만 잡아 줌. 통로에서는 두 시선이 거의 평행 → 3 m 앞 컵이 약 0.5 m 오차. D455f는 한 번에 위치. (같은 시기에 카메라 장착 방향도 바로잡음.) 메모리 한계로 음성인식은 노트북으로.

---
## Measured on the Robot

(그림: 숫자 4개 — 0.09 m Nav2 1 m goal error / 90.9° odom for a 90° turn / 0.08 s detection + depth per frame / 4.2 GB vision worker)

[[영상 1]]
(데모데이: "Where is the red cup?" → 이동 → 찾음)

- Demo Day success : [ ___ / ___ ]

> 실측 숫자 네 개. 데모데이 영상 재생. 성공률은 데모데이 결과로 채움.

---
## Why Probabilistic Memory Helps
### After moving objects (simulation, 5 seeds × 20 queries)

(그림: 막대 — moved object top-1: probabilistic 100% vs similarity only 50%, visits per query 1.00 vs 1.80)

[[영상 2]]
(데모데이: 빨간 컵을 옮긴 뒤 같은 질문 → 예전 자리 실패 → 새 자리)

>> Lowering the old belief finds the new place

> 장난감 세계 시뮬레이션: 위치가 완벽해서 절대값보다 비교가 의미. 옮긴 물체는 확률 메모리가 한 번에 찾음. 데모 영상으로 실제 확인.

---
## Limitations and Lessons

|||
**Limitations**
- Clear cups break depth
- Aisles only
- Desk tops invisible to 2D LiDAR
|||
**Lessons**
- Check the layer below first
- Simple motion in tight spaces
- Keep uncertainty explicit

>> Thank you

> 한계 세 개, 배운 점 세 개. 질문 받는 동안 이 화면 유지.

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
