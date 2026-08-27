"""Generate representative OEM manuals for benchmarking the pipeline.

Real service manuals are laid out with absolutely positioned text and
ruled tables, not with a flowing document model. That layout is what
breaks grid-snapping text extractors: when a cell's text ends within one
character cell of the next column, the separating space is destroyed.

These samples reproduce that geometry — tight column gaps, wrapped cells,
repeated page furniture, and adjacent fault codes — so the extraction can
be measured honestly.

Usage:  python scripts/make_samples.py
"""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

WIDTH, HEIGHT = A4
MARGIN = 42
SAMPLES = Path(__file__).resolve().parent.parent / "samples"

BODY_FONT, BODY_SIZE = "Helvetica", 9.5
BOLD_FONT = "Helvetica-Bold"


def wrap(text, font, size, max_width):
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


class ManualWriter:
    def __init__(self, path, title, footer):
        self.c = canvas.Canvas(str(path), pagesize=A4)
        self.title = title
        self.footer = footer
        self.page = 1
        self.y = 0
        self._start_page()

    def _start_page(self):
        # Page furniture, repeated identically on every page.
        self.c.setFont(BODY_FONT, 7.5)
        self.c.drawString(MARGIN, HEIGHT - 28, self.title)
        self.c.drawRightString(WIDTH - MARGIN, HEIGHT - 28, "Service Documentation")
        self.c.line(MARGIN, HEIGHT - 32, WIDTH - MARGIN, HEIGHT - 32)
        self.c.drawString(MARGIN, 26, self.footer)
        self.c.drawRightString(WIDTH - MARGIN, 26, f"Page {self.page}")
        self.y = HEIGHT - 60

    def space(self, amount=10):
        self.y -= amount

    def need(self, amount):
        if self.y - amount < 55:
            self.c.showPage()
            self.page += 1
            self._start_page()

    def heading(self, text, size=13):
        self.need(30)
        self.c.setFont(BOLD_FONT, size)
        self.c.drawString(MARGIN, self.y, text)
        self.y -= size + 6

    def prose(self, text):
        self.c.setFont(BODY_FONT, BODY_SIZE)
        for line in wrap(text, BODY_FONT, BODY_SIZE, WIDTH - 2 * MARGIN):
            self.need(14)
            self.c.setFont(BODY_FONT, BODY_SIZE)
            self.c.drawString(MARGIN, self.y, line)
            self.y -= 12
        self.y -= 4

    def table(self, header, rows, widths, gap=1.0):
        """Fully ruled table with a deliberately tight inter-column gap.

        Every row is ruled, as in real troubleshooting tables — that is what
        keeps a multi-line cell visually attached to its own row. The column
        gap is only 2pt, which is what destroys the separating space in
        extractors that snap glyphs to a character grid.
        """
        xs, x = [], MARGIN
        for width in widths:
            xs.append(x)
            x += width + gap
        table_right = x - gap

        self.need(60)
        top = self.y + 11
        rules = [top]

        self.c.setFont(BOLD_FONT, 8.5)
        for index, cell in enumerate(header):
            self.c.drawString(xs[index], self.y, cell)
        self.y -= 13
        rules.append(self.y + 4)

        def close_block(bottom, boundaries):
            self.c.rect(MARGIN, bottom, table_right - MARGIN, boundaries[0] - bottom)
            for edge in xs[1:]:
                self.c.line(edge - gap / 2, bottom, edge - gap / 2, boundaries[0])
            for rule in boundaries[1:]:
                self.c.line(MARGIN, rule, table_right, rule)

        for row in rows:
            wrapped = [
                wrap(cell, BODY_FONT, 8.5, widths[index]) for index, cell in enumerate(row)
            ]
            height = max(len(lines) for lines in wrapped) * 10.5
            if self.y - height < 60:
                close_block(self.y + 4, rules)
                self.c.showPage()
                self.page += 1
                self._start_page()
                top = self.y + 11
                rules = [top]
                self.c.setFont(BOLD_FONT, 8.5)
                for index, cell in enumerate(header):
                    self.c.drawString(xs[index], self.y, cell)
                self.y -= 13
                rules.append(self.y + 4)

            self.c.setFont(BODY_FONT, 8.5)
            row_y = self.y
            for index, lines in enumerate(wrapped):
                cell_y = row_y
                for line in lines:
                    self.c.drawString(xs[index], cell_y, line)
                    cell_y -= 10.5
            self.y -= height + 3
            rules.append(self.y + 4)

        close_block(self.y + 4, rules)
        self.y -= 14

    def collision_table(self, header, rows, first_width):
        """Troubleshooting table laid out the way real manuals pack it.

        Column 3 starts immediately after the widest line of column 2 —
        roughly one point of clearance. At that spacing an extractor that
        snaps glyphs to a character grid has nowhere to put the separating
        space and welds the columns together ("isout of charge"). This is
        the geometry that produced the corruption in the real corpus.
        """
        self.need(70)
        top = self.y + 11
        rules = [top]
        col2_x = MARGIN + first_width + 1

        self.c.setFont(BOLD_FONT, 8.5)
        self.c.drawString(MARGIN, self.y, header[0])
        self.c.drawString(col2_x, self.y, header[1])
        self.c.drawString(col2_x + 150, self.y, header[2])
        self.y -= 13
        rules.append(self.y + 4)

        right = WIDTH - MARGIN
        for row in rows:
            col1 = wrap(row[0], BODY_FONT, 8.5, first_width - 2)
            col2 = wrap(row[1], BODY_FONT, 8.5, 150)
            widest = max(stringWidth(line, BODY_FONT, 8.5) for line in col2)
            col3_x = col2_x + widest + 1.0
            col3 = wrap(row[2], BODY_FONT, 8.5, max(60, right - col3_x))
            height = max(len(col1), len(col2), len(col3)) * 10.5

            if self.y - height < 60:
                self.c.rect(MARGIN, self.y + 4, right - MARGIN, rules[0] - self.y - 4)
                for rule in rules[1:]:
                    self.c.line(MARGIN, rule, right, rule)
                self.c.showPage()
                self.page += 1
                self._start_page()
                rules = [self.y + 11]
                self.y -= 13
                rules.append(self.y + 4)

            self.c.setFont(BODY_FONT, 8.5)
            for column, x in ((col1, MARGIN), (col2, col2_x), (col3, col3_x)):
                cell_y = self.y
                for line in column:
                    self.c.drawString(x, cell_y, line)
                    cell_y -= 10.5
            self.y -= height + 3
            rules.append(self.y + 4)

        self.c.rect(MARGIN, self.y + 4, right - MARGIN, rules[0] - self.y - 4)
        for rule in rules[1:]:
            self.c.line(MARGIN, rule, right, rule)
        self.y -= 14

    def save(self):
        self.c.save()


TROUBLE_EN = [
    ["THE ROBOT DOES NOT START",
     "The battery is out of charge and the onboard charger is disconnected from the mains",
     "Perform a complete recharge cycle and attempt restarting the robot."],
    ["THE ROBOT STOPS SUDDENLY",
     "The E-Stop is triggered, indicated by the red lamp on the control panel",
     "Release the E-stop and press the reset button located on the rear panel."],
    ["THE BRUSH DOES NOT ROTATE",
     "The brush deck is not mounted correctly on the chassis frame of the machine",
     "Verify that the deck is mounted and that the locking pin is engaged."],
    ["THE MACHINE LEAVES STREAKS",
     "The squeegee blade is worn or the recovery tank is full to the maximum level",
     "Replace the squeegee blade and empty the recovery tank before restarting."],
    ["NO WATER ON THE FLOOR",
     "The solution filter is clogged or the solution tank is empty after a long cycle",
     "Clean the solution filter and refill the tank with clean water."],
]

TROUBLE_FR = [
    ["LE ROBOT NE DEMARRE PAS",
     "La batterie est déchargée et le chargeur embarqué est débranché du secteur",
     "Effectuer un cycle de recharge complet et tenter de redémarrer le robot."],
    ["LE ROBOT S'ARRETE",
     "L'arrêt d'urgence est déclenché, indiqué par le voyant rouge du panneau",
     "Relâcher l'arrêt d'urgence et appuyer sur le bouton de réarmement."],
    ["LA BROSSE NE TOURNE PAS",
     "Le plateau de brosse n'est pas monté correctement sur le châssis de la machine",
     "Vérifier que le plateau est monté et que la goupille est engagée."],
    ["LA MACHINE LAISSE DES TRACES",
     "La lame du suceur est usée ou le réservoir de récupération est plein",
     "Remplacer la lame du suceur et vider le réservoir avant de redémarrer."],
]

FAULT_CODES = [
    ("AF-01-3021-6-1", "Slope is too steep", "Push robot away from slope and try again"),
    ("AF-01-3022-6-1", "Slope is too steep", "Push robot away from slope and try again"),
    ("AF-01-3023-6-1", "Slope angle sensor fault", "Restart the machine and recalibrate the sensor"),
    ("AE-02-3605-2-4", "Brush motor overcurrent", "Inspect the brush deck for obstructions"),
    ("AE-02-3606-2-4", "Brush motor overtemperature", "Allow the motor to cool before restarting"),
    ("AE-03-1204-1-2", "Solution pump failure", "Check the pump connector and the solution filter"),
    ("AE-03-1205-1-2", "Solution level low", "Refill the solution tank with clean water"),
    ("AH-04-2200-3-1", "Battery voltage below minimum", "Recharge the battery for at least 8 h"),
    ("AH-04-2201-3-1", "Battery temperature high", "Stop charging and let the battery cool"),
    ("AH-05-7710-5-3", "Drive wheel encoder mismatch", "Inspect the encoder wiring on both wheels"),
    ("AK-06-4402-2-2", "Recovery tank full", "Empty the recovery tank and restart the cycle"),
    ("AK-06-4403-2-2", "Recovery tank sensor fault", "Clean the float sensor inside the tank"),
    ("AM-07-9001-4-1", "Navigation map missing", "Reload the cleaning map from the operator panel"),
    ("AM-07-9002-4-1", "Localisation lost", "Move the robot to a known start point and restart"),
]

FAULT_CODES_FR = [
    ("AF-01-3021-6-1", "La pente est trop raide", "Éloigner le robot de la pente et réessayer"),
    ("AF-01-3022-6-1", "La pente est trop raide", "Éloigner le robot de la pente et réessayer"),
    ("AF-01-3023-6-1", "Défaut capteur d'inclinaison", "Redémarrer la machine et recalibrer le capteur"),
    ("AE-02-3605-2-4", "Surintensité moteur de brosse", "Inspecter le plateau de brosse"),
    ("AE-02-3606-2-4", "Surchauffe moteur de brosse", "Laisser refroidir le moteur avant de redémarrer"),
    ("AE-03-1204-1-2", "Défaut pompe de solution", "Vérifier le connecteur et le filtre de solution"),
    ("AE-03-1205-1-2", "Niveau de solution bas", "Remplir le réservoir avec de l'eau propre"),
    ("AH-04-2200-3-1", "Tension batterie sous le minimum", "Recharger la batterie pendant au moins 8 h"),
    ("AH-04-2201-3-1", "Température batterie élevée", "Arrêter la charge et laisser refroidir"),
    ("AH-05-7710-5-3", "Écart codeur roue motrice", "Inspecter le câblage des codeurs des deux roues"),
    ("AK-06-4402-2-2", "Réservoir de récupération plein", "Vider le réservoir et relancer le cycle"),
    ("AK-06-4403-2-2", "Défaut capteur de réservoir", "Nettoyer le flotteur à l'intérieur du réservoir"),
    ("AM-07-9001-4-1", "Carte de navigation absente", "Recharger la carte depuis le panneau opérateur"),
    ("AM-07-9002-4-1", "Localisation perdue", "Placer le robot à un point de départ connu"),
]

SPEC_EN = (
    "The rated supply is 240 Vca and the maximum absorbed current is 8.5 A. The protection "
    "class is IPX0 and the machine must not be operated outdoors. The sound pressure level "
    "is 68 dB and the total mass with batteries is 143 kg."
)
SPEC_FR = (
    "L'alimentation nominale est de 240 Vca et le courant maximal absorbé est de 8.5 A. La "
    "classe de protection est IPX0 et la machine ne doit pas être utilisée à l'extérieur. Le "
    "niveau de pression acoustique est de 68 dB et la masse totale est de 143 kg."
)

INTRO_EN = (
    "This manual describes the operation and routine maintenance of the machine. It is "
    "intended for operators who have been authorised and trained by the service centre. "
    "Read the safety chapter before performing any operation. The machine must be isolated "
    "from the supply before any maintenance is carried out, and the format of the safety "
    "labels must not be altered. There is a notice on the surface of the control panel."
)
INTRO_FR = (
    "Ce manuel décrit le fonctionnement et l'entretien courant de la machine. Il est destiné "
    "aux opérateurs autorisés et formés par le centre de service. Lire le chapitre de "
    "sécurité avant toute opération. La machine doit être isolée du secteur avant tout "
    "entretien et les étiquettes de sécurité ne doivent pas être modifiées."
)

MAINT_EN = (
    "Check the squeegee blades daily and replace them when the edge is rounded. Clean the "
    "solution filter weekly and inspect the brush deck for entangled debris. The battery "
    "connector must be inspected monthly for corrosion and the terminals tightened to 8 Nm."
)
MAINT_FR = (
    "Contrôler les lames du suceur chaque jour et les remplacer lorsque l'arête est arrondie. "
    "Nettoyer le filtre de solution chaque semaine et inspecter le plateau de brosse. Le "
    "connecteur de batterie doit être inspecté tous les mois et serré à 8 Nm."
)


MAINTENANCE_SECTIONS_EN = [
    ("SQUEEGEE ASSEMBLY",
     "Remove the squeegee by loosening the two knobs on the support arm. Wash the blades in "
     "clean water and inspect the rubber edge for cuts. A rounded edge leaves streaks on the "
     "floor and must be replaced. Refit the assembly and tighten the knobs to 4 Nm."),
    ("BRUSH DECK",
     "Lower the deck fully before removing the brushes. Rotate each brush anticlockwise to "
     "release it from the hub. Remove entangled fibres and check that the hub is not worn. "
     "The deck must be mounted squarely on the chassis before the machine is restarted."),
    ("SOLUTION AND RECOVERY TANKS",
     "Drain the recovery tank through the hose at the rear of the machine. Rinse both tanks "
     "with clean water at the end of every shift. Inspect the float sensor inside the recovery "
     "tank and clear any deposits, otherwise the tank-full fault will be reported early."),
    ("BATTERY AND CHARGER",
     "The battery must be charged in a ventilated area. Do not interrupt a charge cycle before "
     "completion. Inspect the connector monthly for corrosion and tighten the terminals to "
     "8 Nm. A battery held below the minimum voltage for a long period will not recover."),
    ("DRIVE SYSTEM",
     "Check the drive wheels for embedded debris and confirm that both encoders report the "
     "same distance after a test run. A mismatch between the two encoders indicates a wiring "
     "fault and is reported by the machine as a drive system fault code."),
]

SPARE_PARTS = [
    ("AE-02-3605-2-4", "Brush motor assembly 24 V", "1", "8.5 A"),
    ("AE-02-3610-2-4", "Brush hub, left", "1", "-"),
    ("AE-02-3611-2-4", "Brush hub, right", "1", "-"),
    ("AK-06-4402-2-2", "Recovery tank float sensor", "1", "24 Vcc"),
    ("AK-06-4410-2-2", "Recovery tank drain hose", "1", "-"),
    ("AH-04-2200-3-1", "Battery pack 240 Vca charger", "1", "8.5 A"),
    ("AH-04-2210-3-1", "Battery connector kit", "1", "-"),
    ("AM-07-9001-4-1", "Operator panel display", "1", "24 Vcc"),
    ("AM-07-9010-4-1", "Emergency stop button", "1", "-"),
    ("AF-01-3021-6-1", "Slope sensor module", "1", "24 Vcc"),
    ("AS-08-5501-1-1", "Squeegee blade, front", "2", "-"),
    ("AS-08-5502-1-1", "Squeegee blade, rear", "2", "-"),
    ("AS-08-5510-1-1", "Squeegee support arm", "1", "-"),
    ("AP-09-6600-2-3", "Solution pump 24 V", "1", "3.2 A"),
    ("AP-09-6610-2-3", "Solution filter cartridge", "1", "-"),
    ("AD-10-7700-5-3", "Drive wheel encoder", "2", "5 Vcc"),
]

SAFETY_EN = (
    "Only personnel authorised and trained by the service centre may open the electrical "
    "compartment. Isolate the machine from the supply and wait five minutes before removing "
    "any cover. The machine must not be washed with a pressure washer. Do not operate the "
    "machine on a slope steeper than the maximum stated in the technical specification."
)

MAINTENANCE_SECTIONS_FR = [
    ("ENSEMBLE SUCEUR",
     "Déposer le suceur en desserrant les deux molettes du bras support. Laver les lames à "
     "l'eau claire et inspecter l'arête en caoutchouc. Une arête arrondie laisse des traces "
     "sur le sol et doit être remplacée. Reposer l'ensemble et serrer les molettes à 4 Nm."),
    ("PLATEAU DE BROSSE",
     "Abaisser complètement le plateau avant de déposer les brosses. Tourner chaque brosse "
     "dans le sens antihoraire pour la libérer du moyeu. Retirer les fibres enroulées et "
     "vérifier que le moyeu n'est pas usé avant de remonter le plateau sur le châssis."),
    ("RESERVOIRS",
     "Vidanger le réservoir de récupération par le tuyau situé à l'arrière de la machine. "
     "Rincer les deux réservoirs à l'eau claire à la fin de chaque service. Inspecter le "
     "flotteur du réservoir de récupération et éliminer les dépôts éventuels."),
    ("BATTERIE ET CHARGEUR",
     "La batterie doit être chargée dans un local ventilé. Ne pas interrompre un cycle de "
     "charge avant sa fin. Inspecter le connecteur chaque mois et serrer les bornes à 8 Nm. "
     "Une batterie maintenue sous la tension minimale pendant une longue période est perdue."),
]

SAFETY_FR = (
    "Seul le personnel autorisé et formé par le centre de service peut ouvrir le compartiment "
    "électrique. Isoler la machine du secteur et attendre cinq minutes avant de déposer un "
    "carter. La machine ne doit pas être lavée au nettoyeur haute pression. Ne pas utiliser "
    "la machine sur une pente supérieure à la valeur maximale indiquée."
)


def build_english():
    path = SAMPLES / "R3-Scrub-Service-Manual-Ed.01-v0.4.pdf"
    m = ManualWriter(path, "R3 SCRUB | SERVICE MANUAL", "R3 Scrub Ed.01 v0.4")
    m.heading("R3 SCRUB SERVICE MANUAL", 16)
    m.heading("1. INTRODUCTION")
    m.prose(INTRO_EN)
    m.heading("2. TECHNICAL SPECIFICATION")
    m.prose(SPEC_EN)
    m.heading("6. TROUBLESHOOTING")
    m.prose(
        "This chapter lists the most frequent faults, their possible causes and the corrective "
        "actions that the operator is authorised to perform. If the fault persists after the "
        "corrective action has been applied, contact the authorised service centre and provide "
        "the fault code shown on the display together with the machine serial number."
    )
    m.collision_table(["PROBLEM", "POSSIBLE CAUSE", "SOLUTION"], TROUBLE_EN, 126)
    m.heading("6.1 FAULT CODES")
    m.prose("The machine reports faults using structured codes shown on the operator display.")
    m.table(["CODE", "DESCRIPTION", "ACTION"],
            [list(row) for row in FAULT_CODES], [110, 156, 220])
    m.heading("7. ROUTINE MAINTENANCE")
    m.prose(MAINT_EN)
    for number, (name, body) in enumerate(MAINTENANCE_SECTIONS_EN, start=1):
        m.heading(f"7.{number} {name}", 11)
        m.prose(body)
    m.heading("8. SAFETY")
    m.prose(SAFETY_EN)
    m.heading("9. SPARE PARTS")
    m.prose(
        "Order spare parts using the part number shown below together with the machine serial "
        "number. Parts marked with a rating must be replaced with an identical rating."
    )
    m.table(["PART NUMBER", "DESCRIPTION", "QTY", "RATING"],
            [list(row) for row in SPARE_PARTS], [110, 210, 45, 90])
    m.save()
    return path


def build_french():
    path = SAMPLES / "R3-Vac-Manuel-Entretien-Ed.01-v0.6.pdf"
    m = ManualWriter(path, "R3 VAC | MANUEL D'ENTRETIEN", "R3 Vac Ed.01 v0.6")
    m.heading("R3 VAC MANUEL D'ENTRETIEN", 16)
    m.heading("1. INTRODUCTION")
    m.prose(INTRO_FR)
    m.heading("2. CARACTERISTIQUES TECHNIQUES")
    m.prose(SPEC_FR)
    m.heading("6. DEPANNAGE")
    m.prose(
        "Ce chapitre indique les pannes les plus fréquentes, leurs causes possibles et les "
        "actions correctives que l'opérateur est autorisé à effectuer. Si la panne persiste "
        "après l'action corrective, contacter le centre de service agréé et indiquer le code "
        "affiché ainsi que le numéro de série de la machine."
    )
    m.collision_table(["PROBLEME", "CAUSE POSSIBLE", "SOLUTION"], TROUBLE_FR, 126)
    m.heading("6.1 CODES DE PANNE")
    m.prose("La machine signale les pannes au moyen de codes structurés affichés à l'écran.")
    m.table(["CODE", "DESCRIPTION", "ACTION"],
            [list(row) for row in FAULT_CODES_FR], [110, 156, 220])
    m.heading("7. ENTRETIEN COURANT")
    m.prose(MAINT_FR)
    for number, (name, body) in enumerate(MAINTENANCE_SECTIONS_FR, start=1):
        m.heading(f"7.{number} {name}", 11)
        m.prose(body)
    m.heading("8. SECURITE")
    m.prose(SAFETY_FR)
    m.heading("9. PIECES DETACHEES")
    m.prose(
        "Commander les pièces détachées en indiquant la référence ci-dessous ainsi que le "
        "numéro de série de la machine. Les pièces avec une caractéristique doivent être "
        "remplacées par une pièce identique."
    )
    m.table(["REFERENCE", "DESIGNATION", "QTE", "CARACTERISTIQUE"],
            [list(row) for row in SPARE_PARTS], [110, 210, 45, 90])
    m.save()
    return path


if __name__ == "__main__":
    SAMPLES.mkdir(exist_ok=True)
    for builder in (build_english, build_french):
        path = builder()
        print(f"wrote {path.relative_to(SAMPLES.parent)} ({path.stat().st_size:,} bytes)")
