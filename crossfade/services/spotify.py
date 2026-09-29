"""Spotify Web API client.

Uses the playlist endpoints introduced in Spotify's February 2026 Web API
update (``/playlists/{id}/items`` and ``POST /me/playlists``) and accepts the
older ``tracks``/``track`` response fields as a fallback.
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence

from ..links import PlaylistLink
from ..models import SPOTIFY, Playlist, Track
from .base import ApiError, JsonClient

API_URL = "https://api.spotify.com/v1"
SEARCH_LIMIT = 10  # Maximum allowed for Development Mode apps.
ADD_BATCH_SIZE = 100


def _strip_quotes(text: str) -> str:
    return text.replace('"', " ").strip()


class SpotifyService:
    name = SPOTIFY

    def __init__(self, access_token: str, market: Optional[str] = None, client: Optional[JsonClient] = None):
        self.market = market
        self.client = client or JsonClient(API_URL, {"Authorization": "Bearer " + access_token})

    @classmethod
    def from_env(cls, env=None) -> "SpotifyService":
        env = os.environ if env is None else env
        token = env.get("SPOTIFY_ACCESS_TOKEN")
        if not token:
            raise ApiError(
                "SPOTIFY_ACCESS_TOKEN is not set. Create a user access token with the "
                "playlist-read-private, playlist-modify-private and playlist-modify-public scopes."
            )
        return cls(token, market=env.get("SPOTIFY_MARKET") or None)

    # -- reading ---------------------------------------------------------

    @staticmethod
    def to_track(data: dict) -> Optional[Track]:
        if not data or data.get("type", "track") != "track" or not data.get("name"):
            return None
        external_ids = data.get("external_ids") or {}
        return Track(
            title=data["name"],
            artists=tuple(a["name"] for a in data.get("artists") or [] if a.get("name")),
            album=(data.get("album") or {}).get("name"),
            duration_ms=data.get("duration_ms"),
            isrc=(external_ids.get("isrc") or "").upper() or None,
            id=data.get("uri") if data.get("id") else None,
            url=(data.get("external_urls") or {}).get("spotify"),
            explicit=data.get("explicit"),
        )

    def _market_params(self) -> dict:
        return {"market": self.market} if self.market else {}

    def get_playlist(self, link: PlaylistLink) -> Playlist:
        data = self.client.get(f"/playlists/{link.playlist_id}", params=self._market_params())
        page = data.get("items") or data.get("tracks") or {}
        tracks: List[Track] = []
        while True:
            for entry in page.get("items") or []:
                track = self.to_track((entry or {}).get("item") or (entry or {}).get("track"))
                if track:
                    tracks.append(track)
            next_url = page.get("next")
            if not next_url:
                break
            page = self.client.get(next_url)
        return Playlist(
            service=SPOTIFY,
            id=link.playlist_id,
            name=data.get("name") or "Untitled playlist",
            description=data.get("description") or "",
            url=(data.get("external_urls") or {}).get("spotify")
            or f"https://open.spotify.com/playlist/{link.playlist_id}",
            tracks=tracks,
        )

    # -- searching -------------------------------------------------------

    def _search(self, query: str) -> List[Track]:
        params = {"q": query, "type": "track", "limit": SEARCH_LIMIT, **self._market_params()}
        data = self.client.get("/search", params=params)
        items = ((data.get("tracks") or {}).get("items")) or []
        return [t for t in (self.to_track(item) for item in items) if t and t.id]

    def find_by_isrc(self, isrc: str) -> List[Track]:
        return self._search(f"isrc:{_strip_quotes(isrc)}")

    def search(self, title: str, artist: str) -> List[Track]:
        title, artist = _strip_quotes(title), _strip_quotes(artist)
        results: List[Track] = []
        if artist:
            results = self._search(f'track:"{title}" artist:"{artist}"')
        if not results:
            results = self._search(f"{title} {artist}".strip())
        return results

    # -- writing ---------------------------------------------------------

    def create_playlist(self, name: str, description: str, tracks: Sequence[Track]) -> str:
        created = self.client.post(
            "/me/playlists", json={"name": name, "description": description[:300], "public": False}
        )
        playlist_id = created.get("id")
        if not playlist_id:
            raise ApiError("Spotify did not return an id for the new playlist")
        uris = [t.id for t in tracks if t.id]
        for start in range(0, len(uris), ADD_BATCH_SIZE):
            self.client.post(f"/playlists/{playlist_id}/items", json={"uris": uris[start : start + ADD_BATCH_SIZE]})
        return (created.get("external_urls") or {}).get("spotify") or f"https://open.spotify.com/playlist/{playlist_id}"
