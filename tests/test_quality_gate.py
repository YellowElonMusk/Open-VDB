"""The gate must fail corrupted extractions and pass clean ones.

257 KB of fused, pipe-littered text once shipped marked "ready" because
the only check was that the extractor returned a non-empty string.
"""

import pytest

from src.ingestion import quality_gate
from src.ingestion.parser import parse_file
from src.ingestion.pipeline import assessment_text

CORRUPTED = """
THE ROBOT DOES | The battery isout of charge | Perform a complete recharge
NOT START | and attempt restarting the robot.
THE ROBOT STOPS | The E-Stop istriggered, indicatedRelease the E-stop and press
SUDDENLY | the reset button on the panel.
BRUSH DOES NOT | The brush deck is not ismounted correctly on the chassis
ROTATE | frame and the locking pin iscase sensitive.
""" * 12

CLEAN = """
This chapter lists the most frequent faults, their possible causes and the corrective actions
that the operator is authorised to perform. If the fault persists, contact the service centre.
The rated supply is 240 Vca, the maximum current is 8.5 A and the protection class is IPX0.
Always isolate the machine before service. There is a notice on the surface of the panel and
the format of the label must not be altered. Understanding the performance of the chassis
requires estimates established there beforehand.
""" * 12


class TestFusionDetection:
    def test_fails_on_fused_text(self):
        report = quality_gate.assess(CORRUPTED)
        assert not report.passed
        assert any("fused_per_1k_words" in failure for failure in report.failures)

    def test_passes_clean_text(self):
        report = quality_gate.assess(CLEAN)
        assert report.passed, report.summary
        assert report.metrics["fused_per_1k_words"] == 0

    @pytest.mark.parametrize("token", ["isout", "istriggered", "ismounted", "iscase"])
    def test_detects_each_documented_fusion(self, token):
        assert quality_gate.count_fused_words(f"the battery {token} of charge") == 1

    def test_camel_case_column_collision_detected(self):
        assert quality_gate.count_fused_words("The E-Stop is triggered, indicatedRelease the") == 1

    @pytest.mark.parametrize(
        "word",
        ["authorised", "troubleshooting", "persists", "isolate", "format", "notice",
         "surface", "established", "there", "understanding", "performance", "chassis"],
    )
    def test_ordinary_words_are_not_flagged(self, word):
        """A gate that rejects good documents is worse than no gate."""
        assert quality_gate.count_fused_words(f"the {word} of the machine") == 0

    def test_french_words_are_not_flagged_in_french_text(self):
        text = (
            "Le technicien est autorisé à effectuer le dépannage. Les mesures des composants "
            "sont importantes pour la surface et dans le montant restant avant les instructions."
        )
        assert quality_gate.count_fused_words(text) == 0


class TestOtherMetrics:
    def test_fails_on_orphan_pipes(self):
        text = "\n".join(["THE ROBOT DOES | The battery is flat"] * 60 + ["ok line"] * 40)
        report = quality_gate.assess(text)
        assert not report.passed
        assert any("orphan_pipe_ratio" in failure for failure in report.failures)

    def test_fails_on_blank_line_padding(self):
        text = "\n\n".join(["A real line of manual text that says something useful."] * 80)
        report = quality_gate.assess(text)
        assert not report.passed
        assert any("blank_line_ratio" in failure for failure in report.failures)

    def test_fails_on_too_little_text(self):
        report = quality_gate.assess("Short.")
        assert not report.passed
        assert any("char_count" in failure for failure in report.failures)

    def test_summary_reports_measurements(self):
        report = quality_gate.assess(CORRUPTED)
        assert "quality gate failed" in report.summary
        assert "measured:" in report.summary


class TestRealExtraction:
    def test_pdf_extracted_by_the_current_parser_passes(self, manual_pdf):
        blocks = parse_file("R3 Scrub Ed.01 v0.4.pdf", manual_pdf)
        report = quality_gate.assess(assessment_text(blocks))
        assert report.passed, report.summary
