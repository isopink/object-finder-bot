"""Pack the design template into one zip (run after every template change).

    python build/pack_template.py            # from docs/presentation/
    -> out/uos_design_template.zip

Contents:
    README.md          how to use, version, date (generated)
    DESIGN.md          design rules (colors, type, layout, paper-review style)
    Rules.md           manuscript symbols (Text.md -> slides)
    build/export.py    deck.html -> PDF + editable PPTX
    vendor/            KaTeX and Noto Serif, so the deck works offline
    example/           this deck as a worked example: Text.md, deck.html and
                       only the images deck.html uses (example/vendor is a copy
                       of vendor/ so the example opens on its own)
"""
import datetime
import re
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "out" / "uos_design_template.zip"
ROOT = "uos_design_template/"


def version():
    m = re.search(r"^version:\s*([\w.]+)", (HERE / "DESIGN.md").read_text(encoding="utf-8"), re.M)
    return m.group(1) if m else "?"


def readme(ver, today):
    return f"""# UOS 발표 디자인 템플릿 v{ver}

만든 날: {today}. 원본은 저장소 `docs/presentation/` 이고, 템플릿을 고칠 때마다
`python build/pack_template.py` 로 이 zip을 다시 만든다.

## 들어 있는 것
- `DESIGN.md` : 디자인 규칙. 흑백 톤 + 강조색 하나(10장), 논문 리뷰 형식(9장), 표지 대표 이미지(11장)
- `Rules.md` : 원고(Text.md) 기호 → 슬라이드 요소
- `build/export.py` : deck.html → PDF + 편집 가능한 PPTX (`pip install python-pptx playwright`, 설치된 Chrome 사용)
- `vendor/` : KaTeX, Noto Serif (오프라인에서도 같은 모양)
- `example/` : 실제로 쓴 덱 한 벌 (Where Is My Cup?, 18장). 새 덱은 이 폴더를 복사해서 시작

## 새 덱 만드는 순서
1. `example/` 를 새 폴더로 복사하고 `Text.md` 부터 고친다 (`Rules.md` 기호).
2. 표지 대표 이미지를 `assets/` 에 넣고 `Text.md` 머리말 `cover-image` 를 바꾼다.
3. `deck.html` 을 원고에 맞게 고친다. 색·글꼴·여백은 `DESIGN.md` 값만 쓴다.
4. 그 폴더에서 `python ../build/export.py --deck deck.html --out out --name 덱이름 --preview`
"""


def main():
    ver = version()
    today = datetime.date.today().isoformat()
    deck = (HERE / "deck.html").read_text(encoding="utf-8")
    used = sorted(set(re.findall(r'(?:src|href)="(assets/[^"]+)"', deck)))
    missing = [u for u in used if not (HERE / u).exists()]
    if missing:
        sys.exit("missing assets: %s" % missing)
    vendor = [p for p in sorted((HERE / "vendor").rglob("*")) if p.is_file()]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(ROOT + "README.md", readme(ver, today))
        for name in ("DESIGN.md", "Rules.md", "build/export.py"):
            z.write(HERE / name, ROOT + name)
        for p in vendor:
            rel = p.relative_to(HERE).as_posix()
            z.write(p, ROOT + rel)
            z.write(p, ROOT + "example/" + rel)
        z.write(HERE / "Text.md", ROOT + "example/Text.md")
        z.write(HERE / "deck.html", ROOT + "example/deck.html")
        for u in used:
            z.write(HERE / u, ROOT + "example/" + u)
    print("ZIP ", OUT, "(v%s, %d images, %.1f MB)" % (ver, len(used), OUT.stat().st_size / 1e6))


if __name__ == "__main__":
    main()
