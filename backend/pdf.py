"""The downloadable inspection report (fpdf2, pure Python).

A plain, form-style layout: header fields, a checklist table, issues to address, then photos.
"""
from datetime import datetime

from fpdf import FPDF
from fpdf.fonts import FontFace

from . import config

TEAL = (91, 158, 149)
DARK = (34, 40, 38)
GRAY = (110, 116, 114)
RULE = (214, 220, 218)
RED = (180, 50, 45)
REPLACE = {"…": "...", "–": "-", "—": "-", "‘": "'", "’": "'", "“": '"', "”": '"', "·": "-"}
CHECK = "4"  # ZapfDingbats check mark
ATTRIBUTION = {"new": "New since move-in", "pre-existing": "Pre-existing", "check": "Check against move-in"}


def _t(s) -> str:
    """The built-in PDF fonts only cover Latin-1, so swap out anything else."""
    s = str(s or "")
    for a, b in REPLACE.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _date(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%B %-d, %Y") if iso else datetime.now().strftime("%B %-d, %Y")
    except ValueError:
        return iso or ""


def _time(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%-I:%M %p") if iso else ""
    except ValueError:
        return ""


class Report(FPDF):
    def __init__(self):
        super().__init__(format="Letter")
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(True, margin=18)
        self.alias_nb_pages()
        self.add_page()
        self.w_in = self.w - 32

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GRAY)
        self.cell(self.w_in / 2, 5, "Recorded with InspectAR")
        self.cell(self.w_in / 2, 5, f"Page {self.page_no()} of {{nb}}", align="R")

    # ---- building blocks -------------------------------------------------

    def title_block(self):
        self.set_font("Helvetica", "B", 20)
        self.set_char_spacing(1.2)
        self.set_text_color(*TEAL)
        self.cell(self.get_string_width("HOME INSPECTION "), 10, "HOME INSPECTION ")
        self.set_text_color(*DARK)
        self.cell(40, 10, "REPORT")
        self.set_char_spacing(0)
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(*TEAL)
        self.set_x(self.w - 16 - 40)
        self.cell(40, 10, "InspectAR", align="R")
        self.ln(16)

    def field(self, x, y, w, label, value):
        self.set_xy(x, y)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*GRAY)
        self.cell(w, 4, label.upper())
        self.set_xy(x, y + 4.5)
        self.set_font("Helvetica", "", 10.5)
        self.set_text_color(*DARK)
        self.cell(w, 6, _t(value))
        self.set_draw_color(*RULE)
        self.line(x, y + 11, x + w, y + 11)

    def fields(self, address, date, prepared_by, inspector):
        y = self.get_y()
        left_w = self.w_in * 0.55
        right_x = 16 + left_w + 10
        right_w = self.w_in - left_w - 10
        self.field(16, y, left_w, "Property address", address)
        self.field(right_x, y, right_w, "Date", date)
        self.field(16, y + 15, left_w, "Prepared by", prepared_by)
        self.field(right_x, y + 15, right_w, "Inspector", inspector)
        self.set_y(y + 33)

    def note(self, text):
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*GRAY)
        self.multi_cell(0, 4.6, _t(text))
        self.ln(6)

    def section(self, title):
        if self.get_y() > self.h - 50:
            self.add_page()
        self.set_font("Helvetica", "B", 11)
        self.set_char_spacing(0.8)
        self.set_text_color(*DARK)
        self.cell(0, 7, title.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_char_spacing(0)
        self.ln(1)

    def table_of(self, headings, rows, widths, mark_cols=()):
        """rows: lists of cell values; in mark_cols a truthy value draws a check mark."""
        self.set_font("Helvetica", "", 9)
        self.set_text_color(*DARK)
        self.set_draw_color(*RULE)
        head = FontFace(emphasis="BOLD", color=TEAL, size_pt=9)
        with self.table(col_widths=widths, width=self.w_in, borders_layout="HORIZONTAL_LINES",
                        headings_style=head, line_height=5.2, padding=(2, 2), text_align="LEFT",
                        first_row_as_headings=True) as table:
            row = table.row()
            for h in headings:
                row.cell(h)
            for values in rows:
                row = table.row()
                for i, v in enumerate(values):
                    if i in mark_cols:
                        color = RED if headings[i] == "Flag" else TEAL
                        row.cell(CHECK if v else "", align="C",
                                 style=FontFace(family="zapfdingbats", color=color, size_pt=10))
                    elif isinstance(v, tuple):  # (text, FontFace)
                        row.cell(_t(v[0]), style=v[1])
                    else:
                        row.cell(_t(v))
        self.ln(8)

    def photos(self, items):
        """items: (photo_file, caption). Three per row."""
        if not items:
            return
        cols, gap = 3, 6
        box_w = (self.w_in - gap * (cols - 1)) / cols
        box_h = box_w * 0.75
        if self.get_y() + 10 + box_h + 12 > self.h - 18:  # keep the heading with the first row
            self.add_page()
        self.section("Photos")
        for n, (photo, caption) in enumerate(items):
            col = n % cols
            if col == 0:
                if n:
                    self.set_y(self.get_y() + box_h + 12)
                if self.get_y() + box_h + 12 > self.h - 18:
                    self.add_page()
            x = 16 + col * (box_w + gap)
            y = self.get_y()
            self.set_draw_color(*RULE)
            self.rect(x, y, box_w, box_h)
            try:
                self.image(str(config.PHOTOS_DIR / photo), x=x + 1, y=y + 1, w=box_w - 2, h=box_h - 2,
                           keep_aspect_ratio=True)
            except Exception:
                pass
            self.set_xy(x, y + box_h + 1.5)
            self.set_font("Helvetica", "", 8.5)
            self.set_text_color(*GRAY)
            self.cell(box_w, 5, _t(caption))
            self.set_xy(16, y)
        self.set_y(self.get_y() + box_h + 12)


# ------------------------------------------------------------------ report

SEVERITY_STYLE = {"Safety hazard": FontFace(emphasis="BOLD", color=RED),
                  "Major": FontFace(emphasis="BOLD", color=RED),
                  "Moderate": FontFace(emphasis="BOLD", color=(190, 120, 20)),
                  "Minor": FontFace(color=GRAY)}


def _inspection(pdf: Report, insp: dict, tpl: dict, entries: list[dict]):
    steps = tpl["steps"] if tpl else []
    pdf.fields(insp["property_address"], _date(insp["started_at"]),
               insp["template_name"], insp["inspector"])
    started, finished = _time(insp["started_at"]), _time(insp.get("finished_at"))
    note = (f"Note: Recorded on site with smart glasses, {started}" + (f" to {finished}" if finished else "")
            + ". Photos were taken at the time of inspection. This report does not replace a specialist "
              "assessment (structural, electrical, pest).")
    note += (" The occupant consented to photos and voice notes; audio was not kept." if insp.get("consent")
             else " No occupant consent was recorded.")
    base = insp.get("baseline")
    if base:
        note += f" Compared with the {base.get('label', 'move-in')} record."
    pdf.note(note)

    rows, flagged, photos = [], [], []
    for i, (s, r) in enumerate(zip(steps, insp["results"])):
        a = r.get("ai_fields") or {}
        if r["reading"]:
            notes = f"Reading: {r['reading']}"
        elif r["status"] == "flag":
            notes = a.get("issue") or r["note"] or "See issues below"
            flagged.append((i, s, r, a))
        elif r["status"] == "pending":
            notes = "Not checked"
        else:
            notes = r["note"]
        checked = s["instruction"].removeprefix("Tap to ").capitalize()
        rows.append([s["area"], s["label"], checked, r["status"] == "pass", r["status"] == "flag", notes])
        if r.get("photo_path"):
            photos.append((r["photo_path"], f"{i + 1}. {s['label']}" + (" (flagged)" if r["status"] == "flag" else "")))

    pdf.section("Checklist")
    pdf.table_of(["Area", "Item", "What was checked", "Pass", "Flag", "Notes"], rows,
                 (16, 18, 30, 7, 7, 26), mark_cols=(3, 4))

    if flagged and base:
        pdf.section("Issues to address")
        pdf.table_of(["Item", "Issue", "Severity", "At move-in", "Recommended action"],
                     [[f"{i + 1}. {s['label']}", a.get("issue") or r["note"],
                       (a.get("severity", ""), SEVERITY_STYLE.get(a.get("severity"), FontFace())),
                       _movein(r), a.get("recommendation", "")] for i, s, r, a in flagged],
                     (18, 20, 13, 21, 32))
    elif flagged:
        pdf.section("Issues to address")
        pdf.table_of(["Item", "Issue", "Severity", "Recommended action"],
                     [[f"{i + 1}. {s['label']}", a.get("issue") or r["note"],
                       (a.get("severity", ""), SEVERITY_STYLE.get(a.get("severity"), FontFace())),
                       a.get("recommendation", "")] for i, s, r, a in flagged],
                     (20, 26, 14, 44))

    if entries:
        _entries_table(pdf, entries, "Other items")
        photos += [(e["photo_file"], f"#{e['id']} {e['issue']}") for e in entries if e.get("photo_file")]
    pdf.photos(photos)


def _movein(r: dict) -> str:
    b = r.get("baseline")
    if not b:
        return ATTRIBUTION.get(r.get("attribution"), "")
    said = b.get("note") if b.get("status") == "flag" else (b.get("reading") or "No issues noted")
    tag = ATTRIBUTION.get(r.get("attribution"))
    return f"{said} ({tag.lower()})" if tag else said


def _entries_table(pdf: Report, entries: list[dict], title: str):
    pdf.section(title)
    pdf.table_of(["#", "Issue", "Location", "Severity", "Recommended action"],
                 [[str(e["id"]), e["issue"], e["location"],
                   (e["severity"], SEVERITY_STYLE.get(e["severity"], FontFace())), e["recommendation"]]
                  for e in entries],
                 (6, 24, 22, 14, 38))


def build(entries: list[dict], insp: dict | None = None, tpl: dict | None = None) -> bytes:
    pdf = Report()
    pdf.title_block()
    if insp:
        _inspection(pdf, insp, tpl, entries)
    else:
        pdf.fields(config.PROPERTY_ADDRESS, _date(None), "InspectAR", config.INSPECTOR_NAME)
        pdf.note("Note: Recorded on site with smart glasses. Photos were taken at the time of inspection. "
                 "This report does not replace a specialist assessment (structural, electrical, pest).")
        if entries:
            _entries_table(pdf, entries, "Findings")
            pdf.photos([(e["photo_file"], f"#{e['id']} {e['issue']}") for e in entries if e.get("photo_file")])
        else:
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(*GRAY)
            pdf.cell(0, 8, "Nothing logged yet.")
    return bytes(pdf.output())
