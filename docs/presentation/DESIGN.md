---
version: 3.0
name: uos-seminar
description: 서울시립대 발표 덱 표준. v3.0 흑백 톤: 흰 바탕, 검정 제목, 회색 단계, 강조색은 마룬 하나를 필요한 곳에만. Noto Serif. v2.0부터 논문 리뷰 형식(섹션 표시, 번호 붙은 그림·표·수식, 패널 (a)(b)(c), 3선 표).
source: "Seminar_8_05 (2026-08-05 'Trajectory Tracking and Control', 36장) 최종본 HTML에서 실제 값을 추출. 7/15 ISAC 덱과 handoff/template.md로 교차 확인."
confirmed: 2026-11-27
revised: 2026-11-28 (v2.0 논문 리뷰 형식, 글꼴 Noto Serif / v3.0 흑백 톤 + 강조색 하나)

canvas:
  size: 1920x1080px        # 16:9. PPTX: 13.333in x 7.5in
  px-to-pt: 0.5            # 1920px = 13.333in -> 1px = 1/144in = 0.5pt
  content-width: 1288px    # 좌우 패딩 316px. 8/5 덱 그대로 (본문 폭 = 4:3 시절과 같음)
  pad: { top: 52px, x: 316px, bottom: 60px }      # 기본
  pad-dense: { top: 44px, x: 316px, bottom: 52px } # 도식 + 표처럼 빽빽한 장

colors:
  title-ink: "#1a1a1a"     # v3.0: 제목, 컬럼 제목, Part 표지 배경, 번호 (v2.0까지 UOS 블루 #004094)
  maroon: "#8C2D2D"        # v3.0: 유일한 강조색. 쓰는 곳은 10장 규칙(장당 1~2곳)
  ink: "#222222"           # 본문
  bullet: "#111111"        # 불릿 점. 컬러 불릿 쓰지 않음
  callout-ink: "#2a2a2a"   # >> 문구
  sub-ink: "#444444"       # 하위 불릿 글자
  sub-dash: "#777777"      # 하위 불릿 대시
  summary: "#8c8c8c"       # ### 요약줄, 표지 발표자
  footer: "#a6a6a6"        # footer 글자, 표지 날짜
  caption: "#999999"       # 이미지 출처
  rule: "#e5e5e5"          # footer 위 선, 2단 구분선
  rule-soft: "#ececec"     # Outline 행 구분선, 카드 테두리
  img-border: "#e3e3e3"
  card-bg: "#fafafa"
  tone-gray: { bg: "#f1f1f1", border: "#a6a6a6" }
  tone-maroon: { bg: "#f5eae9", border: "#cf9a9a" }
  part-label: "#cfcfcf"    # Part 표지 "PART N"
  part-sub: "#d9d9d9"      # Part 표지 부제
  diagram:
    ink: "#2b2b2b"         # 도식 속 물체·굵은 선
    line: "#b3b3b3"        # 벽, 틀, 축
    flow: "#9a9a9a"        # 흐름 화살표 (점선 9 7)
    label: "#6b6b6b"       # 도식 아래 설명
    group-label: "#6b6b6b" # 블록 묶음 라벨 (CONTROLLER 등)
    block-main: { fill: "#f1f1f1", stroke: "#a6a6a6" }
    block-neutral: { fill: "#fafafa", stroke: "#cccccc" }
    block-muted: { fill: "#ffffff", stroke: "#d6d6d6" }
    hi-gray: "#f3f3f3"
    hi-maroon: "#f0dedd"
    math: "#1a1a1a"

fonts:
  serif: "'Noto Serif', serif"   # v2.0: 슬라이드 글꼴. 한글(노트)은 Noto Sans KR
  math: "Georgia, 'Times New Roman', serif"           # 본문 속 그리스 문자·변수는 이탤릭 세리프
  display-math: KaTeX
  weights: { regular: 400, medium: 500, semibold: 600, bold: 700 }  # 700은 슬라이드 제목·라벨에만

type:                      # px (pt = px x 0.5)
  cover-eyebrow: { size: 24, weight: 700, color: "#6b6b6b", tracking: 0.32em, case: upper }
  cover-title:   { size: 60, weight: 600, color: title-ink, lh: 1.16, max-width: 1180 }
  cover-speaker: { size: 26, color: summary }
  cover-date:    { size: 20, color: footer }
  part-label:    { size: 30, weight: 700, color: part-label, tracking: 0.5em }
  part-title:    { size: 104, weight: 600, color: "#ffffff" }
  part-sub:      { size: 36, style: italic, color: part-sub }
  outline-title: { size: 50, weight: 700, color: title-ink }
  outline-part:  { size: 27, weight: 700, color: title-ink, width: 132 }
  outline-name:  { size: 31, weight: 500, color: ink }
  slide-title:   { size: 44, weight: 700, color: title-ink, lh: 1.1 }   # 빽빽한 장 42
  summary:       { size: 27, color: summary, margin-top: 8 }            # 26~25까지 줄여도 됨
  body:          { size: 27, lh: 1.35 }    # 26~25 (항목 많을 때), 2단 안에서는 24
  sub:           { size: 23, lh: 1.35, color: sub-ink }
  col-title:     { size: 29, weight: 700, color: title-ink, margin-bottom: 18 }
  callout:       { size: 29, weight: 500, color: callout-ink }
  card-title:    { size: 27, weight: 700, color: title-ink }
  card-sub:      { size: 20, color: "#555555" }
  caption:       { size: 16, style: italic, color: caption }   # 17까지
  footer:        { size: 18, color: footer }
  reference:     { size: 20, lh: 1.34, color: "#333333" }      # 많으면 19
  diagram-label: { size: 19, color: diagram.label }
  diagram-block: { size: 18, weight: 600 }
  section-tag:   { size: 17, weight: 700, color: diagram.group-label, tracking: 0.08em, case: upper }  # v2.0 제목 위 "§3.2 Method"
  fig-caption:   { size: 18, lh: 1.35, color: "#444444" }   # "Fig. n." 은 700, ink
  panel-label:   { size: 19, weight: 700, color: ink }      # "(a) Symptom"
  table-paper:   { size: 20, head-weight: 700, rule-outer: "2px #222222", rule-head: "1px #222222" }
  eq-number:     { size: 22, color: summary }               # 수식 오른쪽 끝 "(n)"
---

# UOS 발표 덱 표준 디자인

서울시립대 발표(세미나, 수업 발표)에 계속 쓰는 표준이다. 값은 2026-08-05 세미나 덱 최종본에서 그대로 뽑았다. 새 덱은 이 문서의 값만 쓴다.

원고 기호는 같은 폴더의 `Rules.md`를 따른다.

## 1. 톤

- v3.0: **흑백 톤**. 흰 바탕, 검정 제목, 나머지는 회색 단계. 색은 강조가 꼭 필요한 곳에만 마룬 하나(10장).
- 강의 자료처럼 본문이 세로로 꽉 차게 한다. 본문 영역은 flex로 세로 중앙에 둔다.
- 그림자, 그라데이션, 제목 밑줄은 쓰지 않는다.
- 한 장에 주장 하나. 문구는 되도록 한 줄로 끝낸다.

## 2. 캔버스와 단위

- 1920 x 1080 (16:9). 본문 폭 1288px, 좌우 패딩 316px.
- PPTX로 옮길 때 1px = 0.5pt = 1/144in. 제목 44px은 22pt, 본문 27px은 13.5pt.
- 같은 도식이 연속된 장에 나오면 크기와 위치를 똑같이 둔다 (넘길 때 튀지 않게).

## 3. 슬라이드 종류

### 표지
- 가운데 정렬, 패딩 70px 320px.
- v3.0: 학교 엠블럼 대신 **프로젝트 대표 이미지**(11장). 아래 v1.0 배치는 참고용: UOS 엠블럼(261px, 아래 22px) → eyebrow(예: `2026 FALL · INTELLIGENT ROBOTICS`) → 제목 → 검정 선(130 x 3px, 위아래 44px) → `Speaker : 이름` → 날짜.
- 엠블럼 파일: 같은 폴더의 `emblem.png`.

### Outline
- 제목 `Outline` 50px. 아래에 Part 행을 최대 폭 960px로 세로 중앙.
- 행: 위아래 패딩 27px, 아래 1px `rule-soft` 선(마지막 행은 선 없음). `Part N`(검정 27px 700, 폭 132px) + 이름(31px 500), 간격 30px.

### Part 표지
- 배경 #1a1a1a(v2.0까지 UOS 블루), 가운데 정렬.
- `PART N`(30px, 자간 0.5em) → 반투명 흰 선(220 x 2px, rgba(255,255,255,0.5), 위아래 44px) → 제목 104px 600 → 이탤릭 부제 36px(위 40px).

### 본문 장 (기본)
1. 제목 `##` 44px + 요약줄 `###` 27px.
2. 본문 영역(flex 1, 세로 중앙).
3. `>>` 문구 (있을 때).
4. footer.

### References
- 제목 42px, 아래 24px. 항목 간격 17px.
- 번호 `[n]`은 검정 700, 폭 40px. IEEE 형식, 학술지·학회명은 이탤릭.

## 4. 요소

| 요소 | 규칙 |
|---|---|
| 불릿 | `•` 검정(#111), 점과 글 사이 16px, 항목 사이 20~24px |
| 하위 불릿 | `–` #777, 글 23px #444, 왼쪽 들여쓰기 42px, 간격 14px |
| 굵게 `**` | v3.0: 검정 700(색 없음). 요약줄 안에서는 요약색 600 |
| 강조 `==` | v3.0: 마룬 #8C2D2D 700. 장당 1~2곳(10장) |
| 2단 `\|\|\|` | 박스 없이 두 컬럼, 가운데 1px #e5e5e5 세로선, 각 쪽 52~56px 여백. 컬럼 제목 29px 검정 700 |
| 톤 박스 | "묶어서 표시"일 때만. 회색(#f1f1f1 / #a6a6a6). 마룬 톤(#f5eae9 / #cf9a9a)은 강조 규칙을 따를 때만, 테두리 1.5px, 모서리 16px, 패딩 44 x 46px |
| 정보 카드 | #fafafa, 테두리 1px #ececec, **왼쪽 4px 검정**, 모서리 10px, 패딩 26 x 28px. 강조 카드는 #f1f1f1 바탕 + 왼쪽 4px 검정. 카드 사이 화살표 `→` 40px #8c8c8c |
| `>>` 문구 | 박스 없음. 검정 바(56 x 3px, 모서리 2px) 아래 16px에 29px 500 가운데 정렬. footer 위 34px |
| footer | 18px #a6a6a6, 위에 1px #e5e5e5 선, 선 아래 10px. 세 칸: 왼쪽 소속 / 가운데 짧은 제목 / 오른쪽 `n / N` |
| 이미지 | 테두리 1px #e3e3e3, 모서리 8px. 아래 8~12px에 출처 캡션(`Source : …`) 16px 이탤릭 #999 |
| 사진 자리 `[[사진 n]]` | 점선 테두리 상자 + "사진 n" 라벨. 지침의 크기와 정렬을 반영 |
| 표 | v2.0: 3선 표(booktabs). 위·아래 2px #222, 머리행 아래 1px #222, 세로선과 바탕색 없음, 글 20px. 캡션은 표 **위** `Table n.` (v1.0의 마룬 머리행은 쓰지 않음) |

## 5. 수식

- 한 장에 **결과 수식 1개 + 한 줄 해석**. 유도는 Appendix로.
- 본문 속 변수와 그리스 문자는 Georgia 이탤릭. 독립 수식은 KaTeX.
- 수식 밑에 각 항의 뜻을 작은 회색 글씨로 단다 (8/5 덱 13장 방식).
- PPTX에는 수식을 이미지로 넣는다.

## 6. 도식 (SVG)

- 선: 틀·벽 #b3b3b3 3px, 물체 #2b2b2b 5px(둥근 끝).
- 흐름 화살표: #9a9a9a 3px, 점선 `9 7`, 화살촉은 같은 색 삼각형. 움직임이 필요하면 dashoffset 애니메이션.
- 블록: 모서리 10px. 주요 블록 #f1f1f1 / #a6a6a6(글 검정 600), 보조 블록 #fafafa / #cccccc(글 #2b2b2b), 비활성 블록 흰 바탕 / #d6d6d6(글 #6b6b6b).
- 묶음: 점선 #a6a6a6 사각형(모서리 14px) + 라벨 17px 700 #6b6b6b 대문자, 자간 0.06em.
- 계획(기준)은 회색·검정 점선, 실제(측정)·실패는 마룬 실선.
- 도식 아래 설명 19px #6b6b6b. 컬러 강조는 한두 곳만 마룬.
- PPTX에서는 단순 블록도는 도형으로 다시 그리고(편집 가능), 곡선·애니메이션이 있는 도식은 이미지로 넣는다.

## 7. 산출물

- 원고 `Text.md` 하나에서 HTML, PDF, PPTX(편집형)를 뽑는다.
- 발표자 노트(`>`)는 HTML `data-speaker-notes`와 PPTX 노트란에 넣는다.
- 동반 문서 `발표 노트.md`, `발표 대본.md`, `사진 소싱 가이드.md`는 원고가 바뀌면 함께 고친다.
- PPTX 글꼴: Source Sans 3, Noto Sans KR (둘 다 Google Fonts 무료). 받는 PC에도 설치되어 있어야 같은 모양으로 열린다.

## 8. 하지 말 것

- 마룬 말고 다른 강조색 추가
- 컬러 불릿, 제목 밑줄, 그림자, 그라데이션
- 표지 제목 700 (600이 맞다)
- 슬라이드마다 다른 여백

## 9. 논문 리뷰 형식 (v2.0)

학회 논문을 리뷰하듯 발표한다. 슬라이드 글은 여전히 적게 두고, 설명은 그림과 캡션, 수식 번호, 표가 맡는다.

### 9.1 구성
- 순서: Overview(Fig. 1 티저) → §1 Introduction(문제, 기여) → §2 Formulation(기호) → §3 Method(이론 하나당 한 장) → §4 Experiments(설정 표, 결과 표, ablation) → §5 Failure Analysis(분류 표 + 사례별 그림) → §6 Conclusion → References.
- 모든 본문 장의 제목 위에 **섹션 표시**(`§3.2 Method`)를 단다. 17px 700, #6b6b6b, 대문자, 자간 0.08em, 제목과 간격 6px.

### 9.2 그림
- 한 장의 중심은 그림 하나(`Fig. n`). 번호는 덱 전체에서 이어 붙인다.
- 캡션은 그림 **아래**: `Fig. n.`(700, #222) + 한 문장(18px, #444, 왼쪽 정렬, 그림 폭에 맞춤).
- 여러 칸 그림은 패널 `(a) (b) (c)`. 각 패널 위에 라벨 19px 700 + 짧은 설명(예: `(a) Symptom`). 사례 장은 **(a) Symptom → (b) Diagnosis → (c) Fix** 순서로 고정.
- 패널 사이 화살표는 `→` 40px #8c8c8c. 패널 바탕은 흰색, 테두리 1px #e5e5e5, 모서리 10px.
- 사진·화면 캡처도 Fig 번호를 받는다. 출처가 우리 실험이면 날짜를 캡션에 쓴다(`11/28`).

### 9.3 수식
- 독립 수식은 번호 `(n)`를 오른쪽 끝에 붙인다(22px, #8c8c8c). 번호는 덱 전체에서 이어 붙이고, 노트와 대본에서 "식 (4)"처럼 부른다.
- 한 장에 수식은 최대 3개. 기호는 강의 표기(Thrun): 측정 잡음 `Q_t`, 이동 잡음 `R_t`.

### 9.4 표
- 3선 표(booktabs): 위·아래 2px #222, 머리행 아래 1px #222. 세로선, 바탕색, 줄무늬 없음.
- 캡션은 표 **위**: `Table n.` + 한 문장. 숫자 열은 오른쪽 정렬, 강조할 칸만 마룬.

### 9.5 인용
- 본문 속 인용은 `[n]`(회색 #6b6b6b 600, 본문보다 0.8배 크기). 번호는 References 장과 같다.
- 강의 자료는 `[7]` 하나로 인용하고 쪽수는 적지 않는다.

### 9.6 그대로 두는 것
- 표지, footer, `>>` 결론 한 줄, 장당 불릿 3개 이하.

## 10. 흑백 톤과 강조색 (v3.0)

기본은 흑백이다. 색은 "여기를 보라"는 신호로만 쓴다. 색이 많으면 신호가 사라진다.

### 10.1 팔레트
- 검정 #1a1a1a(제목, Part 표지, 단계 상자), 본문 #222, 도식 선·글 #2b2b2b, 보조 글 #6b6b6b, 요약줄 #8c8c8c, footer #a6a6a6.
- 면: #fafafa(카드), #f1f1f1(주요 블록). 선: #cccccc(블록 테두리), #e5e5e5(구분선).
- 강조색: **마룬 #8C2D2D 하나**. 연한 면이 필요하면 #f5eae9 / 테두리 #cf9a9a.
- 사진·지도 캡처는 원래 색 그대로 둔다(데이터이므로).

### 10.2 강조색을 쓰는 곳 (장당 1~2곳)
1. 그 장의 **핵심 숫자 하나**: 결과(`3 / 3`), 실패 값(`+0.0°`, `1.8 m`). 원고에서 `==...==`.
2. 도식에서 **실패·실제 측정**: 틀린 시선, 놓친 관측, 강조할 막대. 기준·계획·정상은 검정이나 회색.
3. 시스템 도식의 **직접 만든 부분**(캡션에 "Maroon = what we built"라고 밝힘).

### 10.3 쓰지 않는 곳
- 제목, 섹션 표시, 컬럼 제목, 불릿, `**굵게**`, `>>` 바, 표지 eyebrow, 인용 번호, 순번 라벨.
- 표의 머리행. 표 안에서는 핵심 칸 하나만.

## 11. 표지 : 프로젝트 대표 이미지 (v3.0)

표지에는 학교 엠블럼 대신 그 프로젝트를 한 장으로 보여 주는 **대표 이미지**를 넣는다.

- 원고 머리말에 `cover-image: "파일명"`과 `cover-caption: "한 문장"`을 적는다. 파일은 `assets/`에 둔다.
- 배치: 좌우 2단. 왼쪽(나머지 폭)에 eyebrow → 제목(64px 600 검정) → 부제 → 검정 선(130 × 3px, 위아래 36px) → 발표자 → 날짜·팀·학교. 오른쪽에 이미지 폭 930px, 테두리 1px #e3e3e3, 모서리 8px, 아래 10px에 캡션 17px #6b6b6b.
- 패딩 90px 110px, 두 단 사이 64px. 표지에는 footer를 달지 않는다.
- 고르는 기준: 결과가 보이는 그림(실제 주행 화면, 로봇 사진, 대표 도식). 로고·장식 사진은 쓰지 않는다. 사진은 원래 색 그대로 둔다(10.1).
- 학교 표시는 날짜 줄의 글(`University of Seoul`)과 footer로 남긴다.
