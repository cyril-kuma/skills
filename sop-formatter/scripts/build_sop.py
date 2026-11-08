#!/usr/bin/env python3
"""
build_sop.py - render an SOP spec (JSON) into a Word document in the
NGS core lab house style (based on "Ligation sequencing gDNA-Native Barcoding").

Usage:
    python build_sop.py spec.json -o "My SOP.docx"
    python build_sop.py spec.json --check        # validate the spec, print an outline

Standard library only. See ../references/spec_format.md for the spec format.
"""
import argparse
import datetime
import json
import os
import re
import struct
import sys
import zipfile
from xml.sax.saxutils import escape as _esc

# ---------------------------------------------------------------- house style
FONT = "Gill Sans MT"
BODY_SZ = 22          # half-points (11 pt)
TITLE_SZ = 28         # 14 pt header title
FOOTER_SZ = 20        # 10 pt footer sign-off lines
BANNER_FILL = "153D63"  # dark navy step banner
MAT_FILL = "D9D9D9"     # materials table header
PREP_FILL = "BFBFBF"    # reagent preparation table header
TABLE_FILL = "D9D9D9"   # default header fill for other tables
CAUTION_RED = "C00000"  # caution / precaution text
KEEP_TOGETHER_ROWS = 15  # tables up to this many body rows are kept on one page
KEEP_TOGETHER_PREP_ROWS = 6
CHAR_TWIPS = 125         # rough width of one 11 pt Gill Sans character


def plain_text(t):
    t = t.get("text", "") if isinstance(t, dict) else t
    return re.sub(r"\*\*|\*|==|\^\{|_\{|\}|\\", "", str(t))


def natural_widths(all_rows, ncols):
    """Column weights from content: wide enough for the longest word, more for long text."""
    need = [4] * ncols      # cells up to 14 characters fit whole; longer ones by their longest word
    maxlen = [4] * ncols
    for r in all_rows:
        col = 0
        for c in r:
            sp = int(c.get("span", 1)) if isinstance(c, dict) else 1
            if sp == 1 and col < ncols:
                txt = plain_text(c).strip()
                words = txt.split() or [""]
                n = len(txt) if len(txt) <= 14 else max(len(w) for w in words)
                need[col] = max(need[col], n)
                maxlen[col] = max(maxlen[col], len(txt))
            col += sp
    desired = [max(nd + 1, min(ml, 32)) for nd, ml in zip(need, maxlen)]
    return need, desired


def fit_widths(need, desired, total):
    """Twip widths: every column gets its minimum (longest word / short entry), then the
    rest of the width is shared towards each column's desired width."""
    pad = 216 + 60
    mins = [(n + 1) * CHAR_TWIPS + pad for n in need]
    des = [max(d * CHAR_TWIPS + pad, m) for d, m in zip(desired, mins)]
    if sum(des) <= total:
        return scale_widths(des, total)
    if sum(mins) <= total:
        room = total - sum(mins)
        gap = sum(d - m for d, m in zip(des, mins)) or 1
        ws = [int(m + (d - m) * room / gap) for d, m in zip(des, mins)]
        ws[-1] += total - sum(ws)
        return ws
    return scale_widths(mins, total)

PAGE = {"A4": (11906, 16838), "Letter": (12240, 15840)}
MARGIN = 1440
HEADER_DIST = 340
FOOTER_DIST = 397

W_NS = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"')


class SpecError(Exception):
    pass


def esc(s):
    return _esc(str(s), {'"': "&quot;"})


# ---------------------------------------------------------------- inline text
TOKEN = re.compile(r"\\([\\*=^_{}])|(\*\*)|(\*)|(==)|(\^\{)|(_\{)|(\})")


def parse_inline(text):
    """Split light markup into runs.

    **bold**  *italic*  ==highlight==  ^{superscript}  _{subscript}
    A backslash escapes a marker character. Unpaired markers print literally.
    """
    text = str(text)
    plain = re.sub(r"\\.", "", text)
    n_bold = plain.count("**")
    n_ital = plain.replace("**", "").count("*")
    n_hl = plain.count("==")
    use_bold, use_ital, use_hl = n_bold % 2 == 0, n_ital % 2 == 0, n_hl % 2 == 0

    runs, buf = [], []
    st = {"b": False, "i": False, "hl": False}
    stack = []

    def flush():
        if buf:
            runs.append(("".join(buf), dict(st, va=stack[-1] if stack else None)))
            buf.clear()

    pos = 0
    for m in TOKEN.finditer(text):
        buf.append(text[pos:m.start()])
        pos = m.end()
        lit, bold, ital, hl, sup, sub, close = m.groups()
        if lit:
            buf.append(lit)
        elif bold:
            if use_bold:
                flush(); st["b"] = not st["b"]
            else:
                buf.append("**")
        elif ital:
            if use_ital:
                flush(); st["i"] = not st["i"]
            else:
                buf.append("*")
        elif hl:
            if use_hl:
                flush(); st["hl"] = not st["hl"]
            else:
                buf.append("==")
        elif sup or sub:
            flush(); stack.append("superscript" if sup else "subscript")
        elif close:
            if stack:
                flush(); stack.pop()
            else:
                buf.append("}")
    buf.append(text[pos:])
    flush()
    return [r for r in runs if r[0]]


def rpr(b=False, i=False, color=None, sz=None, hl=None, va=None, font=None, caps=False):
    x = []
    if font:
        x.append(f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:cs="{font}"/>')
    if b:
        x.append("<w:b/><w:bCs/>")
    if i:
        x.append("<w:i/><w:iCs/>")
    if caps:
        x.append("<w:caps/>")
    if color:
        x.append(f'<w:color w:val="{color}"/>')
    if sz:
        x.append(f'<w:sz w:val="{sz}"/><w:szCs w:val="{sz}"/>')
    if hl:
        x.append(f'<w:highlight w:val="{hl}"/>')
    if va:
        x.append(f'<w:vertAlign w:val="{va}"/>')
    return f"<w:rPr>{''.join(x)}</w:rPr>" if x else ""


def runs_xml(text, b=False, i=False, color=None, sz=None, hl=None):
    """Text with inline markup -> run XML. Base formatting is OR'd with markup."""
    out = []
    for t, f in parse_inline(text):
        props = rpr(b=b or f["b"], i=i or f["i"], color=color, sz=sz,
                    hl=hl or ("yellow" if f["hl"] else None), va=f["va"])
        out.append(f'<w:r>{props}<w:t xml:space="preserve">{esc(t)}</w:t></w:r>')
    return "".join(out)


def para(content_xml="", style=None, num=None, ilvl=0, keep_next=False, jc=None,
         before=None, after=None, ind_left=None, ind_hanging=None, page_break=False,
         line=None):
    p = []
    if style:
        p.append(f'<w:pStyle w:val="{style}"/>')
    if keep_next:
        p.append("<w:keepNext/>")
    if page_break:
        p.append("<w:pageBreakBefore/>")
    if num is not None:
        p.append(f'<w:numPr><w:ilvl w:val="{ilvl}"/><w:numId w:val="{num}"/></w:numPr>')
    sp = []
    if before is not None:
        sp.append(f'w:before="{before}"')
    if after is not None:
        sp.append(f'w:after="{after}"')
    if line is not None:
        sp.append(f'w:line="{line}" w:lineRule="auto"')
    if sp:
        p.append(f"<w:spacing {' '.join(sp)}/>")
    if ind_left is not None or ind_hanging is not None:
        a = []
        if ind_left is not None:
            a.append(f'w:left="{ind_left}"')
        if ind_hanging is not None:
            a.append(f'w:hanging="{ind_hanging}"')
        p.append(f"<w:ind {' '.join(a)}/>")
    if jc:
        p.append(f'<w:jc w:val="{jc}"/>')
    ppr = f"<w:pPr>{''.join(p)}</w:pPr>" if p else ""
    return f"<w:p>{ppr}{content_xml}</w:p>"


# ---------------------------------------------------------------- tables
def cell(paras_xml, width, fill=None, span=1, borders=None, valign=None):
    tc = [f'<w:tcW w:w="{width}" w:type="dxa"/>']
    if span > 1:
        tc.append(f'<w:gridSpan w:val="{span}"/>')
    if borders:
        tc.append(borders)
    if fill:
        tc.append(f'<w:shd w:val="clear" w:color="auto" w:fill="{fill}"/>')
    if valign:
        tc.append(f'<w:vAlign w:val="{valign}"/>')
    return f"<w:tc><w:tcPr>{''.join(tc)}</w:tcPr>{paras_xml}</w:tc>"


def table(rows_xml, widths, jc=None, borders_color="000000", header=False):
    total = sum(widths)
    grid = "".join(f'<w:gridCol w:w="{w}"/>' for w in widths)
    b = "".join(f'<w:{s} w:val="single" w:sz="4" w:space="0" w:color="{borders_color}"/>'
                for s in ("top", "left", "bottom", "right", "insideH", "insideV"))
    tp = ['<w:tblStyle w:val="TableGrid"/>', f'<w:tblW w:w="{total}" w:type="dxa"/>']
    if jc:
        tp.append(f'<w:jc w:val="{jc}"/>')
    tp.append(f"<w:tblBorders>{b}</w:tblBorders>")
    tp.append('<w:tblLayout w:type="fixed"/>')
    tp.append('<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" '
              'w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>')
    return f"<w:tbl><w:tblPr>{''.join(tp)}</w:tblPr><w:tblGrid>{grid}</w:tblGrid>{''.join(rows_xml)}</w:tbl>"


def row(cells_xml, header=False, cant_split=False):
    tr = []
    if cant_split:
        tr.append("<w:cantSplit/>")
    if header:
        tr.append("<w:tblHeader/>")
    trpr = f"<w:trPr>{''.join(tr)}</w:trPr>" if tr else ""
    return f"<w:tr>{trpr}{''.join(cells_xml)}</w:tr>"


def scale_widths(weights, total):
    s = float(sum(weights))
    ws = [max(400, int(round(total * w / s))) for w in weights]
    ws[-1] += total - sum(ws)
    return ws


# ---------------------------------------------------------------- images
def image_size(path):
    with open(path, "rb") as f:
        head = f.read(26)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            w, h = struct.unpack(">II", head[16:24])
            return "png", w, h
        if head[:2] == b"\xff\xd8":
            f.seek(2)
            while True:
                marker = f.read(2)
                if len(marker) < 2 or marker[0] != 0xFF:
                    break
                if marker[1] in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                                 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                    f.read(3)
                    h, w = struct.unpack(">HH", f.read(4))
                    return "jpeg", w, h
                seg = struct.unpack(">H", f.read(2))[0]
                f.seek(seg - 2, 1)
    raise SpecError(f"unsupported image (use PNG or JPEG): {path}")


# ---------------------------------------------------------------- builder
class Builder:
    def __init__(self, spec, base_dir):
        self.spec = spec
        self.base_dir = base_dir
        self.opts = spec.get("options", {}) or {}
        paper = self.opts.get("paper", "A4")
        if paper not in PAGE:
            raise SpecError("options.paper must be 'A4' or 'Letter'")
        self.pw, self.ph = PAGE[paper]
        self.text_w = self.pw - 2 * MARGIN
        self.body = []
        self.last_was_table = False
        self.nums = []          # (numId, abstractId)
        self.next_num = 3       # 1 = cell bullets, 2 = body bullets
        self.table_no = 0
        self.figure_no = 0
        self.images = []        # (rid, name, bytes, ext)
        self.outline = []
        self.warnings = []

    # -- numbering
    def new_num(self, abstract):
        nid = self.next_num
        self.next_num += 1
        self.nums.append((nid, abstract))
        return nid

    # -- emitting
    def add_p(self, xml):
        if self.last_was_table:
            self.body.append(para(style="TableGap"))   # a little air below every table
        self.body.append(xml)
        self.last_was_table = False

    def add_tbl(self, xml):
        if self.last_was_table:
            # Word merges tables that touch; keep a thin paragraph between them
            self.body.append(para(style="Spacer"))
        self.body.append(xml)
        self.last_was_table = True

    def heading(self, text, before=None, page_break=False):
        self.add_p(para(runs_xml(text), style="SOPHeading", before=before, page_break=page_break))

    def paragraph(self, text, style=None, **kw):
        self.add_p(para(runs_xml(text), style=style, **kw))

    def text_block(self, value, where, first_style=None):
        """Purpose/Scope style value: string or list of strings/blocks."""
        if isinstance(value, str):
            self.paragraph(value, style=first_style)
        elif isinstance(value, list):
            for k, v in enumerate(value):
                if isinstance(v, str):
                    self.paragraph(v, style=first_style if k == 0 else None)
                elif isinstance(v, dict):
                    self.block(v, f"{where}[{k}]", None)
                else:
                    raise SpecError(f"{where}[{k}]: expected text or a block")
        else:
            raise SpecError(f"{where}: expected text or a list")

    # -- blocks
    def block(self, b, where, step_ctx):
        if not isinstance(b, dict) or "type" not in b:
            raise SpecError(f"{where}: each block needs a 'type'")
        t = b["type"]
        fn = getattr(self, "b_" + t.replace("-", "_"), None)
        if fn is None:
            raise SpecError(f"{where}: unknown block type '{t}'. "
                            "Allowed: " + ", ".join(sorted(BLOCK_TYPES)))
        fn(b, where, step_ctx)

    def b_heading(self, b, where, ctx):
        self.heading(req(b, "text", where))

    def b_paragraph(self, b, where, ctx):
        self.paragraph(req(b, "text", where),
                       jc={"left": "left", "center": "center", "justify": "both"}.get(b.get("align")))

    def b_page_break(self, b, where, ctx):
        self.add_p(para('<w:r><w:br w:type="page"/></w:r>', style="Spacer"))

    def b_section(self, b, where, ctx):
        title = req(b, "title", where)
        lettered = b.get("lettered", self.opts.get("letter_sections", True))
        if lettered and ctx is not None:
            if ctx.get("section_num") is None:
                ctx["section_num"] = self.new_num(3)
            self.add_p(para(runs_xml(title), style="SOPSection", num=ctx["section_num"]))
        else:
            self.add_p(para(runs_xml(title), style="SOPSection"))
        self.outline.append("    - " + title)
        if b.get("intro"):
            self.paragraph(b["intro"])

    def bullets(self, items, where, level=0, num=2):
        for k, it in enumerate(items):
            if isinstance(it, str):
                self.add_p(para(runs_xml(it), style="SOPList", num=num, ilvl=level))
            elif isinstance(it, dict) and "text" in it:
                self.add_p(para(runs_xml(it["text"]), style="SOPList", num=num, ilvl=level))
                if it.get("items"):
                    self.bullets(it["items"], f"{where}[{k}].items", min(level + 1, 2), num)
            else:
                raise SpecError(f"{where}[{k}]: bullet items are text or {{'text', 'items'}}")

    def b_bullets(self, b, where, ctx):
        if b.get("heading"):
            self.heading(b["heading"])
        self.bullets(req(b, "items", where), where + ".items")

    def callout(self, b, where, label, hl=None, color=None):
        lab = b.get("label", label)
        text = b.get("text", "")
        items = b.get("items")
        if not text and not items:
            raise SpecError(f"{where}: needs 'text' or 'items'")
        body = ""
        if lab:
            body += runs_xml(lab.rstrip(":") + ":" + (" " if text else ""), b=True, hl=hl, color=color)
        if text:
            body += runs_xml(text, hl=hl, color=color)
        self.add_p(para(body, style="SOPNote"))
        if items:
            self.bullets(items, where + ".items")

    def b_note(self, b, where, ctx):
        self.callout(b, where, "Note")

    def b_important(self, b, where, ctx):
        self.callout(b, where, "Important")

    def b_caution(self, b, where, ctx):
        self.callout(b, where, "Caution", color=CAUTION_RED)

    def b_safe_stop(self, b, where, ctx):
        self.callout(b, where, "Safe stopping point", hl="yellow")

    def b_materials(self, b, where, ctx):
        heading = b.get("heading", "Materials Required")
        if b.get("columns"):
            cols = [(req(c, "label", where), c.get("items", [])) for c in b["columns"]]
        else:
            cols = [("Consumables", b.get("consumables", [])),
                    ("Reagents", b.get("reagents", [])),
                    ("Equipment", b.get("equipment", []))]
            extra = b.get("other") or {}
            cols += list(extra.items())
        if not any(items for _, items in cols):
            raise SpecError(f"{where}: materials block has no items")
        if heading:
            self.heading(heading)
        widths = scale_widths([1] * len(cols), self.text_w)
        hdr = row([cell(para(runs_xml(lab), style="TableHeader"), w, fill=MAT_FILL)
                   for (lab, _), w in zip(cols, widths)], header=True, cant_split=True)
        cells = []
        for (lab, items), w in zip(cols, widths):
            if items:
                ps = "".join(para(runs_xml(i), style="TableList", num=1) for i in items)
            else:
                ps = para(runs_xml(b.get("empty_text", "None")), style="TableText")
            cells.append(cell(ps, w))
        self.add_tbl(table([hdr, row(cells, cant_split=True)], widths))
        self.outline.append(f"      [materials: {sum(len(i) for _, i in cols)} items]")

    def b_reagent_prep(self, b, where, ctx):
        heading = b.get("heading", "Preparation of reagents")
        rows = req(b, "rows", where)
        if heading:
            self.heading(heading)
        widths = scale_widths([3950, 2050, 3026], self.text_w)
        hdr = row([cell(para(runs_xml(h), style="TableHeader"), w, fill=PREP_FILL)
                   for h, w in zip(("Item", "Storage", "Instruction"), widths)],
                  header=True, cant_split=True)
        out = [hdr]
        # short prep tables stay on one page; longer ones may split (the header row repeats)
        keep = len(rows) <= KEEP_TOGETHER_PREP_ROWS
        for k, r in enumerate(rows):
            if isinstance(r, dict):
                r = [r.get("item", ""), r.get("storage", ""), r.get("instruction", "")]
            if not isinstance(r, list) or len(r) != 3:
                raise SpecError(f"{where}.rows[{k}]: needs [item, storage, instruction]")
            kn = keep and k < len(rows) - 1
            out.append(row([cell(para(runs_xml(v), style="TableText", keep_next=kn), w)
                            for v, w in zip(r, widths)], cant_split=True))
        self.add_tbl(table(out, widths))

    def caption(self, kind, text, numbered=True, below=False):
        if kind == "Table":
            self.table_no += 1
            n = self.table_no
        else:
            self.figure_no += 1
            n = self.figure_no
        if re.match(rf"^\s*{kind}\s*\d+\s*[:.]", text):
            m = re.match(rf"^\s*({kind}\s*\d+\s*[:.])\s*(.*)$", text, re.S)
            body = runs_xml(m.group(1).rstrip(".:") + ": ", b=True) + runs_xml(m.group(2))
        elif numbered:
            body = runs_xml(f"{kind} {n}: ", b=True) + runs_xml(text)
        else:
            body = runs_xml(text)
        self.add_p(para(body, style="SOPCaption", keep_next=not below, jc="center" if below else None,
                        before=60 if below else None, after=240 if below else None))

    def b_table(self, b, where, ctx):
        header = b.get("header") or b.get("columns")
        rows = b.get("rows", [])
        if header is None and not rows:
            raise SpecError(f"{where}: table needs 'header' and/or 'rows'")
        hrows = []
        if header:
            hrows = header if isinstance(header[0], list) else [header]

        def span(c):
            return int(c.get("span", 1)) if isinstance(c, dict) else 1

        ncols = max(sum(span(c) for c in r) for r in hrows + rows)
        for k, r in enumerate(hrows + rows):
            if sum(span(c) for c in r) != ncols:
                self.warnings.append(f"{where}: row {k} has {sum(span(c) for c in r)} "
                                     f"cells, expected {ncols}; padded")
        need, desired = natural_widths(hrows + rows, ncols)
        layout = b.get("layout", "full")
        if layout == "compact":
            if b.get("width_cm"):
                total = int(float(b["width_cm"]) * 567)
            else:
                # just wide enough for each column's desired width
                total = sum(max(d, n + 1) * CHAR_TWIPS + 276 for n, d in zip(need, desired))
            total = max(3400, min(total, self.text_w))
            jc = "center"
        elif layout == "full":
            total = self.text_w
            jc = None
        else:
            raise SpecError(f"{where}: layout must be 'full' or 'compact'")
        if b.get("widths"):
            if len(b["widths"]) != ncols:
                raise SpecError(f"{where}: 'widths' has {len(b['widths'])} values for {ncols} columns")
            widths = scale_widths(b["widths"], total)
        else:
            widths = fit_widths(need, desired, total)
        fill = b.get("header_fill", TABLE_FILL)
        aligns = b.get("align") or []
        first_bold = b.get("first_col_bold", False)
        last = rows[-1] if rows else None
        total_row = b.get("total_row")
        if total_row is None and last:
            first = last[0]["text"] if isinstance(last[0], dict) else last[0]
            total_row = str(first).strip().lower().startswith("total")

        keep = b.get("keep_together", len(rows) <= KEEP_TOGETHER_ROWS)

        def mk_row(r, is_header, bold_row=False, fill_row=None, kn=False):
            cells, col = [], 0
            for c in r:
                sp = span(c)
                txt = c.get("text", "") if isinstance(c, dict) else c
                bold = is_header or bold_row or (first_bold and col == 0) or \
                    (isinstance(c, dict) and c.get("bold"))
                al = (c.get("align") if isinstance(c, dict) else None) or \
                    (aligns[col] if col < len(aligns) else None)
                jcv = {"center": "center", "right": "right"}.get(al)
                w = sum(widths[col:col + sp])
                style = "TableHeader" if is_header else "TableText"
                cells.append(cell(para(runs_xml(txt, b=bool(bold) and not is_header),
                                       style=style, jc=jcv, keep_next=kn),
                                  w, fill=fill_row, span=sp, valign=b.get("valign")))
                col += sp
            while col < ncols:
                cells.append(cell(para(style="TableText", keep_next=kn), widths[col], fill=fill_row))
                col += 1
            return row(cells, header=is_header, cant_split=True)

        if b.get("caption"):
            self.caption("Table", b["caption"], b.get("numbered", True))
        out = [mk_row(r, True, fill_row=fill) for r in hrows]
        for k, r in enumerate(rows):
            out.append(mk_row(r, False, bold_row=bool(total_row) and k == len(rows) - 1,
                              kn=keep and k < len(rows) - 1))
        self.add_tbl(table(out, widths, jc=jc))

    def b_image(self, b, where, ctx):
        path = req(b, "path", where)
        full = path if os.path.isabs(path) else os.path.join(self.base_dir, path)
        if not os.path.exists(full):
            raise SpecError(f"{where}: image not found: {path}")
        ext, pw, ph = image_size(full)
        width_cm = float(b.get("width_cm", 12))
        cx = int(width_cm * 360000)
        cy = int(cx * ph / pw)
        max_cx = int(self.text_w / 1440 * 914400)
        if cx > max_cx:
            cx, cy = max_cx, int(max_cx * ph / pw)
        n = len(self.images) + 1
        rid = f"rIdImg{n}"
        name = f"image{n}.{'png' if ext == 'png' else 'jpeg'}"
        with open(full, "rb") as f:
            self.images.append((rid, name, f.read(), ext))
        drawing = (
            f'<w:r><w:drawing><wp:inline distT="0" distB="0" distL="0" distR="0">'
            f'<wp:extent cx="{cx}" cy="{cy}"/><wp:docPr id="{100 + n}" name="Picture {n}"/>'
            f'<wp:cNvGraphicFramePr><a:graphicFrameLocks noChangeAspect="1"/></wp:cNvGraphicFramePr>'
            f'<a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
            f'<pic:pic><pic:nvPicPr><pic:cNvPr id="{100 + n}" name="{esc(name)}"/><pic:cNvPicPr/></pic:nvPicPr>'
            f'<pic:blipFill><a:blip r:embed="{rid}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill>'
            f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
            f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic>'
            f'</a:graphicData></a:graphic></wp:inline></w:drawing></w:r>')
        self.add_p(para(drawing, style="SOPFigure", keep_next=bool(b.get("caption"))))
        if b.get("caption"):
            self.caption("Figure", b["caption"], b.get("numbered", True), below=True)

    def b_procedure(self, b, where, ctx):
        heading = b.get("heading", "Procedure")
        steps = req(b, "steps", where)
        if heading:
            self.heading(heading)
        if b.get("continue") and ctx is not None and ctx.get("proc_num"):
            num = ctx["proc_num"]
        else:
            num = self.new_num(2)
        if ctx is not None:
            ctx["proc_num"] = num
        count = 0
        for k, s in enumerate(steps):
            w = f"{where}.steps[{k}]"
            if isinstance(s, dict) and "type" in s:
                self.block(s, w, ctx)          # embedded block, numbering carries on
                continue
            count += 1
            nxt = steps[k + 1] if k + 1 < len(steps) else None
            # a step that introduces a table or figure stays on the same page as it
            lead_in = isinstance(nxt, dict) and nxt.get("type") in ("table", "image")
            self.proc_item(s, w, num, 0, keep_next=lead_in)
        self.outline.append(f"      [procedure: {count} numbered steps]")

    def proc_item(self, s, where, num, level, keep_next=False):
        if isinstance(s, str):
            self.add_p(para(runs_xml(s), style="SOPStep" if level == 0 else "SOPSubstep",
                            num=num, ilvl=level, keep_next=keep_next))
            return
        if not isinstance(s, dict) or "text" not in s:
            raise SpecError(f"{where}: a step is text, {{'text', 'substeps'}}, or a block with 'type'")
        self.add_p(para(runs_xml(s["text"]), style="SOPStep" if level == 0 else "SOPSubstep",
                        num=num, ilvl=level, keep_next=keep_next and not s.get("substeps")))
        for k, sub in enumerate(s.get("substeps", [])):
            if isinstance(sub, dict) and "type" in sub:
                self.block(sub, f"{where}.substeps[{k}]", None)
            else:
                self.proc_item(sub, f"{where}.substeps[{k}]", num, min(level + 1, 2))

    def b_troubleshooting(self, b, where, ctx):
        heading = b.get("heading", "Troubleshooting")
        issues = req(b, "issues", where)
        if heading:
            self.heading(heading)
        num = self.new_num(4)
        for k, iss in enumerate(issues):
            w = f"{where}.issues[{k}]"
            self.add_p(para(runs_xml(req(iss, "problem", w)), style="SOPIssue", num=num, ilvl=0))
            if iss.get("cause"):
                self.add_p(para(runs_xml("Cause: ", b=True) + runs_xml(iss["cause"]),
                                style="SOPIssueText"))
            action = iss.get("action")
            if isinstance(action, list):
                self.add_p(para(runs_xml("Corrective action:", b=True), style="SOPIssueText",
                                keep_next=True))
                for a in action:
                    self.add_p(para(runs_xml(a), style="SOPSubstep", num=num, ilvl=1))
            elif action:
                self.add_p(para(runs_xml("Corrective action: ", b=True) + runs_xml(action),
                                style="SOPIssueText"))

    # -- step banner
    def banner(self, n, title, new_page):
        # A shaded, bordered paragraph (not a table): keep-with-next works in Word and
        # LibreOffice, it shows in the navigation pane, and it can't merge with tables.
        prefix = "" if self.opts.get("number_steps", True) is False else f"Step {n}: "
        self.add_p(para(runs_xml(prefix + title), style="StepBanner", page_break=new_page))

    # -- whole document
    def build(self):
        s = self.spec
        title = req(s, "title", "spec")
        self.outline.append(f"Title: {title}")

        # front matter
        first_heading = True
        for key, label in (("purpose", "Purpose"), ("scope", "Scope")):
            if s.get(key):
                self.heading(label, before=0 if first_heading else None)
                first_heading = False
                self.text_block(s[key], key)
                self.outline.append(label)
        for k, sec in enumerate(s.get("front_matter", []) or []):
            w = f"front_matter[{k}]"
            self.heading(req(sec, "heading", w), before=0 if first_heading else None)
            first_heading = False
            self.text_block(sec.get("content", sec.get("text", "")), w + ".content")
            self.outline.append(sec["heading"])

        steps = s.get("steps", [])
        if not steps:
            self.warnings.append("spec has no steps")
        first_new_page = self.opts.get("first_step_new_page", True)
        every_new_page = self.opts.get("steps_new_page", False)
        for n, st in enumerate(steps, 1):
            w = f"steps[{n - 1}]"
            t = req(st, "title", w)
            t = re.sub(r"^\s*step\s*\d+\s*[:.\-]?\s*", "", t, flags=re.I)
            new_page = st.get("new_page")
            if new_page is None:
                new_page = every_new_page or (n == 1 and first_new_page and len(self.body) > 0)
            self.banner(n, t, new_page)
            self.outline.append(f"  Step {n}: {t}")
            if st.get("intro"):
                # the first paragraph under a banner gets a little air above it
                self.text_block(st["intro"], w + ".intro", first_style="StepIntro")
            ctx = {}
            for k, b in enumerate(st.get("content", [])):
                self.block(b, f"{w}.content[{k}]", ctx)

        for k, sec in enumerate(s.get("back_matter", []) or []):
            w = f"back_matter[{k}]"
            self.heading(req(sec, "heading", w), page_break=bool(sec.get("new_page")))
            self.text_block(sec.get("content", sec.get("text", "")), w + ".content")
            self.outline.append(sec["heading"])

        # a body must end with a paragraph
        self.add_p(para(style="Spacer"))
        return self


def req(d, key, where):
    if not isinstance(d, dict) or d.get(key) in (None, "", []):
        raise SpecError(f"{where}: missing '{key}'")
    return d[key]


BLOCK_TYPES = {"heading", "paragraph", "page_break", "section", "bullets", "note", "important",
               "caution", "safe_stop", "materials", "reagent_prep", "table", "image",
               "procedure", "troubleshooting"}


# ---------------------------------------------------------------- package parts
def styles_xml():
    def pstyle(sid, name, ppr="", rpr_="", based="Normal", nxt=None, extra=""):
        n = f'<w:next w:val="{nxt}"/>' if nxt else ""
        return (f'<w:style w:type="paragraph" w:customStyle="1" w:styleId="{sid}"><w:name w:val="{name}"/>'
                f'<w:basedOn w:val="{based}"/>{n}<w:qFormat/>{extra}<w:pPr>{ppr}</w:pPr><w:rPr>{rpr_}</w:rPr></w:style>')

    f = f'<w:rFonts w:ascii="{FONT}" w:hAnsi="{FONT}" w:eastAsia="{FONT}" w:cs="{FONT}"/>'
    s = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        f'<w:styles {W_NS}>',
        f'<w:docDefaults><w:rPrDefault><w:rPr>{f}<w:sz w:val="{BODY_SZ}"/><w:szCs w:val="{BODY_SZ}"/>'
        '<w:lang w:val="en-GB" w:eastAsia="en-US" w:bidi="ar-SA"/></w:rPr></w:rPrDefault>'
        '<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault></w:docDefaults>',
        '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:qFormat/>'
        '<w:pPr><w:spacing w:after="160" w:line="240" w:lineRule="auto"/><w:jc w:val="both"/></w:pPr>'
        f'<w:rPr>{f}<w:sz w:val="{BODY_SZ}"/><w:szCs w:val="{BODY_SZ}"/></w:rPr></w:style>',
        '<w:style w:type="character" w:default="1" w:styleId="DefaultParagraphFont"><w:name w:val="Default Paragraph Font"/><w:uiPriority w:val="1"/><w:semiHidden/><w:unhideWhenUsed/></w:style>',
        '<w:style w:type="table" w:default="1" w:styleId="TableNormal"><w:name w:val="Normal Table"/><w:uiPriority w:val="99"/><w:semiHidden/><w:unhideWhenUsed/>'
        '<w:tblPr><w:tblInd w:w="0" w:type="dxa"/><w:tblCellMar><w:top w:w="0" w:type="dxa"/><w:left w:w="108" w:type="dxa"/>'
        '<w:bottom w:w="0" w:type="dxa"/><w:right w:w="108" w:type="dxa"/></w:tblCellMar></w:tblPr></w:style>',
        '<w:style w:type="numbering" w:default="1" w:styleId="NoList"><w:name w:val="No List"/><w:uiPriority w:val="99"/><w:semiHidden/><w:unhideWhenUsed/></w:style>',
        '<w:style w:type="table" w:styleId="TableGrid"><w:name w:val="Table Grid"/><w:basedOn w:val="TableNormal"/><w:uiPriority w:val="39"/>'
        '<w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:tblPr><w:tblBorders>'
        + "".join(f'<w:{x} w:val="single" w:sz="4" w:space="0" w:color="auto"/>'
                  for x in ("top", "left", "bottom", "right", "insideH", "insideV"))
        + '</w:tblBorders></w:tblPr></w:style>',
        pstyle("SOPHeading", "SOP Heading", '<w:keepNext/><w:keepLines/><w:spacing w:before="240" w:after="80"/><w:jc w:val="left"/><w:outlineLvl w:val="2"/>', "<w:b/><w:bCs/>", nxt="Normal"),
        pstyle("SOPSection", "SOP Sub-stage", '<w:keepNext/><w:keepLines/><w:spacing w:before="280" w:after="80"/><w:ind w:left="425" w:hanging="425"/><w:jc w:val="left"/><w:outlineLvl w:val="1"/>', "<w:b/><w:bCs/>", nxt="Normal"),
        pstyle("StepBanner", "SOP Step Banner",
               '<w:keepNext/><w:keepLines/><w:pBdr>'
               + "".join(f'<w:{s} w:val="single" w:sz="4" w:space="{sp}" w:color="{BANNER_FILL}"/>'
                         for s, sp in (("top", 6), ("left", 4), ("bottom", 6), ("right", 4)))
               + f'</w:pBdr><w:shd w:val="clear" w:color="auto" w:fill="{BANNER_FILL}"/>'
               '<w:spacing w:before="360" w:after="200" w:line="240" w:lineRule="auto"/>'
               '<w:ind w:left="105" w:right="105"/><w:jc w:val="left"/><w:outlineLvl w:val="0"/>',
               '<w:b/><w:bCs/><w:color w:val="FFFFFF"/>', nxt="StepIntro"),
        pstyle("StepIntro", "SOP Step Intro", '<w:keepNext/>', ""),
        pstyle("TableGap", "SOP Table Gap", '<w:spacing w:after="0" w:line="120" w:lineRule="exact"/>',
               '<w:sz w:val="12"/><w:szCs w:val="12"/>'),
        pstyle("SOPStep", "SOP Procedure Step", '<w:spacing w:after="160"/>', ""),
        pstyle("SOPSubstep", "SOP Procedure Sub-step", '<w:spacing w:after="80"/>', ""),
        pstyle("SOPList", "SOP Bullet", '<w:spacing w:after="80"/>', ""),
        pstyle("SOPNote", "SOP Note", '<w:spacing w:after="160"/>', ""),
        pstyle("SOPIssue", "SOP Troubleshooting Issue", '<w:keepNext/><w:spacing w:before="120" w:after="60"/><w:jc w:val="left"/>', "<w:b/><w:bCs/>"),
        pstyle("SOPIssueText", "SOP Troubleshooting Text", '<w:spacing w:after="80"/><w:ind w:left="425"/>', ""),
        pstyle("SOPCaption", "SOP Caption", '<w:keepNext/><w:spacing w:before="120" w:after="80"/>', ""),
        pstyle("SOPFigure", "SOP Figure", '<w:spacing w:before="120" w:after="0"/><w:jc w:val="center"/>', ""),
        pstyle("TableText", "SOP Table Text", '<w:spacing w:after="0"/><w:jc w:val="left"/>', ""),
        pstyle("TableHeader", "SOP Table Header", '<w:keepNext/><w:spacing w:after="0"/><w:jc w:val="left"/>', "<w:b/><w:bCs/>"),
        pstyle("TableList", "SOP Table Bullet", '<w:spacing w:after="0"/><w:jc w:val="left"/>', ""),
        pstyle("Spacer", "SOP Spacer", '<w:spacing w:after="0"/>', ""),
        pstyle("Header", "header", '<w:tabs><w:tab w:val="center" w:pos="4513"/><w:tab w:val="right" w:pos="9026"/></w:tabs><w:spacing w:after="0"/>', ""),
        pstyle("Footer", "footer", '<w:tabs><w:tab w:val="center" w:pos="4513"/><w:tab w:val="right" w:pos="9026"/></w:tabs><w:spacing w:after="0"/>', ""),
        pstyle("HeaderTitle", "SOP Header Title", '<w:spacing w:after="0" w:line="276" w:lineRule="auto"/><w:jc w:val="center"/>',
               f'<w:b/><w:bCs/><w:sz w:val="{TITLE_SZ}"/><w:szCs w:val="{TITLE_SZ}"/>', based="Header"),
        pstyle("FooterText", "SOP Footer Sign-off", '<w:spacing w:after="0"/><w:jc w:val="left"/>',
               f'<w:i/><w:iCs/><w:sz w:val="{FOOTER_SZ}"/><w:szCs w:val="{FOOTER_SZ}"/>', based="Footer"),
        '</w:styles>',
    ]
    return "".join(s)


def numbering_xml(nums):
    def lvl(i, fmt, text, left, hang, font=None, bold=False, start=1):
        r = []
        if font:
            r.append(f'<w:rFonts w:ascii="{font}" w:hAnsi="{font}" w:hint="default"/>')
        if bold:
            r.append("<w:b/><w:bCs/>")
        rp = f"<w:rPr>{''.join(r)}</w:rPr>" if r else ""
        return (f'<w:lvl w:ilvl="{i}"><w:start w:val="{start}"/><w:numFmt w:val="{fmt}"/>'
                f'<w:lvlText w:val="{text}"/><w:lvlJc w:val="left"/>'
                f'<w:pPr><w:ind w:left="{left}" w:hanging="{hang}"/></w:pPr>{rp}</w:lvl>')

    BUL, CIR, SQ = "", "o", ""
    absn = {
        # 0: bullets inside table cells (materials lists)
        0: [lvl(0, "bullet", BUL, 284, 284, "Symbol"), lvl(1, "bullet", CIR, 568, 284, "Courier New"),
            lvl(2, "bullet", SQ, 852, 284, "Wingdings")],
        # 1: body bullets
        1: [lvl(0, "bullet", BUL, 720, 360, "Symbol"), lvl(1, "bullet", CIR, 1440, 360, "Courier New"),
            lvl(2, "bullet", SQ, 2160, 360, "Wingdings")],
        # 2: numbered procedure 1. -> bullet -> circle
        2: [lvl(0, "decimal", "%1.", 425, 425), lvl(1, "bullet", BUL, 851, 426, "Symbol"),
            lvl(2, "bullet", CIR, 1276, 425, "Courier New")],
        # 3: lettered sub-stages A. B. C. (bold)
        3: [lvl(0, "upperLetter", "%1.", 425, 425, bold=True)],
        # 4: troubleshooting 1. issue (bold) -> A. corrective step
        4: [lvl(0, "decimal", "%1.", 425, 425, bold=True), lvl(1, "upperLetter", "%2.", 851, 426),
            lvl(2, "bullet", BUL, 1276, 425, "Symbol")],
    }
    x = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>', f'<w:numbering {W_NS}>']
    for aid, lvls in absn.items():
        x.append(f'<w:abstractNum w:abstractNumId="{aid}"><w:multiLevelType w:val="hybridMultilevel"/>'
                 + "".join(lvls) + "</w:abstractNum>")
    x.append('<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>')
    x.append('<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>')
    for nid, aid in nums:
        ov = "".join(f'<w:lvlOverride w:ilvl="{i}"><w:startOverride w:val="1"/></w:lvlOverride>'
                     for i in range(3))
        x.append(f'<w:num w:numId="{nid}"><w:abstractNumId w:val="{aid}"/>{ov}</w:num>')
    x.append("</w:numbering>")
    return "".join(x)


def header_xml(title):
    # title centred, with a thin rule underneath that runs a little past the margins
    p = ('<w:p><w:pPr><w:pStyle w:val="HeaderTitle"/>'
         '<w:pBdr><w:bottom w:val="single" w:sz="4" w:space="8" w:color="000000"/></w:pBdr>'
         '<w:ind w:left="-567" w:right="-567"/></w:pPr>'
         + runs_xml(title) + "</w:p>")
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:hdr {W_NS}>{p}'
            '<w:p><w:pPr><w:pStyle w:val="Header"/></w:pPr></w:p></w:hdr>')


def footer_xml(lines, text_w):
    pg = ('<w:p><w:pPr><w:pStyle w:val="Footer"/><w:jc w:val="right"/></w:pPr>'
          '<w:fldSimple w:instr=" PAGE "><w:r><w:t>1</w:t></w:r></w:fldSimple></w:p>')
    cell_ps = "".join(f'<w:p><w:pPr><w:pStyle w:val="FooterText"/></w:pPr>{runs_xml(l)}</w:p>'
                      for l in lines) or '<w:p><w:pPr><w:pStyle w:val="FooterText"/></w:pPr></w:p>'
    none = "".join(f'<w:{s} w:val="nil"/>' for s in ("left", "bottom", "right", "insideH", "insideV"))
    tbl = (f'<w:tbl><w:tblPr><w:tblStyle w:val="TableGrid"/><w:tblW w:w="{text_w}" w:type="dxa"/>'
           f'<w:tblBorders><w:top w:val="single" w:sz="4" w:space="0" w:color="000000"/>{none}</w:tblBorders>'
           f'<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid><w:gridCol w:w="{text_w}"/></w:tblGrid>'
           f'<w:tr><w:tc><w:tcPr><w:tcW w:w="{text_w}" w:type="dxa"/></w:tcPr>{cell_ps}</w:tc></w:tr></w:tbl>')
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:ftr {W_NS}>{pg}{tbl}'
            '<w:p><w:pPr><w:pStyle w:val="Footer"/></w:pPr></w:p></w:ftr>')


def footer_lines(spec):
    f = spec.get("footer", {}) or {}
    out = []
    if f.get("lab"):
        out.append(f["lab"])
    for key, label in (("drafted_by", "Drafted by"), ("reviewed_by", "Reviewed by"),
                       ("approved_by", "Approved by"), ("version", "Version"),
                       ("effective_date", "Effective date"), ("review_date", "Next review")):
        if f.get(key):
            out.append(f"{label}: {f[key]}")
    out += f.get("lines", []) or []
    return out


def write_docx(b, out_path):
    s = b.spec
    pw, ph = b.pw, b.ph
    sect = (f'<w:sectPr><w:headerReference w:type="default" r:id="rIdHeader1"/>'
            f'<w:footerReference w:type="default" r:id="rIdFooter1"/>'
            f'<w:pgSz w:w="{pw}" w:h="{ph}"/>'
            f'<w:pgMar w:top="{MARGIN}" w:right="{MARGIN}" w:bottom="{MARGIN}" w:left="{MARGIN}" '
            f'w:header="{HEADER_DIST}" w:footer="{FOOTER_DIST}" w:gutter="0"/>'
            f'<w:cols w:space="708"/><w:docGrid w:linePitch="360"/></w:sectPr>')
    document = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {W_NS}>'
                f'<w:body>{"".join(b.body)}{sect}</w:body></w:document>')

    img_types = {ext for _, _, _, ext in b.images}
    defaults = ('<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>')
    if "png" in img_types:
        defaults += '<Default Extension="png" ContentType="image/png"/>'
    if "jpeg" in img_types:
        defaults += '<Default Extension="jpeg" ContentType="image/jpeg"/>'
    wml = "application/vnd.openxmlformats-officedocument.wordprocessingml"
    ctypes = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' + defaults +
              f'<Override PartName="/word/document.xml" ContentType="{wml}.document.main+xml"/>'
              f'<Override PartName="/word/styles.xml" ContentType="{wml}.styles+xml"/>'
              f'<Override PartName="/word/numbering.xml" ContentType="{wml}.numbering+xml"/>'
              f'<Override PartName="/word/settings.xml" ContentType="{wml}.settings+xml"/>'
              f'<Override PartName="/word/fontTable.xml" ContentType="{wml}.fontTable+xml"/>'
              f'<Override PartName="/word/header1.xml" ContentType="{wml}.header+xml"/>'
              f'<Override PartName="/word/footer1.xml" ContentType="{wml}.footer+xml"/>'
              '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
              '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
              '</Types>')
    R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{R}/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            f'<Relationship Id="rId3" Type="{R}/extended-properties" Target="docProps/app.xml"/>'
            '</Relationships>')
    doc_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                f'<Relationship Id="rIdStyles" Type="{R}/styles" Target="styles.xml"/>'
                f'<Relationship Id="rIdNumbering" Type="{R}/numbering" Target="numbering.xml"/>'
                f'<Relationship Id="rIdSettings" Type="{R}/settings" Target="settings.xml"/>'
                f'<Relationship Id="rIdFonts" Type="{R}/fontTable" Target="fontTable.xml"/>'
                f'<Relationship Id="rIdHeader1" Type="{R}/header" Target="header1.xml"/>'
                f'<Relationship Id="rIdFooter1" Type="{R}/footer" Target="footer1.xml"/>'
                + "".join(f'<Relationship Id="{rid}" Type="{R}/image" Target="media/{name}"/>'
                          for rid, name, _, _ in b.images)
                + '</Relationships>')
    settings = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:settings {W_NS}>'
                '<w:zoom w:percent="100"/><w:defaultTabStop w:val="720"/>'
                '<w:characterSpacingControl w:val="doNotCompress"/>'
                '<w:compat><w:compatSetting w:name="compatibilityMode" '
                'w:uri="http://schemas.microsoft.com/office/word" w:val="15"/></w:compat>'
                '</w:settings>')
    fonts = (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:fonts {W_NS}>'
             f'<w:font w:name="{FONT}"><w:panose1 w:val="020B0502020104020203"/><w:charset w:val="00"/>'
             '<w:family w:val="swiss"/><w:pitch w:val="variable"/></w:font>'
             '<w:font w:name="Symbol"><w:charset w:val="02"/><w:family w:val="roman"/><w:pitch w:val="variable"/></w:font>'
             '<w:font w:name="Courier New"><w:charset w:val="00"/><w:family w:val="modern"/><w:pitch w:val="fixed"/></w:font>'
             '<w:font w:name="Wingdings"><w:charset w:val="02"/><w:family w:val="auto"/><w:pitch w:val="variable"/></w:font>'
             '</w:fonts>')
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    author = esc((s.get("footer") or {}).get("drafted_by", ""))
    core = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{esc(s["title"])}</dc:title><dc:creator>{author}</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified></cp:coreProperties>')
    app = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
           '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties">'
           '<Application>Microsoft Office Word</Application></Properties>')

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ctypes)
        z.writestr("_rels/.rels", rels)
        z.writestr("docProps/core.xml", core)
        z.writestr("docProps/app.xml", app)
        z.writestr("word/document.xml", document)
        z.writestr("word/_rels/document.xml.rels", doc_rels)
        z.writestr("word/styles.xml", styles_xml())
        z.writestr("word/numbering.xml", numbering_xml(b.nums))
        z.writestr("word/settings.xml", settings)
        z.writestr("word/fontTable.xml", fonts)
        z.writestr("word/header1.xml", header_xml(s.get("header_title") or s["title"]))
        z.writestr("word/footer1.xml", footer_xml(footer_lines(s), b.text_w))
        for _, name, data, _ in b.images:
            z.writestr(f"word/media/{name}", data)


def main():
    ap = argparse.ArgumentParser(description="Render an SOP spec (JSON) into the house-style .docx")
    ap.add_argument("spec")
    ap.add_argument("-o", "--output", help="output .docx path (default: <title>.docx)")
    ap.add_argument("--check", action="store_true", help="validate the spec and print an outline only")
    a = ap.parse_args()
    try:
        with open(a.spec, encoding="utf-8") as f:
            spec = json.load(f)
    except json.JSONDecodeError as e:
        sys.exit(f"spec is not valid JSON: {e}")
    try:
        b = Builder(spec, os.path.dirname(os.path.abspath(a.spec))).build()
    except SpecError as e:
        sys.exit(f"spec error: {e}")
    for w in b.warnings:
        print("warning:", w, file=sys.stderr)
    if a.check:
        print("\n".join(b.outline))
        print(f"\nOK: {len(spec.get('steps', []))} steps, {b.table_no} numbered tables, "
              f"{b.figure_no} figures")
        return
    out = a.output or re.sub(r'[\\/:*?"<>|]+', "-", spec["title"]).strip() + ".docx"
    write_docx(b, out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
