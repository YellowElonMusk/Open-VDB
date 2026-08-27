"""Near-duplicate collapsing with fact-conflict protection.

OEM corpora restate the same procedure across a manual, a quick guide and
a wallchart, and ship overlapping revisions of the same document. Left
alone that produces duplicate vectors, duplicate top_k slots, and — worst —
two chunks that read almost identically but state different values.

Grouping is MinHash + LSH over 3-word shingles, with a bag-of-words
fallback for chunks too short to shingle usefully. Merging is then decided
by a *fact fingerprint*: the multiset of every number, unit, tolerance and
code-like token in the chunk.

    normalised text equal -> merge, union the provenance
    fingerprints equal    -> merge, keep the fullest wording
    fingerprints differ   -> NEVER merge; keep every member, flag for review

The last rule is what stops

    AF-01-3021-6-1 | Slope is too steep - Push robot away from slope
    AF-01-3022-6-1 | Slope is too steep - Push robot away from slope

from collapsing into one chunk and the agent citing the wrong fault code.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.ingestion.pipeline import ChunkDraft

# MinHash / LSH configuration. 64 permutations in 16 bands of 4 rows puts
# the S-curve inflection near Jaccard 0.5, so restatements become candidate
# pairs while unrelated chunks rarely do.
NUM_PERM = 64
BANDS = 16
ROWS = NUM_PERM // BANDS
SHINGLE_SIZE = 3
# Candidate pairs below this Jaccard are discarded before merging. Set at
# the LSH inflection point: grouping is safe because merging still requires
# identical fact fingerprints, so a loose group only means "look closer".
SIMILARITY_THRESHOLD = 0.5
# Chunks with fewer tokens than this use the bag-of-words path instead.
SHORT_CHUNK_TOKENS = 12
SHORT_CHUNK_JACCARD = 0.8

_MERSENNE = (1 << 61) - 1

# Structured identifiers: AE-02-3605-2-4, AF-01-3021-6-1, IPX0, RX-500.
_CODE_RE = re.compile(r"\b[A-Za-z]{1,4}[-_]?\d{1,4}(?:[-_]\d{1,4}){1,5}\b|\bIPX?\d+\b")
# Quantities with a unit: 240 Vca, 8.5 A, 50 mm, 20 °C, 95 %.
_UNIT_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*"
    r"(V(?:ca|cc|ac|dc)?|kV|mA|A|kW|W|Hz|kHz|mm|cm|m|km|kg|g|mg|L|l|ml|bar|Pa|kPa"
    r"|°C|°F|%|Nm|rpm|min|h|s|dB|Ah|Wh)\b",
    re.IGNORECASE,
)
_TOLERANCE_RE = re.compile(r"±\s*\d+(?:[.,]\d+)?")
_TOLERANCE_STRIP_RE = re.compile(r"[±\s]")
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
_TOKEN_RE = re.compile(r"[a-z0-9à-ÿ]+")
_DIGIT_RUN_RE = re.compile(r"\d+")
# A skeleton needs at least this many tokens before it is trusted to group.
MIN_SKELETON_TOKENS = 4


def normalise(text: str) -> str:
    """Case/punctuation/whitespace-insensitive form for equality testing."""
    lowered = text.lower()
    lowered = re.sub(r"[^\w\s]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _num(value: str) -> str:
    """Canonical numeric form: 8,50 -> 8.5, but 240 stays 240."""
    text = value.replace(",", ".")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def fact_fingerprint(text: str) -> tuple[str, ...]:
    """The sorted multiset of facts asserted by a chunk.

    Two chunks with different fingerprints make different factual claims,
    however similar their wording, and must never be merged.
    """
    facts: list[str] = []
    remaining = text

    for match in _CODE_RE.finditer(text):
        facts.append(f"code:{match.group(0).upper().replace('_', '-')}")
    remaining = _CODE_RE.sub(" ", remaining)

    for match in _TOLERANCE_RE.finditer(remaining):
        value = _TOLERANCE_STRIP_RE.sub("", match.group(0))
        facts.append(f"tol:{_num(value)}")
    remaining = _TOLERANCE_RE.sub(" ", remaining)

    for match in _UNIT_RE.finditer(remaining):
        facts.append(f"qty:{_num(match.group(1))}{match.group(2).lower()}")
    remaining = _UNIT_RE.sub(" ", remaining)

    for match in _NUMBER_RE.finditer(remaining):
        facts.append(f"num:{_num(match.group(0))}")

    return tuple(sorted(facts))


def skeleton(text: str) -> str:
    """Wording with every numeric value blanked out.

    Two chunks sharing a skeleton but differing in fingerprint are the
    dangerous case: same sentence, different values. Grouping on the
    skeleton catches them deterministically, where a similarity threshold
    might not — a one-token difference in a short row can fall below any
    reasonable cutoff.
    """
    return _DIGIT_RUN_RE.sub("#", normalise(text))


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(normalise(text))


def _shingles(tokens: list[str]) -> set[str]:
    if len(tokens) < SHINGLE_SIZE:
        return {" ".join(tokens)} if tokens else set()
    return {
        " ".join(tokens[i : i + SHINGLE_SIZE])
        for i in range(len(tokens) - SHINGLE_SIZE + 1)
    }


def _hash(value: str) -> int:
    return int.from_bytes(hashlib.blake2b(value.encode(), digest_size=8).digest(), "big")


def _minhash(shingles: set[str]) -> tuple[int, ...]:
    """MinHash signature using a family of (a*x + b) mod prime permutations."""
    if not shingles:
        return tuple([0] * NUM_PERM)
    hashes = [_hash(s) for s in shingles]
    signature = []
    for i in range(NUM_PERM):
        a = 2 * i + 1
        b = _hash(f"seed{i}") % _MERSENNE
        signature.append(min(((a * h + b) % _MERSENNE) for h in hashes))
    return tuple(signature)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


class _UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _candidate_pairs(signatures: list[tuple[int, ...]]) -> set[tuple[int, int]]:
    """LSH banding: chunks sharing any band are candidates."""
    pairs: set[tuple[int, int]] = set()
    for band in range(BANDS):
        buckets: dict[tuple, list[int]] = defaultdict(list)
        start = band * ROWS
        for index, signature in enumerate(signatures):
            buckets[signature[start : start + ROWS]].append(index)
        for members in buckets.values():
            if len(members) < 2:
                continue
            for i, left in enumerate(members):
                for right in members[i + 1 :]:
                    pairs.add((left, right))
    return pairs


def _union_provenance(members: Iterable) -> list[str]:
    seen: list[str] = []
    for member in members:
        for entry in member.provenance or []:
            if entry not in seen:
                seen.append(entry)
    return seen


def deduplicate(drafts: list["ChunkDraft"]) -> list["ChunkDraft"]:
    """Collapse restatements while preserving every distinct factual claim."""
    if len(drafts) < 2:
        return drafts

    token_lists = [_tokens(draft.text) for draft in drafts]
    shingle_sets = [_shingles(tokens) for tokens in token_lists]
    signatures = [_minhash(shingles) for shingles in shingle_sets]

    union = _UnionFind(len(drafts))

    for left, right in _candidate_pairs(signatures):
        if _jaccard(shingle_sets[left], shingle_sets[right]) >= SIMILARITY_THRESHOLD:
            union.union(left, right)

    # Short chunks produce too few shingles for LSH to be reliable, so
    # compare them by token set instead.
    # Same wording, different numbers — group them so the fingerprint rule
    # can flag the disagreement instead of letting it pass unnoticed.
    by_skeleton: dict[str, list[int]] = defaultdict(list)
    for index, draft in enumerate(drafts):
        key = skeleton(draft.text)
        if len(key.split()) >= MIN_SKELETON_TOKENS:
            by_skeleton[key].append(index)
    for indices in by_skeleton.values():
        for other in indices[1:]:
            union.union(indices[0], other)

    short = [i for i, tokens in enumerate(token_lists) if len(tokens) < SHORT_CHUNK_TOKENS]
    for position, left in enumerate(short):
        for right in short[position + 1 :]:
            if union.find(left) == union.find(right):
                continue
            left_set, right_set = set(token_lists[left]), set(token_lists[right])
            if _jaccard(left_set, right_set) >= SHORT_CHUNK_JACCARD:
                union.union(left, right)

    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(len(drafts)):
        groups[union.find(index)].append(index)

    survivors: list[tuple[int, "ChunkDraft"]] = []

    for members in groups.values():
        if len(members) == 1:
            survivors.append((members[0], drafts[members[0]]))
            continue

        # Split the group by fact fingerprint. Differing fingerprints are
        # different claims: every one of them survives.
        by_fingerprint: dict[tuple[str, ...], list[int]] = defaultdict(list)
        for index in members:
            by_fingerprint[fact_fingerprint(drafts[index].text)].append(index)

        conflicted = len(by_fingerprint) > 1

        for indices in by_fingerprint.values():
            # Identical normalised text, or identical facts: keep the
            # fullest wording and carry every source forward.
            best = max(indices, key=lambda i: len(drafts[i].text))
            survivor = drafts[best]
            survivor.provenance = _union_provenance(drafts[i] for i in indices)
            if conflicted:
                survivor.needs_review = True
            survivors.append((min(indices), survivor))

    survivors.sort(key=lambda pair: pair[0])
    return [draft for _, draft in survivors]
