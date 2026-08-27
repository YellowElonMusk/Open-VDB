"""Shared fixtures: synthetic OEM manuals built with reportlab.

The fixtures mirror the structures that broke the old pipeline — justified
prose, three-column troubleshooting tables with wrapped cells, and a fault
code table with adjacent codes that must never be conflated.
"""

import io

import pytest
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

STYLES = {
    "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=16, leading=20, spaceAfter=6),
    "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13, leading=16, spaceAfter=5),
    # alignment=4 is TA_JUSTIFY — justified prose stresses inter-word spacing
    "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=12, alignment=4),
    "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=10.5),
    "cellh": ParagraphStyle("cellh", fontName="Helvetica-Bold", fontSize=8.5, leading=10.5),
}

TROUBLESHOOTING_HEADER = ["PROBLEM", "POSSIBLE CAUSE", "SOLUTION"]
TROUBLESHOOTING_ROWS = [
    [
        "THE ROBOT DOES NOT START",
        "The battery is out of charge and the onboard charger is disconnected",
        "Perform a complete recharge cycle and attempt restarting the robot.",
    ],
    [
        "THE ROBOT STOPS SUDDENLY",
        "The E-Stop is triggered, indicated by the red lamp on the control panel",
        "Release the E-stop and press the reset button located on the rear panel.",
    ],
    [
        "BRUSH DOES NOT ROTATE",
        "The brush deck is not mounted correctly on the chassis frame",
        "Verify that the deck is mounted and that the locking pin is engaged.",
    ],
]

FAULT_CODE_HEADER = ["CODE", "DESCRIPTION", "ACTION"]
FAULT_CODE_ROWS = [
    ["AF-01-3021-6-1", "Slope is too steep", "Push robot away from slope and try again"],
    ["AF-01-3022-6-1", "Slope is too steep", "Push robot away from slope and try again"],
    ["AE-02-3605-2-4", "Brush motor overcurrent", "Inspect the brush deck for obstructions"],
]

PROSE = (
    "This chapter lists the most frequent faults, their possible causes and the corrective "
    "actions that the operator is authorised to perform. If the fault persists after the "
    "corrective action has been applied, contact the authorised service centre and provide "
    "the fault code shown on the display together with the machine serial number. The rated "
    "supply is 240 Vca, the maximum current is 8.5 A and the protection class is IPX0. "
    "Always isolate the machine before service; there is a notice on the surface of the "
    "panel and the format of the label must not be altered."
)

FRENCH_PROSE = (
    "Ce chapitre indique les pannes les plus fréquentes, leurs causes possibles et les "
    "actions correctives que l'opérateur est autorisé à effectuer. Si la panne persiste "
    "après l'action corrective, contactez le centre de service agréé et indiquez le code "
    "affiché ainsi que le numéro de série de la machine. L'alimentation nominale est de "
    "240 Vca, le courant maximal est de 8.5 A et la classe de protection est IPX0."
)


def _table(header, rows, widths):
    data = [[Paragraph(cell, STYLES["cellh"]) for cell in header]]
    data += [[Paragraph(cell, STYLES["cell"]) for cell in row] for row in rows]
    table = Table(data, colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]
        )
    )
    return table


def build_manual_pdf(title="R3 SCRUB SERVICE MANUAL", prose=PROSE, extra_pages=0) -> bytes:
    """A small manual: heading, justified prose, and two ruled tables."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=18 * mm, bottomMargin=18 * mm)
    story = [
        Paragraph(title, STYLES["h1"]),
        Spacer(1, 4 * mm),
        Paragraph("6. TROUBLESHOOTING", STYLES["h2"]),
        Paragraph(prose, STYLES["body"]),
        Spacer(1, 3 * mm),
        _table(TROUBLESHOOTING_HEADER, TROUBLESHOOTING_ROWS, [45 * mm, 62 * mm, 62 * mm]),
        Spacer(1, 4 * mm),
        Paragraph("6.1 FAULT CODES", STYLES["h2"]),
        _table(FAULT_CODE_HEADER, FAULT_CODE_ROWS, [40 * mm, 55 * mm, 74 * mm]),
    ]
    for index in range(extra_pages):
        story.append(Paragraph(f"7.{index + 1} MAINTENANCE", STYLES["h2"]))
        story.append(Paragraph(prose, STYLES["body"]))
    doc.build(story)
    return buf.getvalue()


@pytest.fixture
def manual_pdf() -> bytes:
    return build_manual_pdf()


@pytest.fixture
def french_manual_pdf() -> bytes:
    return build_manual_pdf(title="R3 VAC MANUEL D'ENTRETIEN", prose=FRENCH_PROSE)
