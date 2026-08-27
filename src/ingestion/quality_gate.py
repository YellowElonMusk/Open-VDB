"""Extraction quality gate.

A document that parses to a non-empty string is not a document that was
parsed *correctly*. Corrupted extractions look fine to a length check and
then poison every downstream artifact, so ingestion measures the text and
refuses to publish it when the numbers say it is broken.

Metrics
-------
fused_per_1k_words  Words welded together where a space was destroyed
                    ("isout of charge", "istriggered"). The signature of a
                    grid-snapping text extractor hitting a column boundary.
orphan_pipe_ratio   Lines holding exactly one "|" — the residue of turning
                    column gaps into delimiters without a row model.
blank_line_ratio    Structural padding that crowds out real content.
char_count          Too little text to be a usable document at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Thresholds — exceeding any of these fails the document.
MAX_FUSED_PER_1K_WORDS = 1.0
MAX_ORPHAN_PIPE_RATIO = 0.05
MAX_BLANK_LINE_RATIO = 0.25
MIN_CHARS = 500

# Fusion detection
# ----------------
# A destroyed space welds two words into one token. Detection has to be
# precise: a false positive fails a legitimate document, which is worse
# than not measuring at all.
#
# Three signals are used, all of which appear in the corrupted corpus:
#
#   camel     "indicatedRelease"  — column 2 ran into column 3
#   leading   "isout of charge"   — a function word swallowed the next word
#
# Two other conceivable signals are deliberately NOT used, because without
# a dictionary they flag ordinary prose:
#
#   mid-token   "understanding" (under+and+ing), "performance"
#               (per+for+mance), "authorised" (author+is+ed)
#   end-of-token "chassis" (chass+is), "understand", "compare", "breathe"
#
# English and French are simply too full of those. Every fusion observed
# in the corpus is a leading or camel case, and precision matters more:
# a false positive fails a document that was extracted correctly.

# Function words, kept per language: a French article welded inside an
# English word is not evidence of anything, and checking for it only
# creates false positives ("troubleshooting" contains "les").
_FUNCTION_WORDS = {
    "en": ["is", "are", "not", "for", "and", "the", "with", "that"],
    "fr": ["est", "sont", "pour", "dans", "avec", "les", "des", "une", "sur"],
}

# A lowercase run running straight into a capitalised word.
_FUSED_CAMEL = re.compile(r"[a-zà-ÿ]{2,}[A-ZÀ-Þ][a-zà-ÿ]{2,}")


def _leading_re(words: list[str]) -> re.Pattern:
    return re.compile(rf"\b(?:{'|'.join(words)})[a-zà-ÿ]{{3,}}\b")


_LEADING_RE = {lang: _leading_re(words) for lang, words in _FUNCTION_WORDS.items()}
# Real EN/FR words that begin with a function word. Guards the leading
# rule — a gate that rejects good documents is worse
# than no gate at all.
_NOT_FUSED = frozenset("""
isolate isolated isolates isolating isolation isolator island islands isle
issue issued issues issuing isobar isotope isothermal
area areas arena arenas
note notes noted notice noticed notices noticeable noticing nothing notify
notified notification notifications notion notions notable notably notch
notches notorious notwithstanding
form forms formed formal formally format formats formatted formatting
formation former formerly formula formulas fort forth forty force forced
forces forcing forward forwards foreign forest forests forge forget forgot
fork forks forbid forbidden forecast foreman forever foremost
android andiron
theft their theirs them theme themes themselves then thence theory theories
therapy there thereby therefore thereof these thesis they theatre theater
thermal thermostat thermometer
within without withstand withdraw withdrawal withdrawn withhold
establish established establishes establishing estate estates esteem
estimate estimated estimates estimating estimation
pouring poured pourra pourrait pourront pourrez pourriez
less lesson lessons lessen lesser lest lesion lesions
design designed designs designer designers designation designate desk desks
describe described describes description descriptions descend descent
desert deserve desire desired despite destination destinations destroy
destiné destinée destinés destinées desserrer desserrant desserrage dessiné
destroyed destruction destructive desperate dessus dessous dessin dessins
unemployment uneven unexpected unexpectedly unequal unease uneasy unearth
sure surely surface surfaces surfacing surge surgery surplus surprise
surprising surround surrounded surrounding surveillance survey surveys
survive survival surcharge surtout
""".split())


@dataclass
class Report:
    """Outcome of assessing one extraction."""

    passed: bool
    metrics: dict[str, float]
    failures: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        detail = ", ".join(
            f"{name}={value:g}" for name, value in sorted(self.metrics.items())
        )
        if self.passed:
            return f"extraction quality OK ({detail})"
        return f"extraction quality gate failed: {'; '.join(self.failures)} | measured: {detail}"


def detect_language(text: str) -> str:
    """Pick which function-word set applies. Local to avoid a parser import."""
    words = re.findall(r"[a-zà-ÿ]+", text.lower())[:5000]
    if not words:
        return "en"
    fr = sum(1 for w in words if w in {"le", "la", "les", "des", "une", "est", "pour", "dans", "avec", "sur", "que", "qui"})
    en = sum(1 for w in words if w in {"the", "is", "are", "and", "for", "with", "that", "this", "not", "of", "to", "in"})
    return "fr" if fr > en else "en"


def find_fused_words(text: str, lang: str | None = None) -> list[str]:
    """Return the welded tokens found in `text`."""
    language = lang or detect_language(text)
    lowered = text.lower()

    found = [match.group(0) for match in _FUSED_CAMEL.finditer(text)]
    pattern = _LEADING_RE[language]
    found += [m.group(0) for m in pattern.finditer(lowered) if m.group(0) not in _NOT_FUSED]
    return found


def count_fused_words(text: str, lang: str | None = None) -> int:
    """Count words welded together by a destroyed space."""
    return len(find_fused_words(text, lang))


def measure(text: str) -> dict[str, float]:
    """Compute the raw quality metrics for a block of extracted text."""
    lines = text.split("\n")
    total_lines = len(lines)
    words = len(re.findall(r"\S+", text))

    blank_lines = sum(1 for line in lines if not line.strip())
    orphan_pipes = sum(1 for line in lines if line.count("|") == 1)

    return {
        "char_count": float(len(text)),
        "word_count": float(words),
        "fused_per_1k_words": round(count_fused_words(text) * 1000 / words, 2) if words else 0.0,
        "orphan_pipe_ratio": round(orphan_pipes / total_lines, 3) if total_lines else 0.0,
        "blank_line_ratio": round(blank_lines / total_lines, 3) if total_lines else 0.0,
    }


def assess(text: str) -> Report:
    """Measure an extraction and decide whether it may be published."""
    metrics = measure(text)
    failures: list[str] = []

    if metrics["char_count"] < MIN_CHARS:
        failures.append(f"char_count={metrics['char_count']:g} (min {MIN_CHARS})")
    if metrics["fused_per_1k_words"] > MAX_FUSED_PER_1K_WORDS:
        failures.append(
            f"fused_per_1k_words={metrics['fused_per_1k_words']:g} (max {MAX_FUSED_PER_1K_WORDS})"
        )
    if metrics["orphan_pipe_ratio"] > MAX_ORPHAN_PIPE_RATIO:
        failures.append(
            f"orphan_pipe_ratio={metrics['orphan_pipe_ratio']:g} (max {MAX_ORPHAN_PIPE_RATIO})"
        )
    if metrics["blank_line_ratio"] > MAX_BLANK_LINE_RATIO:
        failures.append(
            f"blank_line_ratio={metrics['blank_line_ratio']:g} (max {MAX_BLANK_LINE_RATIO})"
        )

    return Report(passed=not failures, metrics=metrics, failures=failures)
