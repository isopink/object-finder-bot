"""Export deck.html to PDF and an editable PPTX (UOS standard template).

    python build/export.py                 # from docs/presentation/
    python build/export.py --deck deck.html --out out

How it works: the installed Chrome opens deck.html?export (all slides stacked at
1920x1080). The PDF is Chrome's print of that page. For the PPTX, a script in the page
reads the position and style of every element: text blocks become PowerPoint text
boxes, boxes and lines become shapes, and equations / SVG figures / photos become
pictures at the same place. 1 px = 0.5 pt (1920 px = 13.333 in). Speaker notes come
from each slide's data-notes.

Needs: pip install python-pptx playwright (uses the installed Chrome, no download).
"""
import argparse
import re
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Pt

EMU_PER_PX = 6350  # 12192000 EMU (13.333 in) / 1920 px

EXTRACT_JS = r"""
() => {
  const out = [];
  const secs = Array.from(document.querySelectorAll('section.slide'));
  let picN = 0;
  for (const sec of secs) {
    const R0 = sec.getBoundingClientRect();
    const items = [];
    const rect = (r) => ({x: r.left - R0.left, y: r.top - R0.top, w: r.width, h: r.height});
    // CSS zoom: computed lengths are unzoomed, rects are zoomed; multiply by the ancestors' zoom
    const ez = (el) => { let z = 1; for (let e = el; e; e = e.parentElement) z *= parseFloat(getComputedStyle(e).zoom) || 1; return z; };
    const isPic = (el) => el.matches('img, svg, .eq');
    const textItem = (el, cs) => {
      const runs = [];
      const push = (s, st, z) => {
        if (!s) return;
        runs.push({s, color: st.color, size: parseFloat(st.fontSize) * z, weight: parseInt(st.fontWeight) || 400,
                   italic: st.fontStyle === 'italic', family: st.fontFamily,
                   ls: st.letterSpacing === 'normal' ? 0 : (parseFloat(st.letterSpacing) || 0) * z,
                   upper: st.textTransform === 'uppercase'});
      };
      let brs = 0;
      const walk = (n) => {
        for (const c of n.childNodes) {
          if (c.nodeType === 3) push(c.textContent.replace(/\s+/g, ' '), getComputedStyle(c.parentElement), ez(c.parentElement));
          else if (c.nodeType === 1) {
            if (c.tagName === 'BR') { runs.push({br: true}); brs++; }
            else walk(c);
          }
        }
      };
      walk(el);
      // trim outer whitespace
      while (runs.length && !runs[0].br && !runs[0].s.trim()) runs.shift();
      if (runs.length && !runs[0].br) runs[0].s = runs[0].s.replace(/^\s+/, '');
      if (runs.length) { const l = runs[runs.length - 1]; if (!l.br) l.s = l.s.replace(/\s+$/, ''); }
      const range = document.createRange(); range.selectNodeContents(el);
      const tr = range.getBoundingClientRect();
      const z = ez(el);
      const lh = (cs.lineHeight === 'normal' ? parseFloat(cs.fontSize) * 1.2 : parseFloat(cs.lineHeight)) * z;
      const lines = Math.max(1, Math.round(tr.height / lh));
      let align = cs.textAlign;
      if (cs.display.includes('flex') && cs.justifyContent === 'center') align = 'center';
      if (align === 'start') align = 'left';
      return Object.assign({t: 'text', runs, align, lh, lines, brs, box: rect(el.getBoundingClientRect())}, rect(tr));
    };
    const walk = (el) => {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      if (el !== sec && isPic(el)) {
        const id = 'p' + (picN++); el.setAttribute('data-pic', id);
        items.push(Object.assign({t: 'pic', id, src: el.tagName === 'IMG' ? el.getAttribute('src') : null}, rect(el.getBoundingClientRect())));
        return;
      }
      if (el !== sec) {
        const sides = ['Top', 'Right', 'Bottom', 'Left'];
        const zz = ez(el);
        const bw = sides.map(s => (parseFloat(cs['border' + s + 'Width']) || 0) * zz);
        const bc = sides.map(s => cs['border' + s + 'Color']);
        const bg = cs.backgroundColor;
        const hasBg = bg && bg !== 'rgba(0, 0, 0, 0)' && bg !== 'transparent';
        if (hasBg || bw.some(w => w > 0)) {
          items.push(Object.assign({t: 'shape', bg: hasBg ? bg : null, bw, bc, dashed: cs.borderTopStyle === 'dashed',
                                    rad: (parseFloat(cs.borderTopLeftRadius) || 0) * zz}, rect(el.getBoundingClientRect())));
        }
      }
      const hasText = Array.from(el.childNodes).some(n => n.nodeType === 3 && n.textContent.trim());
      if (el !== sec && hasText) { items.push(textItem(el, cs)); return; }
      for (const c of el.children) walk(c);
    };
    walk(sec);
    out.push({notes: sec.getAttribute('data-notes') || '', items});
  }
  return out;
}
"""


def rgb(css):
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)", css or "")
    if not m:
        return None, 0.0
    a = float(m.group(4)) if m.group(4) is not None else 1.0
    return RGBColor(int(m.group(1)), int(m.group(2)), int(m.group(3))), a


def blend_on_white(css):
    """PowerPoint shapes here are opaque: mix a translucent colour onto white."""
    c, a = rgb(css)
    if c is None:
        return None
    if a >= 0.999:
        return c
    return RGBColor(*(round(v * a + 255 * (1 - a)) for v in (c[0], c[1], c[2])))


def E(px):
    return Emu(int(round(px * EMU_PER_PX)))


def font_name(family):
    first = family.split(",")[0].strip().strip("'\"")
    if first.lower() in ("katex_main", "katex_math"):
        return "Noto Serif"
    return first or "Noto Serif"


def add_shape(slide, it):
    x, y, w, h = it["x"], it["y"], it["w"], it["h"]
    if w < 0.5 or h < 0.5:
        return
    bw, bc = it["bw"], it["bc"]
    present = [(bw[i], bc[i]) for i in range(4) if bw[i] > 0]
    base = max(set(present), key=present.count) if present else None
    uniform_sides = [i for i in range(4) if bw[i] > 0 and (bw[i], bc[i]) == base]
    if it["bg"] or len(uniform_sides) == 4:
        kind = MSO_SHAPE.ROUNDED_RECTANGLE if it["rad"] > 0 else MSO_SHAPE.RECTANGLE
        shp = slide.shapes.add_shape(kind, E(x), E(y), E(w), E(h))
        if it["rad"] > 0:
            shp.adjustments[0] = min(0.5, it["rad"] / max(1.0, min(w, h)))
        if it["bg"]:
            shp.fill.solid()
            shp.fill.fore_color.rgb = blend_on_white(it["bg"])
        else:
            shp.fill.background()
        if len(uniform_sides) == 4:
            shp.line.color.rgb = blend_on_white(base[1])
            shp.line.width = Pt(base[0] * 0.5)
            if it["dashed"]:
                shp.line.dash_style = MSO_LINE_DASH_STYLE.DASH
        else:
            shp.line.fill.background()
        shp.shadow.inherit = False
        drawn = set(uniform_sides) if len(uniform_sides) == 4 else set()
    else:
        drawn = set()
    # remaining sides as thin bars
    for i in range(4):
        if bw[i] <= 0 or i in drawn:
            continue
        t = bw[i]
        if i == 0:
            bx, by, bww, bh = x, y, w, t
        elif i == 1:
            bx, by, bww, bh = x + w - t, y, t, h
        elif i == 2:
            bx, by, bww, bh = x, y + h - t, w, t
        else:
            bx, by, bww, bh = x, y, t, h
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, E(bx), E(by), E(bww), E(bh))
        bar.fill.solid()
        bar.fill.fore_color.rgb = blend_on_white(bc[i])
        bar.line.fill.background()
        bar.shadow.inherit = False


def add_text(slide, it):
    runs = it["runs"]
    if not runs:
        return
    sizes = [r["size"] for r in runs if not r.get("br")] or [20]
    fs = max(sizes)
    single = it["lines"] <= it["brs"] + 1  # every line break is explicit -> no wrapping
    x, y, w, h = it["x"], it["y"], it["w"], it["h"]
    pad = 0.08 * w + 12 if single else 6
    align = it["align"]
    if single:
        if align == "center":
            x -= pad / 2
        elif align == "right":
            x -= pad
        w += pad
    else:
        w += pad
    tb = slide.shapes.add_textbox(E(x), E(y), E(w), E(max(h, fs * 1.2)))
    tf = tb.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.word_wrap = not single
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.vertical_anchor = MSO_ANCHOR.TOP
    p = tf.paragraphs[0]

    def style_para(par):
        par.line_spacing = Pt(it["lh"] * 0.5)
        par.alignment = {"center": PP_ALIGN.CENTER, "right": PP_ALIGN.RIGHT}.get(align, PP_ALIGN.LEFT)

    style_para(p)
    for r in runs:
        if r.get("br"):
            p = tf.add_paragraph()
            style_para(p)
            continue
        s = r["s"].upper() if r["upper"] else r["s"]
        run = p.add_run()
        run.text = s
        f = run.font
        f.size = Pt(r["size"] * 0.5)
        f.bold = r["weight"] >= 600
        f.italic = r["italic"]
        f.name = font_name(r["family"])
        c = blend_on_white(r["color"])
        if c is not None:
            f.color.rgb = c
        rpr = run._r.get_or_add_rPr()
        ea = rpr.find(qn("a:ea"))
        if ea is None:
            ea = rpr.makeelement(qn("a:ea"), {})
            rpr.append(ea)
        ea.set("typeface", "Noto Sans KR")
        if r["ls"]:
            rpr.set("spc", str(int(round(r["ls"] * 0.5 * 100))))


def main():
    ap = argparse.ArgumentParser()
    here = Path(__file__).resolve().parent.parent
    ap.add_argument("--deck", default=str(here / "deck.html"))
    ap.add_argument("--out", default=str(here / "out"))
    ap.add_argument("--name", default="where_is_my_banana")
    ap.add_argument("--preview", action="store_true", help="also save one PNG per slide")
    args = ap.parse_args()

    deck = Path(args.deck).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    url = deck.as_uri() + "?export"

    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel="chrome")
        page = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=2)
        page.goto(url, wait_until="networkidle")
        page.wait_for_selector("body[data-ready='1']", timeout=30000)
        page.evaluate("document.fonts.ready")
        page.wait_for_timeout(300)

        pdf_path = out / (args.name + ".pdf")
        page.pdf(path=str(pdf_path), width="1920px", height="1080px", print_background=True,
                 prefer_css_page_size=True)
        print("PDF ", pdf_path)

        data = page.evaluate(EXTRACT_JS)

        if args.preview:
            prev = out / "preview"
            prev.mkdir(exist_ok=True)
            for i, loc in enumerate(page.locator("section.slide").all()):
                loc.screenshot(path=str(prev / ("s%02d.png" % (i + 1))), scale="css")

        prs = Presentation()
        prs.slide_width = Emu(1920 * EMU_PER_PX)
        prs.slide_height = Emu(1080 * EMU_PER_PX)
        blank = prs.slide_layouts[6]
        with tempfile.TemporaryDirectory() as td:
            for si, sd in enumerate(data):
                slide = prs.slides.add_slide(blank)
                for it in sd["items"]:
                    if it["t"] == "shape":
                        add_shape(slide, it)
                    elif it["t"] == "text":
                        add_text(slide, it)
                    elif it["t"] == "pic":
                        if it["w"] < 1 or it["h"] < 1:
                            continue
                        src = it.get("src")
                        local = (deck.parent / src) if src and not src.startswith(("http", "data:")) else None
                        if local is not None and local.exists():
                            img = str(local)
                        else:
                            img = str(Path(td) / (it["id"] + ".png"))
                            page.locator("[data-pic='%s']" % it["id"]).screenshot(path=img, omit_background=True)
                        slide.shapes.add_picture(img, E(it["x"]), E(it["y"]), E(it["w"]), E(it["h"]))
                if sd["notes"]:
                    slide.notes_slide.notes_text_frame.text = sd["notes"]
        pptx_path = out / (args.name + ".pptx")
        prs.save(str(pptx_path))
        print("PPTX", pptx_path, "(%d slides)" % len(data))
        browser.close()


if __name__ == "__main__":
    sys.exit(main())
