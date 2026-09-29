"""Service-agnostic data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple

SPOTIFY = "spotify"
APPLE_MUSIC = "apple_music"

SERVICE_NAMES = {SPOTIFY: "Spotify", APPLE_MUSIC: "Apple Music"}


@dataclass(frozen=True)
class Track:
    """A track as described by a streaming service.

    ``id`` is the identifier the owning service needs to add the track to a
    playlist (a ``spotify:track:...`` URI for Spotify, a catalog song id for
    Apple Music).
    """

    title: str
    artists: Tuple[str, ...]
    album: Optional[str] = None
    duration_ms: Optional[int] = None
    isrc: Optional[str] = None
    id: Optional[str] = None
    url: Optional[str] = None
    explicit: Optional[bool] = None

    @property
    def primary_artist(self) -> str:
        return self.artists[0] if self.artists else ""

    def display(self) -> str:
        artists = ", ".join(self.artists) or "Unknown artist"
        return f"{artists} - {self.title}"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "artists": list(self.artists),
            "album": self.album,
            "duration_ms": self.duration_ms,
            "isrc": self.isrc,
            "id": self.id,
            "url": self.url,
            "explicit": self.explicit,
        }


@dataclass
class Playlist:
    service: str
    id: str
    name: str
    tracks: List[Track]
    description: str = ""
    url: Optional[str] = None


class MatchStatus(str, Enum):
    MATCHED = "matched"
    UNCERTAIN = "uncertain"
    UNMATCHED = "unmatched"


@dataclass
class MatchResult:
    """Outcome of resolving one source track on the target service.

    ``method`` is one of ``isrc``, ``exact``, ``fuzzy``, ``llm`` or ``none``.
    """

    source: Track
    status: MatchStatus
    match: Optional[Track] = None
    confidence: float = 0.0
    method: str = "none"
    reason: str = ""
    candidates: List[Tuple[Track, float]] = field(default_factory=list)
