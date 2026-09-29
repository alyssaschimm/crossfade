"""End-to-end playlist conversion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Mapping, Optional

from .links import parse_playlist_link
from .llm import Resolver
from .matcher import Matcher
from .models import APPLE_MUSIC, SERVICE_NAMES, SPOTIFY, MatchResult, MatchStatus, Playlist
from .services.base import MusicService

OTHER_SERVICE = {SPOTIFY: APPLE_MUSIC, APPLE_MUSIC: SPOTIFY}


@dataclass
class ConversionResult:
    source: Playlist
    target_service: str
    results: List[MatchResult]
    playlist_url: Optional[str]
    playlist_name: str

    def by_status(self, status: MatchStatus) -> List[MatchResult]:
        return [r for r in self.results if r.status is status]


def convert_playlist(
    link: str,
    services: Mapping[str, MusicService],
    resolver: Optional[Resolver] = None,
    name: Optional[str] = None,
    include_uncertain: bool = False,
    dry_run: bool = False,
    progress: Optional[Callable[[int, int, MatchResult], None]] = None,
    **matcher_options,
) -> ConversionResult:
    """Convert the playlist at ``link`` to the other service.

    ``services`` maps service names (``"spotify"``, ``"apple_music"``) to
    clients. Returns the match results and the URL of the created playlist
    (``None`` for dry runs or when nothing matched).
    """
    parsed = parse_playlist_link(link)
    source_service = services[parsed.service]
    target_name = OTHER_SERVICE[parsed.service]
    target = services[target_name]

    playlist = source_service.get_playlist(parsed)
    matcher = Matcher(target, resolver=resolver, **matcher_options)

    results: List[MatchResult] = []
    for position, track in enumerate(playlist.tracks, start=1):
        result = matcher.match(track)
        results.append(result)
        if progress:
            progress(position, len(playlist.tracks), result)

    wanted = {MatchStatus.MATCHED} | ({MatchStatus.UNCERTAIN} if include_uncertain else set())
    to_add = [r.match for r in results if r.status in wanted and r.match is not None]

    new_name = name or playlist.name
    url = None
    if to_add and not dry_run:
        description = f"Converted from {SERVICE_NAMES[parsed.service]} with crossfade."
        if playlist.url:
            description += f" Original: {playlist.url}"
        url = target.create_playlist(new_name, description, to_add)
    return ConversionResult(playlist, target_name, results, url, new_name)
