from pathlib import Path
import re

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "parkpulse-agent-architecture.md"
OUTPUT_DIR = ROOT / "output" / "pdf"
OUTPUT = OUTPUT_DIR / "parkpulse-agent-architecture.pdf"
FONT_PATH = Path("/Library/Fonts/Arial Unicode.ttf")


def register_fonts() -> tuple[str, str]:
    if FONT_PATH.exists():
        pdfmetrics.registerFont(TTFont("ArialUnicode", str(FONT_PATH)))
        return "ArialUnicode", "ArialUnicode"
    return "Helvetica", "Helvetica-Bold"


BASE_FONT, BOLD_FONT = register_fonts()


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def inline_markup(text: str) -> str:
    text = esc(text)
    text = re.sub(r"`([^`]+)`", r"<font name='Courier'>\1</font>", text)
    text = re.sub(r"\*\*([^*]+)\*\*", rf"<font name='{BOLD_FONT}'>\1</font>", text)
    return text


def make_styles():
    styles = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "TitleZH",
            parent=styles["Title"],
            fontName=BOLD_FONT,
            fontSize=22,
            leading=29,
            textColor=colors.HexColor("#0f172a"),
            spaceAfter=14,
            alignment=TA_LEFT,
        ),
        "h2": ParagraphStyle(
            "H2ZH",
            parent=styles["Heading2"],
            fontName=BOLD_FONT,
            fontSize=15,
            leading=21,
            textColor=colors.HexColor("#0f766e"),
            spaceBefore=12,
            spaceAfter=7,
        ),
        "h3": ParagraphStyle(
            "H3ZH",
            parent=styles["Heading3"],
            fontName=BOLD_FONT,
            fontSize=12.5,
            leading=18,
            textColor=colors.HexColor("#1e293b"),
            spaceBefore=8,
            spaceAfter=5,
        ),
        "body": ParagraphStyle(
            "BodyZH",
            parent=styles["BodyText"],
            fontName=BASE_FONT,
            fontSize=9.5,
            leading=15,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=6,
        ),
        "bullet": ParagraphStyle(
            "BulletZH",
            parent=styles["BodyText"],
            fontName=BASE_FONT,
            fontSize=9.3,
            leading=14,
            leftIndent=16,
            firstLineIndent=-8,
            bulletIndent=4,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=3,
        ),
        "code": ParagraphStyle(
            "CodeZH",
            fontName=BASE_FONT,
            fontSize=8.0,
            leading=11,
            leftIndent=0,
            rightIndent=0,
            textColor=colors.HexColor("#0f172a"),
            backColor=colors.HexColor("#f1f5f9"),
            borderColor=colors.HexColor("#cbd5e1"),
            borderWidth=0.5,
            borderPadding=7,
            spaceBefore=4,
            spaceAfter=8,
        ),
        "table": ParagraphStyle(
            "TableZH",
            fontName=BASE_FONT,
            fontSize=7.8,
            leading=10.5,
            textColor=colors.HexColor("#1f2937"),
        ),
    }


STYLES = make_styles()


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_table_divider(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped) and set(stripped) <= {"|", "-", ":", " "}


def build_table(lines: list[str]):
    rows = [split_table_row(line) for line in lines if not is_table_divider(line)]
    if not rows:
        return Spacer(1, 1)

    max_cols = max(len(row) for row in rows)
    normalized = [row + [""] * (max_cols - len(row)) for row in rows]
    data = [[Paragraph(inline_markup(cell), STYLES["table"]) for cell in row] for row in normalized]
    table = Table(data, repeatRows=1, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e0f2fe")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("FONTNAME", (0, 0), (-1, -1), BASE_FONT),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#cbd5e1")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def parse_markdown(text: str):
    story = []
    lines = text.splitlines()
    i = 0
    in_code = False
    code_lines: list[str] = []

    while i < len(lines):
        line = lines[i]

        if line.strip().startswith("```"):
            if in_code:
                story.append(Preformatted("\n".join(code_lines), STYLES["code"], maxLineLength=96))
                code_lines = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue

        if in_code:
            code_lines.append(line)
            i += 1
            continue

        if not line.strip():
            story.append(Spacer(1, 4))
            i += 1
            continue

        if line.startswith("# "):
            story.append(Paragraph(inline_markup(line[2:].strip()), STYLES["title"]))
            i += 1
            continue

        if line.startswith("## "):
            story.append(Paragraph(inline_markup(line[3:].strip()), STYLES["h2"]))
            i += 1
            continue

        if line.startswith("### "):
            story.append(Paragraph(inline_markup(line[4:].strip()), STYLES["h3"]))
            i += 1
            continue

        if line.strip().startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i])
                i += 1
            story.append(build_table(table_lines))
            story.append(Spacer(1, 8))
            continue

        if line.startswith("- "):
            story.append(Paragraph(inline_markup(line[2:].strip()), STYLES["bullet"], bulletText="•"))
            i += 1
            continue

        if re.match(r"^\d+\. ", line):
            story.append(Paragraph(inline_markup(line.strip()), STYLES["body"]))
            i += 1
            continue

        paragraph_lines = [line.strip()]
        i += 1
        while i < len(lines):
            next_line = lines[i]
            if (
                not next_line.strip()
                or next_line.startswith("#")
                or next_line.startswith("- ")
                or next_line.strip().startswith("|")
                or next_line.strip().startswith("```")
            ):
                break
            paragraph_lines.append(next_line.strip())
            i += 1
        story.append(Paragraph(inline_markup(" ".join(paragraph_lines)), STYLES["body"]))

    return story


class ArchitectureDocTemplate(BaseDocTemplate):
    def __init__(self, filename: str):
        super().__init__(
            filename,
            pagesize=letter,
            leftMargin=0.62 * inch,
            rightMargin=0.62 * inch,
            topMargin=0.68 * inch,
            bottomMargin=0.58 * inch,
            title="ParkPulse AI Architecture",
            author="ParkPulse AI",
        )
        frame = Frame(
            self.leftMargin,
            self.bottomMargin,
            self.width,
            self.height,
            id="normal",
        )
        self.addPageTemplates([PageTemplate(id="main", frames=[frame], onPage=self._draw_footer)])

    def _draw_footer(self, canvas, doc):
        canvas.saveState()
        canvas.setFont(BASE_FONT, 7.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(self.leftMargin, 0.34 * inch, "ParkPulse AI Architecture")
        canvas.drawRightString(letter[0] - self.rightMargin, 0.34 * inch, f"Page {doc.page}")
        canvas.restoreState()


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    story = parse_markdown(SOURCE.read_text(encoding="utf-8"))
    doc = ArchitectureDocTemplate(str(OUTPUT))
    doc.build(story)
    print(OUTPUT)


if __name__ == "__main__":
    main()
