from typing import List, Optional, Sequence

from crossfade.models import Playlist, Track
from crossfade.normalize import normalize_artist, normalize_title


class FakeService:
    """In-memory MusicService used by tests."""

    def __init__(self, name: str, catalog: Sequence[Track] = (), playlists: Optional[dict] = None):
        self.name = name
        self.catalog = list(catalog)
        self.playlists = playlists or {}
        self.created: List[tuple] = []
        self.searches: List[tuple] = []

    def get_playlist(self, link):
        return self.playlists[link.playlist_id]

    def find_by_isrc(self, isrc):
        return [t for t in self.catalog if t.isrc == isrc]

    def search(self, title, artist):
        self.searches.append((title, artist))
        words = set(normalize_title(title).core.split())
        artist_n = normalize_artist(artist)
        return [
            t for t in self.catalog
            if words & set(normalize_title(t.title).core.split())
            or artist_n in " ".join(normalize_artist(a) for a in t.artists)
        ]

    def create_playlist(self, name, description, tracks):
        self.created.append((name, description, list(tracks)))
        return f"https://example.test/{self.name}/playlist/{len(self.created)}"


class FakeResolver:
    def __init__(self, resolution):
        self.resolution = resolution
        self.calls = []

    def resolve(self, source, candidates):
        self.calls.append((source, list(candidates)))
        return self.resolution


def make_playlist(service, playlist_id, tracks, name="Road Trip"):
    return Playlist(service=service, id=playlist_id, name=name, tracks=list(tracks), url=f"https://src/{playlist_id}")


def track(title, *artists, **kwargs):
    return Track(title=title, artists=tuple(artists), **kwargs)


class FakeHttpResponse:
    def __init__(self, status=200, payload=None, headers=None):
        import json as _json

        self.status_code = status
        self.headers = headers or {}
        self._payload = payload
        self.content = b"" if payload is None else _json.dumps(payload).encode()
        self.text = self.content.decode()

    def json(self):
        return self._payload


class FakeHttpSession:
    """Routes ``(method, url)`` to queued responses and records requests."""

    def __init__(self, routes):
        self.routes = {k: list(v) if isinstance(v, list) else [v] for k, v in routes.items()}
        self.calls = []

    def request(self, method, url, headers=None, params=None, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "params": params, "json": json})
        queue = self.routes.get((method, url))
        if not queue:
            raise AssertionError(f"Unexpected request {method} {url} {params}")
        response = queue.pop(0) if len(queue) > 1 else queue[0]
        return response if isinstance(response, FakeHttpResponse) else FakeHttpResponse(payload=response)
