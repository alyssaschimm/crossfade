"""Title/artist normalisation and similarity scoring used for fuzzy matching.

Services decorate titles differently, e.g. Spotify's ``"Song - 2011 Remaster"``
vs Apple Music's ``"Song (Remastered)"``, or ``"Song (feat. X)"`` vs a separate
artist credit. Normalisation strips that noise while keeping the parts that
denote a genuinely different recording (live, remix, acoustic, ...) as *tags*
so that e.g. a live version is never treated as a match for the studio one.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import FrozenSet, Iterable, Optional, Set

from .models import Track

# Qualifiers that change which recording a title refers to.
_TAG_PATTERNS = {
    "live": r"\blive\b",
    "remix": r"\b(?:re)?mix(?:ed)?\b|\bdub\b",
    "acoustic": r"\bacoustic\b|\bunplugged\b",
    "instrumental": r"\binstrumental\b",
    "demo": r"\bdemo\b",
    "karaoke": r"\bkaraoke\b",
    "reprise": r"\breprise\b",
    "cover": r"\bcover\b",
    "sped up": r"\bsped[ -]?up\b",
    "slowed": r"\bslowed\b",
    "a cappella": r"\ba ?cappella\b",
}
_TAG_RES = {tag: re.compile(pattern) for tag, pattern in _TAG_PATTERNS.items()}

# Qualifiers that are just packaging/metadata noise.
_NOISE_RE = re.compile(
    r"\b(?:remaster(?:ed)?|deluxe|bonus(?: track)?|mono|stereo|(?:single|album|lp|original|explicit|clean"
    r"|radio|main|extended)? ?(?:version|edit|mix)|explicit|clean|anniversary|edition|expanded"
    r"|from\b.*|soundtrack|motion picture|\d{4})\b"
)
_FEAT_RE = re.compile(r"^(?:feat\.?|ft\.?|featuring|with)\s")
_FEAT_TAIL_RE = re.compile(r"\s(?:feat\.?|ft\.?|featuring)\s.*$")
_BRACKET_RE = re.compile(r"[(\[{]([^)\]}]*)[)\]}]")
_DASH_SUFFIX_RE = re.compile(r"\s[-\u2013\u2014]\s(.+)$")
_NON_WORD_RE = re.compile(r"[^\w\s]")
_SPACE_RE = re.compile(r"\s+")


def _fold(text: str) -> str:
    """Lowercase, strip accents and unify punctuation variants."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = text.replace("\u2019", "'").replace("\u2018", "'").replace("`", "'")
    text = text.replace("&", " and ").replace("+", " and ")
    return text


def _clean(text: str) -> str:
    text = text.replace("'", "")
    text = _NON_WORD_RE.sub(" ", text)
    return _SPACE_RE.sub(" ", text).strip()


def _tags_in(text: str) -> FrozenSet[str]:
    return frozenset(tag for tag, regex in _TAG_RES.items() if regex.search(text))


_PLAIN_MIX_RE = re.compile(r"\b(?:original|radio|album|main|single|extended|clean|explicit) mix\b")


def _classify(qualifier: str):
    """Classify a folded title qualifier as ``("drop", set())``, ``("tag", tags)`` or ``("keep", set())``."""
    q = qualifier.strip()
    if not q or _FEAT_RE.match(q):
        return "drop", frozenset()
    found = _tags_in(_PLAIN_MIX_RE.sub(" ", q))
    if found:
        return "tag", found
    if _NOISE_RE.search(q) and not _clean(_NOISE_RE.sub(" ", q)):
        return "drop", frozenset()
    return "keep", frozenset()


@dataclass(frozen=True)
class NormalizedTitle:
    core: str
    tags: FrozenSet[str]


def normalize_title(title: str) -> NormalizedTitle:
    """Split a title into its normalised core text and version tags."""
    text = _fold(title)
    tags = set()

    def replace_bracket(m: "re.Match[str]") -> str:
        kind, found = _classify(m.group(1))
        tags.update(found)
        return f" {m.group(1)} " if kind == "keep" else " "

    text = _BRACKET_RE.sub(replace_bracket, text)
    m = _DASH_SUFFIX_RE.search(text)
    if m:
        kind, found = _classify(m.group(1))
        tags.update(found)
        if kind != "keep":
            text = text[: m.start()]
    text = _FEAT_TAIL_RE.sub("", text)
    core = _clean(text)
    return NormalizedTitle(core or _clean(_fold(title)), frozenset(tags))


def search_title(title: str) -> str:
    """Title with featuring credits and packaging noise removed, for search queries.

    Version qualifiers such as "Live" or "Remix" are kept so the search can find
    the right recording.
    """
    text = _BRACKET_RE.sub(lambda m: " " if _classify(_fold(m.group(1)))[0] == "drop" else m.group(0), title)
    m = _DASH_SUFFIX_RE.search(text)
    if m and _classify(_fold(m.group(1)))[0] == "drop":
        text = text[: m.start()]
    text = re.sub(r"\s(?:feat\.?|ft\.?|featuring)\s.*$", "", text, flags=re.I)
    return _SPACE_RE.sub(" ", text).strip() or title


def normalize_artist(name: str) -> str:
    text = _clean(_fold(name))
    if text.startswith("the "):
        text = text[4:]
    return text


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


_CREDIT_SEP_RE = re.compile(r"(\s*(?:,|/|;|\band\b|\bx\b|\bfeat\b\.?|\bft\b\.?|\bfeaturing\b|\bwith\b)\s*)")


def _credit_entities(credit: str) -> Set[str]:
    """Every normalised name a credit string could refer to.

    ``"Earth, Wind & Fire & The Emotions"`` yields ``earth wind and fire``,
    ``emotions``, the whole string and other contiguous spans, so that it can be
    compared against separately listed artists without letting ``"Queen"``
    match ``"Queen Latifah"``.
    """
    tokens = _CREDIT_SEP_RE.split(_fold(credit))
    parts = len(tokens) // 2 + 1
    entities = set()
    for i in range(parts):
        for j in range(i, parts):
            name = normalize_artist("".join(tokens[2 * i : 2 * j + 1]))
            if name:
                entities.add(name)
    return entities


def artist_similarity(a: Iterable[str], b: Iterable[str]) -> float:
    """Similarity of two artist credits.

    Handles one service listing artists separately and the other combining
    them into a single string (``"A & B"``).
    """
    a, b = [x for x in a if x], [x for x in b if x]
    a_norm, b_norm = [normalize_artist(x) for x in a], [normalize_artist(x) for x in b]
    if not any(a_norm) or not any(b_norm):
        return 0.0
    a_entities = set().union(*(_credit_entities(x) for x in a))
    b_entities = set().union(*(_credit_entities(x) for x in b))
    if a_norm[0] in b_entities or b_norm[0] in a_entities:
        return 1.0
    best_primary = max(similarity(a_norm[0], y) for y in b_norm)
    return max(best_primary, similarity(" ".join(a_norm), " ".join(b_norm)))


def duration_similarity(a: Optional[int], b: Optional[int]) -> Optional[float]:
    """1.0 within 2s, falling linearly to 0.0 at 30s apart; None if unknown."""
    if not a or not b:
        return None
    diff = abs(a - b) / 1000.0
    if diff <= 2:
        return 1.0
    return max(0.0, 1.0 - (diff - 2) / 28.0)


@dataclass(frozen=True)
class Score:
    value: float
    exact: bool
    title: float
    artist: float
    duration: Optional[float]


def score_tracks(source: Track, candidate: Track) -> Score:
    """Score how likely ``candidate`` is the same recording as ``source``."""
    src_title, cand_title = normalize_title(source.title), normalize_title(candidate.title)
    title = similarity(src_title.core, cand_title.core)
    artist = artist_similarity(source.artists, candidate.artists)
    duration = duration_similarity(source.duration_ms, candidate.duration_ms)
    same_tags = src_title.tags == cand_title.tags

    if duration is None:
        value = 0.6 * title + 0.4 * artist
    else:
        value = 0.55 * title + 0.35 * artist + 0.10 * duration
    if not same_tags:
        value *= 0.75

    exact = (
        title == 1.0
        and artist == 1.0
        and same_tags
        and (duration is None or abs(source.duration_ms - candidate.duration_ms) <= 5000)
    )
    return Score(round(value, 4), exact, title, artist, duration)
