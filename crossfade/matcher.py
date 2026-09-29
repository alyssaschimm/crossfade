"""Resolve source tracks on a target service.

Pipeline for each track:

1. **Exact** – look the track up by ISRC; failing that, search the target and
   accept a candidate whose normalised title, artist and version tags are
   identical (and duration within 5s).
2. **Fuzzy** – score the search candidates on normalised title, artist and
   duration similarity. Scores at or above ``accept_threshold`` are matched.
3. **LLM** – scores between ``review_threshold`` and ``accept_threshold`` are
   low-confidence and are handed to the resolver (if configured) to pick the
   right candidate or reject them all.

Anything still ambiguous is reported as *uncertain*; tracks with no plausible
candidates are *unmatched*.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .llm import Resolver
from .models import MatchResult, MatchStatus, Track
from .normalize import Score, score_tracks, search_title
from .services.base import ApiError, MusicService

DEFAULT_ACCEPT_THRESHOLD = 0.85
DEFAULT_REVIEW_THRESHOLD = 0.6
DEFAULT_LLM_ACCEPT_THRESHOLD = 0.7
MAX_LLM_CANDIDATES = 5
MAX_REPORTED_CANDIDATES = 3


class Matcher:
    def __init__(
        self,
        target: MusicService,
        resolver: Optional[Resolver] = None,
        accept_threshold: float = DEFAULT_ACCEPT_THRESHOLD,
        review_threshold: float = DEFAULT_REVIEW_THRESHOLD,
        llm_accept_threshold: float = DEFAULT_LLM_ACCEPT_THRESHOLD,
    ):
        if not 0 <= review_threshold <= accept_threshold <= 1:
            raise ValueError("Thresholds must satisfy 0 <= review <= accept <= 1")
        self.target = target
        self.resolver = resolver
        self.accept_threshold = accept_threshold
        self.review_threshold = review_threshold
        self.llm_accept_threshold = llm_accept_threshold
        self._cache: Dict[tuple, MatchResult] = {}

    def match(self, source: Track) -> MatchResult:
        key = (source.isrc, source.title, source.artists, source.album, source.duration_ms)
        if key not in self._cache:
            try:
                self._cache[key] = self._match(source)
            except ApiError as exc:
                return MatchResult(source, MatchStatus.UNMATCHED, reason=f"Lookup failed: {exc}")
        cached = self._cache[key]
        return MatchResult(
            source, cached.status, cached.match, cached.confidence, cached.method, cached.reason, cached.candidates
        )

    def _match(self, source: Track) -> MatchResult:
        # 1a. Exact: ISRC lookup.
        if source.isrc:
            by_isrc = self.target.find_by_isrc(source.isrc)
            if by_isrc:
                ranked = self._rank(source, by_isrc)
                best, _ = ranked[0]
                return MatchResult(
                    source, MatchStatus.MATCHED, best, 1.0, "isrc", f"Same ISRC ({source.isrc})", _summary(ranked)
                )

        candidates = self._search(source)
        if not candidates:
            return MatchResult(source, MatchStatus.UNMATCHED, reason="No search results on target service")

        ranked = self._rank(source, candidates)
        summary = _summary(ranked)

        # 1b. Exact: identical normalised metadata.
        for track, score in ranked:
            if score.exact:
                return MatchResult(
                    source, MatchStatus.MATCHED, track, 1.0, "exact", "Identical normalised title and artist", summary
                )

        # 2. Fuzzy.
        best, best_score = ranked[0]
        if best_score.value >= self.accept_threshold:
            return MatchResult(
                source, MatchStatus.MATCHED, best, best_score.value, "fuzzy", _explain(best_score), summary
            )
        if best_score.value < self.review_threshold:
            return MatchResult(
                source, MatchStatus.UNMATCHED, None, best_score.value, "none",
                f"Best candidate scored {best_score.value:.2f}, below {self.review_threshold:.2f}", summary,
            )

        # 3. Low confidence: ask the LLM resolver.
        if self.resolver is None:
            return MatchResult(
                source, MatchStatus.UNCERTAIN, best, best_score.value, "fuzzy",
                f"Low-confidence fuzzy match ({_explain(best_score)}); no LLM resolver configured", summary,
            )
        shortlist = [t for t, s in ranked[:MAX_LLM_CANDIDATES] if s.value >= self.review_threshold]
        verdict = self.resolver.resolve(source, shortlist)
        if not verdict.ok:
            return MatchResult(
                source, MatchStatus.UNCERTAIN, best, best_score.value, "fuzzy",
                f"Low-confidence fuzzy match; {verdict.reason}", summary,
            )
        reason = f"LLM: {verdict.reason}" if verdict.reason else "LLM verdict"
        if verdict.index is None:
            status = MatchStatus.UNMATCHED if verdict.confidence >= self.llm_accept_threshold else MatchStatus.UNCERTAIN
            match = None if status is MatchStatus.UNMATCHED else best
            confidence = 0.0 if match is None else best_score.value
            return MatchResult(source, status, match, confidence, "llm", reason, summary)
        chosen = shortlist[verdict.index]
        status = MatchStatus.MATCHED if verdict.confidence >= self.llm_accept_threshold else MatchStatus.UNCERTAIN
        return MatchResult(source, status, chosen, verdict.confidence, "llm", reason, summary)

    def _search(self, source: Track) -> List[Track]:
        artist = source.primary_artist
        queries = [search_title(source.title)]
        if source.title not in queries:
            queries.append(source.title)
        seen, results = set(), []
        for title in queries:
            for track in self.target.search(title, artist):
                key = track.id or (track.title, track.artists)
                if key not in seen:
                    seen.add(key)
                    results.append(track)
            if results:
                break
        return results

    @staticmethod
    def _rank(source: Track, candidates: Sequence[Track]) -> List[Tuple[Track, Score]]:
        scored = [(c, score_tracks(source, c)) for c in candidates]
        # Stable sort keeps the service's relevance order for ties.
        scored.sort(key=lambda pair: (pair[1].exact, pair[1].value), reverse=True)
        return scored


def _summary(ranked: Sequence[Tuple[Track, Score]]) -> List[Tuple[Track, float]]:
    return [(t, s.value) for t, s in ranked[:MAX_REPORTED_CANDIDATES]]


def _explain(score: Score) -> str:
    parts = [f"title {score.title:.2f}", f"artist {score.artist:.2f}"]
    if score.duration is not None:
        parts.append(f"duration {score.duration:.2f}")
    return "similarity " + ", ".join(parts)
