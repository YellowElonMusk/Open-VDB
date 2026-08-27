"""Measure extraction quality before and after the pipeline rebuild.

Runs both extractors over the manuals in samples/ and prints the metrics
side by side. The "before" path is a faithful reproduction of the old
implementation — pypdf in layout mode followed by the whitespace-to-pipe
substitution — kept here only so the delta can be measured. It is not
importable from the application and must never be reintroduced into it.

Usage:  python scripts/quality_report.py
"""

import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.ingestion import quality_gate  # noqa: E402
from src.ingestion.dedup import deduplicate  # noqa: E402
from src.ingestion.parser import KIND_HEADING, KIND_TABLE, parse_file  # noqa: E402
from src.ingestion.pipeline import assessment_text, chunk_text  # noqa: E402

SAMPLES = Path(__file__).resolve().parent.parent / "samples"


# ── Historical extraction path (for benchmarking only) ────────────────

def legacy_extract(content: bytes) -> str:
    """The old _parse_pdf + _clean_pdf_text, reproduced verbatim."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    pages = []
    for page_num, page in enumerate(reader.pages, 1):
        text = page.extract_text(extraction_mode="layout") or page.extract_text()
        if not text:
            continue
        pages.append(f"[Page {page_num}]\n{legacy_clean(text)}")
    return _legacy_dedupe_furniture("\n\n".join(pages), len(reader.pages))


def legacy_clean(text: str) -> str:
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    lines = []
    for line in text.split("\n"):
        if re.search(r"\S\s{4,}\S", line):
            line = re.sub(r"\s{3,}", " | ", line.strip())  # the fabricated-row bug
        else:
            line = re.sub(r" {2,}", " ", line)
        lines.append(line)
    return re.sub(r"\n{4,}", "\n\n\n", "\n".join(lines)).strip()


def _legacy_dedupe_furniture(text: str, page_count: int) -> str:
    if page_count < 3:
        return text
    lines = text.split("\n")
    counts: dict[str, int] = {}
    for line in lines:
        key = re.sub(r"\d+", "#", line.strip())
        if key and len(key) > 5:
            counts[key] = counts.get(key, 0) + 1
    noise = {k for k, v in counts.items() if v >= page_count * 0.6}
    if not noise:
        return text
    return "\n".join(
        line for line in lines if re.sub(r"\d+", "#", line.strip()) not in noise
    )


# ── Reporting ────────────────────────────────────────────────────────

def row(label, before, after, better="lower"):
    if isinstance(before, float) or isinstance(after, float):
        b, a = f"{before:g}", f"{after:g}"
    else:
        b, a = str(before), str(after)
    arrow = ""
    try:
        if float(before) != float(after):
            improved = float(after) < float(before) if better == "lower" else float(after) > float(before)
            arrow = "  ✅" if improved else "  ⚠️"
    except (TypeError, ValueError):
        pass
    return f"  {label:<28} {b:>12}  ->  {a:>12}{arrow}"


def analyse(path: Path) -> None:
    content = path.read_bytes()
    print(f"\n{'=' * 74}\n{path.name}\n{'=' * 74}")

    try:
        before_text = legacy_extract(content)
        before = quality_gate.measure(before_text)
        before_report = quality_gate.assess(before_text)
    except ImportError:
        print("  (pypdf not installed — install it to see the 'before' column)")
        return

    blocks = parse_file(path.name, content)
    after_text = assessment_text(blocks)
    after = quality_gate.measure(after_text)
    after_report = quality_gate.assess(after_text)

    print("\n  EXTRACTION QUALITY" + " " * 22 + "before" + " " * 8 + "after")
    print(row("fused words per 1k words", before["fused_per_1k_words"], after["fused_per_1k_words"]))
    print(row("orphan pipe line ratio", before["orphan_pipe_ratio"], after["orphan_pipe_ratio"]))
    print(row("blank line ratio", before["blank_line_ratio"], after["blank_line_ratio"]))
    print(row("word count", int(before["word_count"]), int(after["word_count"]), better="higher"))

    headings = sum(1 for b in blocks if b.kind == KIND_HEADING)
    table_rows = sum(1 for b in blocks if b.kind == KIND_TABLE)
    legacy_headings = 0  # the old path produced no heading concept at all
    legacy_tables = 0    # nor any real table rows

    print("\n  STRUCTURE RECOVERED")
    print(row("headings", legacy_headings, headings, better="higher"))
    print(row("table rows (header-bound)", legacy_tables, table_rows, better="higher"))

    drafts = chunk_text(blocks)
    survivors = deduplicate(drafts)
    flagged = sum(1 for d in survivors if d.needs_review)
    print("\n  CHUNKING & DEDUP")
    print(f"  {'chunks':<28} {len(drafts):>12}  ->  {len(survivors):>12}  (after dedup)")
    print(f"  {'flagged needs_review':<28} {'':>12}      {flagged:>12}")
    intact = sum(
        1 for d in survivors
        if d.kind == "table" and re.search(r"[A-Z]{2}-\d{2}-\d{3,4}-\d-\d", d.text)
    )
    print(f"  {'fault-code rows intact':<28} {'':>12}      {intact:>12}")

    print("\n  QUALITY GATE")
    print(f"    before: {'PASS' if before_report.passed else 'FAIL'} — {before_report.summary[:150]}")
    print(f"    after:  {'PASS' if after_report.passed else 'FAIL'} — {after_report.summary[:150]}")

    if before_report.passed is False:
        sample = quality_gate.find_fused_words(before_text)[:6]
        if sample:
            print(f"\n  fused examples from the old path: {', '.join(sample)}")


def main() -> None:
    pdfs = sorted(SAMPLES.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs in {SAMPLES}. Run: python scripts/make_samples.py")
        return
    for path in pdfs:
        analyse(path)
    print()


if __name__ == "__main__":
    main()
