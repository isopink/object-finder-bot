---
version: 1.0
name: uos-seminar
description: 서울시립대 발표 덱 표준. 흰 바탕, UOS 블루 제목, 마룬 강조 한 가지, Source Sans 3 + Noto Sans KR. 강의 자료처럼 본문이 세로로 꽉 차는 레이아웃.
source: "Seminar_8_05 (2026-08-05 'Trajectory Tracking and Control', 36장) 최종본 HTML에서 실제 값을 추출. 7/15 ISAC 덱과 handoff/template.md로 교차 확인."
confirmed: 2026-11-27

canvas:
  size: 1920x1080px        # 16:9. PPTX: 13.333in x 7.5in
  px-to-pt: 0.5            # 1920px = 13.333in -> 1px = 1/144in = 0.5pt
  content-width: 1288px    # 좌우 패딩 316px. 8/5 덱 그대로 (본문 폭 = 4:3 시절과 같음)
  pad: { top: 52px, x: 316px, bottom: 60px }      # 기본
  pad-dense: { top: 44px, x: 316px, bottom: 52px } # 도식 + 표처럼 빽빽한 장

colors:
  uos-blue: "#004094"      # 제목, 컬럼 제목, Part 표지 배경, 번호, 링크
  maroon: "#8C2D2D"        # 강조(**굵게**), >> 액센트 바, 표지 eyebrow. 강조색은 이것 하나
  ink: "#222222"           # 본문
  bullet: "#111111"        # 불릿 점. 컬러 불릿 쓰지 않음
  callout-ink: "#2a2f35"   # >> 문구
  sub-ink: "#444444"       # 하위 불릿 글자
  sub-dash: "#777777"      # 하위 불릿 대시
  summary: "#8a8f96"       # ### 요약줄, 표지 발표자
  footer: "#a2a8ae"        # footer 글자, 표지 날짜
  caption: "#999999"       # 이미지 출처
  rule: "#e4e7ea"          # footer 위 선, 2단 구분선
  rule-soft: "#eceef1"     # Outline 행 구분선, 카드 테두리
  img-border: "#e2e5e8"
  card-bg: "#fafbfc"
  tone-blue: { bg: "#eaf1f9", border: "#9fbde0" }
  tone-maroon: { bg: "#f5eae9", border: "#cf9a9a" }
  part-label: "#cdd9ee"    # Part 표지 "PART N"
  part-sub: "#bcd0ec"      # Part 표지 부제
  diagram:
    ink: "#24405e"         # 도식 속 물체·굵은 선
    line: "#a8b0b8"        # 벽, 틀, 축
    flow: "#8a9bb0"        # 흐름 화살표 (점선 9 7)
    label: "#667080"       # 도식 아래 설명
    group-label: "#5a7396" # 블록 묶음 라벨 (CONTROLLER 등)
    block-blue: { fill: "#eaf1f9", stroke: "#9fbde0" }
    block-neutral: { fill: "#fafbfc", stroke: "#c9d3de" }
    block-muted: { fill: "#ffffff", stroke: "#d5dae0" }
    hi-blue: "#eef3f9"
    hi-maroon: "#f0dedd"
    math: "#1a1f26"

fonts:
  sans: "'Source Sans 3', 'Noto Sans KR', sans-serif"   # 영문은 Source Sans 3, 한글은 Noto Sans KR
  math: "Georgia, 'Times New Roman', serif"           # 본문 속 그리스 문자·변수는 이탤릭 세리프
  display-math: KaTeX
  weights: { regular: 400, medium: 500, semibold: 600, bold: 700 }  # 700은 슬라이드 제목·라벨에만

type:                      # px (pt = px x 0.5)
  cover-eyebrow: { size: 24, weight: 700, color: maroon, tracking: 0.32em, case: upper }
  cover-title:   { size: 60, weight: 600, color: uos-blue, lh: 1.16, max-width: 1180 }
  cover-speaker: { size: 26, color: summary }
  cover-date:    { size: 20, color: footer }
  part-label:    { size: 30, weight: 700, color: part-label, tracking: 0.5em }
  part-title:    { size: 104, weight: 600, color: "#ffffff" }
  part-sub:      { size: 36, style: italic, color: part-sub }
  outline-title: { size: 50, weight: 700, color: uos-blue }
  outline-part:  { size: 27, weight: 700, color: uos-blue, width: 132 }
  outline-name:  { size: 31, weight: 500, color: ink }
  slide-title:   { size: 44, weight: 700, color: uos-blue, lh: 1.1 }   # 빽빽한 장 42
  summary:       { size: 27, color: summary, margin-top: 8 }            # 26~25까지 줄여도 됨
  body:          { size: 27, lh: 1.35 }    # 26~25 (항목 많을 때), 2단 안에서는 24
  sub:           { size: 23, lh: 1.35, color: sub-ink }
  col-title:     { size: 29, weight: 700, color: uos-blue, margin-bottom: 18 }
  callout:       { size: 29, weight: 500, color: callout-ink }
  card-title:    { size: 27, weight: 700, color: uos-blue }
  card-sub:      { size: 20, color: "#555555" }
  caption:       { size: 16, style: italic, color: caption }   # 17까지
  footer:        { size: 18, color: footer }
  reference:     { size: 20, lh: 1.34, color: "#333333" }      # 많으면 19
  diagram-label: { size: 19, color: diagram.label }
  diagram-block: { size: 18, weight: 600 }
---

# UOS 발표 덱 표준 디자인

서울시립대 발표(세미나, 수업 발표)에 계속 쓰는 표준이다. 값은 2026-08-05 세미나 덱 최종본에서 그대로 뽑았다. 새 덱은 이 문서의 값만 쓴다.

원고 기호는 같은 폴더의 `Rules.md`를 따른다.

## 1. 톤

- 흰 바탕에 **UOS 블루 제목 + 마룬 강조 한 가지**. 그 밖의 색은 회색 단계뿐이다.
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
- 위에서부터: UOS 엠블럼(261px, 아래 22px) → eyebrow(예: `2026 FALL · INTELLIGENT ROBOTICS`) → 제목 → 블루 선(130 x 3px, 위아래 44px) → `Speaker : 이름` → 날짜.
- 엠블럼 파일: 같은 폴더의 `emblem.png`.

### Outline
- 제목 `Outline` 50px. 아래에 Part 행을 최대 폭 960px로 세로 중앙.
- 행: 위아래 패딩 27px, 아래 1px `rule-soft` 선(마지막 행은 선 없음). `Part N`(블루 27px 700, 폭 132px) + 이름(31px 500), 간격 30px.

### Part 표지
- 배경 UOS 블루, 가운데 정렬.
- `PART N`(30px, 자간 0.5em) → 반투명 흰 선(220 x 2px, rgba(255,255,255,0.5), 위아래 44px) → 제목 104px 600 → 이탤릭 부제 36px(위 40px).

### 본문 장 (기본)
1. 제목 `##` 44px + 요약줄 `###` 27px.
2. 본문 영역(flex 1, 세로 중앙).
3. `>>` 문구 (있을 때).
4. footer.

### References
- 제목 42px, 아래 24px. 항목 간격 17px.
- 번호 `[n]`은 블루 700, 폭 40px. IEEE 형식, 학술지·학회명은 이탤릭.

## 4. 요소

| 요소 | 규칙 |
|---|---|
| 불릿 | `•` 검정(#111), 점과 글 사이 16px, 항목 사이 20~24px |
| 하위 불릿 | `–` #777, 글 23px #444, 왼쪽 들여쓰기 42px, 간격 14px |
| 강조 `**` | 마룬 #8C2D2D. 요약줄 안의 강조는 요약색(#8a8f96) 600 |
| 2단 `\|\|\|` | 박스 없이 두 컬럼, 가운데 1px #e4e7ea 세로선, 각 쪽 52~56px 여백. 컬럼 제목 29px 블루 700 |
| 톤 박스 | "묶어서 표시"일 때만. 블루(#eaf1f9 / #9fbde0) 또는 마룬(#f5eae9 / #cf9a9a), 테두리 1.5px, 모서리 16px, 패딩 44 x 46px |
| 정보 카드 | #fafbfc, 테두리 1px #eceef1, **왼쪽 4px 블루**, 모서리 10px, 패딩 26 x 28px. 강조 카드는 마룬 톤 + 왼쪽 4px 마룬. 카드 사이 화살표 `→` 40px #8a8f96 |
| `>>` 문구 | 박스 없음. 마룬 바(56 x 3px, 모서리 2px) 아래 16px에 29px 500 가운데 정렬. footer 위 34px |
| footer | 18px #a2a8ae, 위에 1px #e4e7ea 선, 선 아래 10px. 세 칸: 왼쪽 소속 / 가운데 짧은 제목 / 오른쪽 `n / N` |
| 이미지 | 테두리 1px #e2e5e8, 모서리 8px. 아래 8~12px에 출처 캡션(`Source : …`) 16px 이탤릭 #999 |
| 사진 자리 `[[사진 n]]` | 점선 테두리 상자 + "사진 n" 라벨. 지침의 크기와 정렬을 반영 |
| 표 | 머리행 마룬 바탕 흰 글 700, 본문 행 아래 1px #e4e7ea, 글 18~20px (8/5 덱 21장 이미지에서 추정) |

## 5. 수식

- 한 장에 **결과 수식 1개 + 한 줄 해석**. 유도는 Appendix로.
- 본문 속 변수와 그리스 문자는 Georgia 이탤릭. 독립 수식은 KaTeX.
- 수식 밑에 각 항의 뜻을 작은 회색 글씨로 단다 (8/5 덱 13장 방식).
- PPTX에는 수식을 이미지로 넣는다.

## 6. 도식 (SVG)

- 선: 틀·벽 #a8b0b8 3px, 물체 #24405e 5px(둥근 끝).
- 흐름 화살표: #8a9bb0 3px, 점선 `9 7`, 화살촉은 같은 색 삼각형. 움직임이 필요하면 dashoffset 애니메이션.
- 블록: 모서리 10px. 주요 블록 #eaf1f9 / #9fbde0(글 블루 600), 보조 블록 #fafbfc / #c9d3de(글 #24405e), 비활성 블록 흰 바탕 / #d5dae0(글 #667080).
- 묶음: 점선 #9fbde0 사각형(모서리 14px) + 라벨 17px 700 #5a7396 대문자, 자간 0.06em.
- 계획(기준)은 블루 점선, 실제(측정)는 마룬 실선.
- 도식 아래 설명 19px #667080. 컬러 강조는 한두 곳만 마룬.
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
