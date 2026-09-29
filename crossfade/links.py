"""Parse Spotify and Apple Music playlist links."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

from .models import APPLE_MUSIC, SPOTIFY


class InvalidLinkError(ValueError):
    pass


@dataclass(frozen=True)
class PlaylistLink:
    service: str
    playlist_id: str
    storefront: Optional[str] = None
    library: bool = False


_SPOTIFY_ID = r"[A-Za-z0-9]{22}"
_SPOTIFY_URI = re.compile(rf"^spotify:(?:user:[^:]+:)?playlist:({_SPOTIFY_ID})$")
_SPOTIFY_PATH = re.compile(rf"^/(?:intl-[a-z]{{2}}(?:-[a-z]{{2}})?/)?(?:user/[^/]+/)?playlist/({_SPOTIFY_ID})/?$", re.I)

_APPLE_CATALOG_ID = r"pl\.[A-Za-z0-9-]+"
_APPLE_LIBRARY_ID = r"p\.[A-Za-z0-9]+"
_APPLE_CATALOG_PATH = re.compile(rf"^/([a-z]{{2}})/playlist/(?:[^/]+/)?({_APPLE_CATALOG_ID})/?$", re.I)
_APPLE_LIBRARY_PATH = re.compile(rf"^/(?:[a-z]{{2}}/)?library/playlist/({_APPLE_LIBRARY_ID})/?$", re.I)

_SPOTIFY_HOSTS = {"open.spotify.com", "play.spotify.com"}
_APPLE_HOSTS = {"music.apple.com", "itunes.apple.com", "geo.music.apple.com"}


def parse_playlist_link(link: str) -> PlaylistLink:
    """Return which service and playlist a link points to.

    Raises :class:`InvalidLinkError` for anything that is not a recognised
    Spotify or Apple Music playlist link.
    """
    link = (link or "").strip()
    match = _SPOTIFY_URI.match(link)
    if match:
        return PlaylistLink(SPOTIFY, match.group(1))

    parsed = urlparse(link if "://" in link else f"https://{link}")
    host = (parsed.hostname or "").lower()
    path = parsed.path

    if host in _SPOTIFY_HOSTS:
        match = _SPOTIFY_PATH.match(path)
        if match:
            return PlaylistLink(SPOTIFY, match.group(1))
    elif host in _APPLE_HOSTS:
        match = _APPLE_LIBRARY_PATH.match(path)
        if match:
            return PlaylistLink(APPLE_MUSIC, match.group(1), library=True)
        match = _APPLE_CATALOG_PATH.match(path)
        if match:
            return PlaylistLink(APPLE_MUSIC, match.group(2), storefront=match.group(1).lower())
    elif host in {"spotify.link", "spotify.app.link"}:
        raise InvalidLinkError(
            "Shortened Spotify links are not supported; open the link and copy the full "
            "https://open.spotify.com/playlist/... URL instead."
        )

    raise InvalidLinkError(f"Not a Spotify or Apple Music playlist link: {link!r}")
