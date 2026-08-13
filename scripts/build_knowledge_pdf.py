"""Renders data/error_knowledge_seed.py into a real, readable PDF.

This PDF is not decorative — app/services/knowledge_base.py extracts its text at
build time and parses it back into entries, using the exact markers laid down
here. Whatever exists in the PDF is what the running app actually knows, so if
you hand-edit the PDF later, re-run scripts/build_knowledge_index.py rather
than the seed data.

Run: python scripts/build_knowledge_pdf.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from data.error_knowledge_seed import ENTRIES

OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "error_knowledge_base.pdf"

NAVY = colors.HexColor("#0b3c7e")
BLUE = colors.HexColor("#1668e3")
INK = colors.HexColor("#14263d")
MUTED = colors.HexColor("#5a6c85")
LINE = colors.HexColor("#d3dfef")
FIELD_BG = colors.HexColor("#eef3fb")

styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    "BHTitle", parent=styles["Title"], textColor=NAVY, fontSize=26, spaceAfter=6,
)
subtitle_style = ParagraphStyle(
    "BHSubtitle", parent=styles["Normal"], textColor=MUTED, fontSize=12,
    alignment=TA_CENTER, spaceAfter=4,
)
entry_title_style = ParagraphStyle(
    "BHEntryTitle", parent=styles["Heading2"], textColor=INK, fontSize=13,
    spaceAfter=2, spaceBefore=0,
)
meta_style = ParagraphStyle(
    "BHMeta", parent=styles["Normal"], textColor=MUTED, fontSize=8.5, spaceAfter=8,
)
field_label_style = ParagraphStyle(
    "BHFieldLabel", parent=styles["Normal"], textColor=NAVY, fontSize=9,
    fontName="Helvetica-Bold", spaceAfter=2,
)
field_body_style = ParagraphStyle(
    "BHFieldBody", parent=styles["Normal"], textColor=INK, fontSize=9.5,
    leading=13, spaceAfter=8,
)
marker_style = ParagraphStyle(
    "BHMarker", parent=styles["Normal"], fontName="Courier", fontSize=7.5,
    textColor=colors.HexColor("#9aa9bd"), spaceAfter=2,
)
patch_style = ParagraphStyle(
    "BHPatch", parent=styles["Code"], fontName="Courier", fontSize=8,
    leading=10.5, backColor=FIELD_BG, borderPadding=6,
)
toc_style = ParagraphStyle(
    "BHToc", parent=styles["Normal"], fontSize=9.5, textColor=INK, leading=14,
)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_entry_flowables(entry: dict) -> list:
    flow = []
    flow.append(Paragraph(f"=== ENTRY {entry['id']} ===", marker_style))
    flow.append(Paragraph(_escape(entry["title"]), entry_title_style))
    flow.append(
        Paragraph(
            f"Language: {_escape(entry['language'])} &nbsp;|&nbsp; "
            f"Framework: {_escape(entry['framework'])} &nbsp;|&nbsp; "
            f"Tags: {_escape(', '.join(entry['tags']))} &nbsp;|&nbsp; "
            f"Confidence: {entry['confidence']:.2f}",
            meta_style,
        )
    )

    flow.append(Paragraph("Error Pattern:", field_label_style))
    flow.append(Paragraph(_escape(entry["error_pattern"]), field_body_style))

    flow.append(Paragraph("Root Cause:", field_label_style))
    flow.append(Paragraph(_escape(entry["root_cause"]), field_body_style))

    flow.append(Paragraph("Fix:", field_label_style))
    flow.append(Paragraph(_escape(entry["fix"]), field_body_style))

    if entry.get("patch", "").strip():
        flow.append(Paragraph("Patch Template:", field_label_style))
        flow.append(Preformatted(entry["patch"].rstrip(), patch_style))
        flow.append(Spacer(1, 6))

    flow.append(Paragraph(f"=== END {entry['id']} ===", marker_style))
    flow.append(Spacer(1, 14))
    line = Table([[""]], colWidths=[6.6 * inch], rowHeights=[0.5])
    line.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE)]))
    flow.append(line)
    flow.append(Spacer(1, 14))
    return flow


def build_pdf() -> Path:
    doc = SimpleDocTemplate(
        str(OUTPUT_PATH),
        pagesize=LETTER,
        topMargin=0.85 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        title="BugHound Error Knowledge Base",
        author="BugHound",
    )

    story = []

    # ---- cover -----------------------------------------------------------
    story.append(Spacer(1, 1.6 * inch))
    story.append(Paragraph("BugHound", title_style))
    story.append(Paragraph("Error Knowledge Base", subtitle_style))
    story.append(Spacer(1, 10))
    story.append(
        Paragraph(
            f"{len(ENTRIES)} recurring error patterns across Python, FastAPI, "
            "LangChain, JavaScript/Node.js, Docker, and deployment. Each entry is a "
            "generic, previously-seen pattern — the running system matches new "
            "errors against this document instead of calling a model when a strong "
            "match exists.",
            subtitle_style,
        )
    )
    story.append(Spacer(1, 40))

    by_framework: dict = {}
    for e in ENTRIES:
        by_framework.setdefault(e["framework"], []).append(e["id"])
    toc_rows = [["Framework", "Entries", "Count"]]
    for fw, ids in sorted(by_framework.items()):
        toc_rows.append([fw, ", ".join(ids), str(len(ids))])
    toc_table = Table(toc_rows, colWidths=[1.6 * inch, 4.2 * inch, 0.7 * inch])
    toc_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, FIELD_BG]),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(toc_table)
    story.append(PageBreak())

    # ---- entries -----------------------------------------------------------
    for entry in ENTRIES:
        story.append(KeepTogether(build_entry_flowables(entry)))

    doc.build(story)
    return OUTPUT_PATH


if __name__ == "__main__":
    path = build_pdf()
    size_kb = path.stat().st_size / 1024
    print(f"Wrote {path} ({size_kb:.0f} KB, {len(ENTRIES)} entries)")
