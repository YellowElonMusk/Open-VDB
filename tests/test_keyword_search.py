"""Tests for the keyword retrieval mode helpers."""

from src.api.retrieve import _escape_like, keyword_terms, score_keyword_match


class TestKeywordTerms:
    def test_splits_on_whitespace(self):
        assert keyword_terms("reset hydraulic valve") == ["reset", "hydraulic", "valve"]

    def test_short_tokens_dropped(self):
        assert keyword_terms("a hydraulic valve") == ["hydraulic", "valve"]

    def test_single_short_query_kept(self):
        assert keyword_terms("E") == ["E"]


class TestEscapeLike:
    def test_wildcards_escaped(self):
        assert _escape_like("100%") == "100\\%"
        assert _escape_like("E_042") == "E\\_042"
        assert _escape_like("a\\b") == "a\\\\b"


class TestScoreKeywordMatch:
    def test_exact_phrase_scores_one(self):
        content = "Error E-042: replace the servo fuse."
        assert score_keyword_match(content, "E-042", ["E-042"]) == 1.0

    def test_case_insensitive(self):
        assert score_keyword_match("ERROR e-042 DETECTED", "E-042", ["E-042"]) == 1.0

    def test_partial_term_match_below_phrase(self):
        content = "Check the hydraulic system."
        score = score_keyword_match(content, "hydraulic valve", ["hydraulic", "valve"])
        assert 0 < score < 1.0

    def test_all_terms_no_phrase_below_one(self):
        content = "The valve on the hydraulic line."
        score = score_keyword_match(content, "hydraulic valve", ["hydraulic", "valve"])
        assert score == 0.99

    def test_no_match_zero(self):
        assert score_keyword_match("Unrelated text", "E-042", ["E-042"]) == 0.0
