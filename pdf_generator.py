import io

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


def generate_pdf_sheet(views: dict, dimensions: dict, features: list[dict], filename: str) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A3),
        rightMargin=12 * mm,
        leftMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
    )
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "title",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#f97316"),
        alignment=TA_CENTER,
        spaceAfter=4,
    )
    label = ParagraphStyle(
        "label",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#888888"),
        alignment=TA_CENTER,
    )

    story = [Paragraph(f"Draft AI - {filename}", title), Spacer(1, 4 * mm)]

    table_data = [
        ["Length", "Width", "Height", "Volume"],
        [
            f"{dimensions.get('length', '—')} mm",
            f"{dimensions.get('width', '—')} mm",
            f"{dimensions.get('height', '—')} mm",
            f"{dimensions.get('volume', '—')} mm³",
        ],
    ]
    dim_table = Table(table_data, colWidths=[72 * mm] * 4)
    dim_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f97316")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#1a1a1a")),
                ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#dddddd")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#333333")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#333333")),
            ]
        )
    )
    story.extend([dim_table, Spacer(1, 5 * mm)])

    if features:
        feature_rows = [["Detected Features"]]
        for feature in features:
            items = ", ".join(f"{key}={value}" for key, value in feature.items())
            feature_rows.append([items])
        feature_table = Table(feature_rows, colWidths=[288 * mm])
        feature_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#111111")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#f97316")),
                    ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#dddddd")),
                    ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#333333")),
                    ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#333333")),
                ]
            )
        )
        story.extend([feature_table, Spacer(1, 5 * mm)])

    cells = []
    row = []
    for view in views.values():
        content = []
        if view.get("png"):
            content.append(RLImage(io.BytesIO(view["png"]), width=125 * mm, height=95 * mm))
        else:
            content.append(Paragraph("[view unavailable]", label))
        content.append(Paragraph(view["label"], label))
        row.append(content)
        if len(row) == 2:
            cells.append(row)
            row = []
    if row:
        row += [[""]] * (2 - len(row))
        cells.append(row)

    grid = Table(cells, colWidths=[148 * mm, 148 * mm])
    grid.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8f8f8")),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#333333")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#333333")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story.append(grid)
    doc.build(story)
    return buffer.getvalue()
