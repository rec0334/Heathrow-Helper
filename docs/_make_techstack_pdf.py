"""Generate Heathrow Helper — Tech Stack PDF."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
)
from reportlab.lib.enums import TA_LEFT


NAVY = colors.HexColor("#0a1628")
ACCENT_RED = colors.HexColor("#9b1d2a")
GOLD = colors.HexColor("#c9a96e")
INK_MUTED = colors.HexColor("#5b6577")
LINE = colors.HexColor("#e6e0d4")
BG_HEAD = colors.HexColor("#f5f1ea")
BG_ROW = colors.HexColor("#faf7f1")


styles = getSampleStyleSheet()
H1 = ParagraphStyle(
    "H1", parent=styles["Heading1"], fontName="Helvetica-Bold",
    fontSize=24, leading=28, textColor=NAVY, spaceAfter=4
)
SUB = ParagraphStyle(
    "Sub", parent=styles["Normal"], fontName="Helvetica",
    fontSize=10, leading=14, textColor=INK_MUTED, spaceAfter=18
)
H2 = ParagraphStyle(
    "H2", parent=styles["Heading2"], fontName="Helvetica-Bold",
    fontSize=14, leading=18, textColor=ACCENT_RED, spaceBefore=14, spaceAfter=6
)
BODY = ParagraphStyle(
    "Body", parent=styles["Normal"], fontName="Helvetica",
    fontSize=10, leading=14, textColor=NAVY, alignment=TA_LEFT
)
CALLOUT = ParagraphStyle(
    "Callout", parent=BODY, fontName="Helvetica-Oblique",
    fontSize=11, leading=15, textColor=NAVY,
    leftIndent=10, borderPadding=10, spaceBefore=10, spaceAfter=10
)
CELL = ParagraphStyle("Cell", parent=BODY, fontSize=9.5, leading=13)
CELL_BOLD = ParagraphStyle("CellBold", parent=CELL, fontName="Helvetica-Bold")
FOOTER = ParagraphStyle(
    "Footer", parent=BODY, fontSize=8, textColor=INK_MUTED, leading=11
)


def make_table(rows, col_widths):
    """rows[0] is the header. Cells become Paragraphs for wrap support."""
    data = []
    for r, row in enumerate(rows):
        line = []
        for c, cell in enumerate(row):
            style = CELL_BOLD if r == 0 else (CELL_BOLD if c == 0 else CELL)
            line.append(Paragraph(str(cell), style))
        data.append(line)
    t = Table(data, colWidths=col_widths, hAlign="LEFT")
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BG_ROW, colors.white]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING",  (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING",   (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 6),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, GOLD),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, LINE),
    ]))
    # Force header text white (Paragraph would otherwise carry NAVY)
    return t


def header_para(text, style):
    return Paragraph(text, style)


def build(path: str):
    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=18*mm, rightMargin=18*mm,
        topMargin=18*mm, bottomMargin=16*mm,
        title="Heathrow Helper — Tech Stack",
        author="Heathrow Helper",
    )
    story = []

    # Title + subtitle
    story.append(Paragraph("Heathrow Helper", H1))
    story.append(Paragraph(
        "Tech stack reference &mdash; languages, libraries, APIs and infrastructure used to build "
        "<b>heathrow-helper.vercel.app</b>.",
        SUB
    ))

    # Languages
    story.append(Paragraph("Languages", H2))
    story.append(make_table([
        ["Language", "Where it's used"],
        ["Python 3.12", "Backend logic &mdash; <font face='Courier'>bot.py</font> (~2,000 lines), <font face='Courier'>app.py</font> (Flask routes)"],
        ["HTML (Jinja2)", "Page templates &mdash; index, about, privacy, terms, contact"],
        ["CSS3", "Styling &mdash; tokens, base, chat, pages, dark"],
        ["JavaScript (vanilla)", "Chat UI &mdash; <font face='Courier'>static/js/chat.js</font>, no framework"],
        ["JSON", "Static reference data &mdash; 18 files in <font face='Courier'>/data</font>"],
    ], col_widths=[45*mm, None]))

    # Backend
    story.append(Paragraph("Backend &mdash; Python libraries (requirements.txt)", H2))
    story.append(make_table([
        ["Library", "Purpose"],
        ["Flask 3.0+", "Web framework, routing, templates"],
        ["gunicorn", "Production WSGI server (used by Render)"],
        ["requests", "HTTP client for Heathrow + AviationStack APIs"],
        ["python-dotenv", "Loads <font face='Courier'>.env</font> for the AviationStack key locally"],
        ["langdetect", "Detects the user's input language"],
        ["deep-translator", "Translates non-English queries to English"],
    ], col_widths=[45*mm, None]))

    # Frontend
    story.append(Paragraph("Frontend &mdash; runtime libraries (CDN)", H2))
    story.append(make_table([
        ["Library", "Purpose"],
        ["marked v12", "Markdown &rarr; HTML rendering in chat replies"],
        ["DOMPurify v3", "XSS sanitisation of bot output"],
        ["Geist &amp; Geist Mono", "Typography (Google Fonts)"],
    ], col_widths=[45*mm, None]))

    # Data sources
    story.append(Paragraph("Data sources (live APIs)", H2))
    story.append(make_table([
        ["API", "What we use it for"],
        ["Heathrow Data Platform<br/><font size='8' face='Courier'>api-dp-prod.dp.heathrow.com</font>",
         "Live departures/arrivals, status, codeshares, security &amp; immigration waits"],
        ["AviationStack", "Fallback flight lookup for non-LHR flights"],
    ], col_widths=[55*mm, None]))

    # Deployment
    story.append(Paragraph("Deployment &amp; infrastructure", H2))
    story.append(make_table([
        ["Tool", "Purpose"],
        ["Vercel", "Primary host &mdash; <font face='Courier'>heathrow-helper.vercel.app</font> (Python serverless)"],
        ["Render", "Backup host &mdash; <font face='Courier'>heathrow-helper.onrender.com</font>"],
        ["Vercel CLI", "Deploy via <font face='Courier'>vercel deploy --prod</font>"],
        ["Git + GitHub", "Source control &mdash; <font face='Courier'>rec0334/Heathrow-Helper</font>"],
        ["npm", "Used only to install the Vercel CLI globally"],
    ], col_widths=[45*mm, None]))

    story.append(PageBreak())

    # Configuration files
    story.append(Paragraph("Configuration files", H2))
    story.append(make_table([
        ["File", "Used by"],
        ["<font face='Courier'>vercel.json</font>", "Vercel &mdash; rewrites all routes to <font face='Courier'>api/index.py</font>"],
        ["<font face='Courier'>Procfile</font>", "Render &mdash; <font face='Courier'>web: gunicorn app:app</font>"],
        ["<font face='Courier'>runtime.txt</font>", "Render &mdash; pins <font face='Courier'>python-3.12.4</font>"],
        ["<font face='Courier'>.vercelignore</font>", "Vercel &mdash; excludes .env, render configs, tests"],
        ["<font face='Courier'>requirements.txt</font>", "Both hosts &mdash; Python dependency list"],
    ], col_widths=[55*mm, None]))

    # Local dev tools
    story.append(Paragraph("Local dev tools", H2))
    story.append(make_table([
        ["Tool", "Why"],
        ["VS Code / Claude Code", "Editing"],
        ["Playwright", "Mobile + dark-mode screenshot testing"],
        ["curl", "API smoke-testing live endpoints"],
        ["<font face='Courier'>test_live.py</font>", "Live end-to-end tests"],
    ], col_widths=[55*mm, None]))

    # Summary callout
    story.append(Spacer(1, 10))
    story.append(Paragraph("One-line summary", H2))
    summary_tbl = Table([[Paragraph(
        "<b>Python (Flask) backend serving a vanilla-JS chat UI, deployed on Vercel as a Python "
        "serverless function, with live Heathrow API + AviationStack data and ~18 JSON files of "
        "static reference content.</b>",
        ParagraphStyle("S", parent=BODY, fontSize=11, leading=15, textColor=NAVY)
    )]], colWidths=[None])
    summary_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BG_HEAD),
        ("BOX", (0, 0), (-1, -1), 1, GOLD),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
    ]))
    story.append(summary_tbl)

    story.append(Spacer(1, 18))
    story.append(Paragraph(
        "No build step. No framework. No database &mdash; by design, to keep cold start under 1 second and the "
        "codebase scannable in one read.",
        FOOTER
    ))

    doc.build(story)
    print(f"Wrote {path}")


if __name__ == "__main__":
    build(r"C:\Users\chitt\heathrow-bot\docs\heathrow-helper-tech-stack.pdf")
