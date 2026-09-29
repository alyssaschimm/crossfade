"""Apple Music API client.

Requires a developer token (a signed JWT from your Apple Developer account).
Reading library playlists and creating playlists additionally require a
Music User Token for the listener's account.
"""

from __future__ import annotations

import os
from typing import List, Optional, Sequence
from urllib.parse import parse_qs, urlparse

from ..links import PlaylistLink
from ..models import APPLE_MUSIC, Playlist, Track
from .base import ApiError, JsonClient

API_URL = "https://api.music.apple.com"
SEARCH_LIMIT = 25
PAGE_LIMIT = 100
ADD_BATCH_SIZE = 100


class AppleMusicService:
    name = APPLE_MUSIC

    def __init__(
        self,
        developer_token: str,
        user_token: Optional[str] = None,
        storefront: str = "us",
        client: Optional[JsonClient] = None,
    ):
        self.storefront = storefront.lower()
        self.has_user_token = bool(user_token)
        headers = {"Authorization": "Bearer " + developer_token}
        if user_token:
            headers["Music-User-Token"] = user_token
        self.client = client or JsonClient(API_URL, headers)

    @classmethod
    def from_env(cls, env=None) -> "AppleMusicService":
        env = os.environ if env is None else env
        developer_token = env.get("APPLE_MUSIC_DEVELOPER_TOKEN")
        if not developer_token:
            raise ApiError("APPLE_MUSIC_DEVELOPER_TOKEN is not set.")
        return cls(
            developer_token,
            user_token=env.get("APPLE_MUSIC_USER_TOKEN") or None,
            storefront=env.get("APPLE_MUSIC_STOREFRONT") or "us",
        )

    def _require_user_token(self, action: str) -> None:
        if not self.has_user_token:
            raise ApiError(f"APPLE_MUSIC_USER_TOKEN is required to {action}.")

    # -- reading ---------------------------------------------------------

    @staticmethod
    def to_track(resource: dict) -> Optional[Track]:
        """Convert a ``songs`` or ``library-songs`` resource into a Track."""
        if not resource or resource.get("type") not in ("songs", "library-songs"):
            return None
        attrs = resource.get("attributes") or {}
        if not attrs.get("name"):
            return None
        catalog_attrs: dict = {}
        catalog_id = None
        if resource["type"] == "songs":
            catalog_id = resource.get("id")
        else:
            catalog = ((resource.get("relationships") or {}).get("catalog") or {}).get("data") or []
            if catalog:
                catalog_id = catalog[0].get("id")
                catalog_attrs = catalog[0].get("attributes") or {}
            catalog_id = catalog_id or (attrs.get("playParams") or {}).get("catalogId")
        isrc = attrs.get("isrc") or catalog_attrs.get("isrc")
        artist = attrs.get("artistName") or catalog_attrs.get("artistName")
        rating = attrs.get("contentRating") or catalog_attrs.get("contentRating")
        return Track(
            title=attrs["name"],
            artists=(artist,) if artist else (),
            album=attrs.get("albumName") or catalog_attrs.get("albumName"),
            duration_ms=attrs.get("durationInMillis") or catalog_attrs.get("durationInMillis"),
            isrc=isrc.upper() if isrc else None,
            id=catalog_id,
            url=attrs.get("url") or catalog_attrs.get("url"),
            explicit=(rating == "explicit") if rating else None,
        )

    def _collect_tracks(self, path: str, params: dict) -> List[Track]:
        tracks: List[Track] = []
        data = self.client.get(path, params=params)
        while True:
            for resource in data.get("data") or []:
                track = self.to_track(resource)
                if track:
                    tracks.append(track)
            next_path = data.get("next")
            if not next_path:
                return tracks
            # ``next`` only carries the offset; re-apply any other query params it lacks.
            existing = parse_qs(urlparse(next_path).query)
            data = self.client.get(next_path, params={k: v for k, v in params.items() if k not in existing} or None)

    def get_playlist(self, link: PlaylistLink) -> Playlist:
        if link.library:
            self._require_user_token("read library playlists")
            base = f"/v1/me/library/playlists/{link.playlist_id}"
            url = f"https://music.apple.com/library/playlist/{link.playlist_id}"
            track_params = {"limit": PAGE_LIMIT, "include": "catalog"}
        else:
            storefront = link.storefront or self.storefront
            base = f"/v1/catalog/{storefront}/playlists/{link.playlist_id}"
            url = f"https://music.apple.com/{storefront}/playlist/{link.playlist_id}"
            track_params = {"limit": PAGE_LIMIT}

        info = (self.client.get(base).get("data") or [{}])[0]
        attrs = info.get("attributes") or {}
        description = attrs.get("description") or {}
        if isinstance(description, dict):
            description = description.get("standard") or description.get("short") or ""
        return Playlist(
            service=APPLE_MUSIC,
            id=link.playlist_id,
            name=attrs.get("name") or "Untitled playlist",
            description=description,
            url=attrs.get("url") or url,
            tracks=self._collect_tracks(f"{base}/tracks", track_params),
        )

    # -- searching -------------------------------------------------------

    def find_by_isrc(self, isrc: str) -> List[Track]:
        data = self.client.get(f"/v1/catalog/{self.storefront}/songs", params={"filter[isrc]": isrc})
        return [t for t in (self.to_track(r) for r in data.get("data") or []) if t and t.id]

    def search(self, title: str, artist: str) -> List[Track]:
        params = {"term": f"{title} {artist}".strip(), "types": "songs", "limit": SEARCH_LIMIT}
        data = self.client.get(f"/v1/catalog/{self.storefront}/search", params=params)
        songs = ((data.get("results") or {}).get("songs") or {}).get("data") or []
        return [t for t in (self.to_track(r) for r in songs) if t and t.id]

    # -- writing ---------------------------------------------------------

    def create_playlist(self, name: str, description: str, tracks: Sequence[Track]) -> str:
        self._require_user_token("create playlists")
        song_refs = [{"id": t.id, "type": "songs"} for t in tracks if t.id]
        created = self.client.post(
            "/v1/me/library/playlists",
            json={
                "attributes": {"name": name, "description": description},
                "relationships": {"tracks": {"data": song_refs[:ADD_BATCH_SIZE]}},
            },
        )
        playlist_id = ((created.get("data") or [{}])[0]).get("id")
        if not playlist_id:
            raise ApiError("Apple Music did not return an id for the new playlist")
        for start in range(ADD_BATCH_SIZE, len(song_refs), ADD_BATCH_SIZE):
            self.client.post(
                f"/v1/me/library/playlists/{playlist_id}/tracks",
                json={"data": song_refs[start : start + ADD_BATCH_SIZE]},
            )
        return f"https://music.apple.com/library/playlist/{playlist_id}"
