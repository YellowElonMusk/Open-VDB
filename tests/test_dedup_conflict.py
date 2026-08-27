"""Deduplication must never merge chunks that state different facts.

    AF-01-3021-6-1 | Slope is too steep - Push robot away from slope
    AF-01-3022-6-1 | Slope is too steep - Push robot away from slope

A plain similarity threshold collapses these two rows and the support
agent starts answering with the wrong fault code. The same hazard exists
across document revisions that restate a sentence with a different value.
"""

from src.ingestion.dedup import deduplicate, fact_fingerprint, skeleton
from src.ingestion.parser import parse_file
from src.ingestion.pipeline import ChunkDraft, chunk_text


def draft(text, source="R3Vac", revision="v0.4", page=14):
    return ChunkDraft(
        text=text,
        source_doc=source,
        revision=revision,
        page=page,
        provenance=[f"{source} {revision} p.{page}"],
    )


class TestFactFingerprint:
    def test_adjacent_fault_codes_have_different_fingerprints(self):
        assert fact_fingerprint("AF-01-3021-6-1 Slope is too steep") != fact_fingerprint(
            "AF-01-3022-6-1 Slope is too steep"
        )

    def test_captures_quantities_units_and_codes(self):
        facts = fact_fingerprint("Rated supply 240 Vca, current 8.5 A, class IPX0")
        assert facts == ("code:IPX0", "qty:240vca", "qty:8.5a")

    def test_240_is_not_confused_with_24(self):
        assert fact_fingerprint("240 Vca") != fact_fingerprint("24 Vca")

    def test_decimal_formatting_is_normalised(self):
        assert fact_fingerprint("8,50 A") == fact_fingerprint("8.5 A")

    def test_skeleton_ignores_values_but_keeps_wording(self):
        assert skeleton("supply is 240 Vca") == skeleton("supply is 230 Vca")
        assert skeleton("supply is 240 Vca") != skeleton("current is 240 Vca")


class TestNeverMergeConflicts:
    def test_adjacent_fault_codes_are_never_merged(self):
        drafts = [
            draft("AF-01-3021-6-1 | Slope is too steep - Push robot away from slope and try again"),
            draft("AF-01-3022-6-1 | Slope is too steep - Push robot away from slope and try again"),
        ]
        survivors = deduplicate(drafts)

        assert len(survivors) == 2
        texts = " ".join(s.text for s in survivors)
        assert "AF-01-3021-6-1" in texts and "AF-01-3022-6-1" in texts

    def test_conflicting_members_are_flagged_for_review(self):
        survivors = deduplicate([
            draft("AF-01-3021-6-1 | Slope is too steep - Push robot away from slope and try again"),
            draft("AF-01-3022-6-1 | Slope is too steep - Push robot away from slope and try again"),
        ])
        assert all(s.needs_review for s in survivors)

    def test_revisions_stating_different_values_both_survive(self):
        """The two R3 Vac revisions restate a sentence with different values."""
        survivors = deduplicate([
            draft("The rated supply is 240 Vca and the maximum current is 8.5 A", revision="v0.4"),
            draft("The rated supply is 230 Vca and the maximum current is 8.5 A", revision="v0.6"),
        ])
        assert len(survivors) == 2
        assert all(s.needs_review for s in survivors)
        assert {"240 Vca" in s.text for s in survivors} == {True, False}

    def test_real_fault_code_table_keeps_every_code(self, manual_pdf):
        drafts = chunk_text(parse_file("R3 Vac Ed.01 v0.4.pdf", manual_pdf))
        survivors = deduplicate(drafts)
        text = " ".join(s.text for s in survivors)
        for code in ("AF-01-3021-6-1", "AF-01-3022-6-1", "AE-02-3605-2-4"):
            assert code in text, f"{code} was lost during deduplication"


class TestMergeDuplicates:
    def test_identical_chunks_merge_and_keep_both_provenances(self):
        survivors = deduplicate([
            draft("Press the green start button and wait for the lamp", source="R3Scrub", page=3),
            draft("Press the green start button and wait for the lamp", source="QuickGuide", page=1),
        ])
        assert len(survivors) == 1
        assert survivors[0].provenance == ["R3Scrub v0.4 p.3", "QuickGuide v0.4 p.1"]
        assert not survivors[0].needs_review

    def test_same_facts_reworded_keeps_the_fullest_wording(self):
        short = draft("Recharge the battery fully before restarting the robot unit", page=2)
        long = draft(
            "Recharge the battery fully before restarting the robot unit and check the charger",
            source="QuickGuide",
            page=9,
        )
        survivors = deduplicate([short, long])
        assert len(survivors) == 1
        assert survivors[0].text == long.text
        assert len(survivors[0].provenance) == 2

    def test_unrelated_chunks_are_left_alone(self):
        drafts = [
            draft("Recharge the battery fully before restarting the robot"),
            draft("Replace the brush deck and tighten the locking pin"),
            draft("Empty the recovery tank after every cleaning cycle"),
        ]
        assert len(deduplicate(drafts)) == 3
