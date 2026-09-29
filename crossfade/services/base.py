"""Common service interface and a small JSON HTTP client with retries."""

from __future__ import annotations

import time
from typing import Callable, List, Optional, Protocol, Sequence

import requests

from ..links import PlaylistLink
from ..models import Playlist, Track


class ApiError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class MusicService(Protocol):
    name: str

    def get_playlist(self, link: PlaylistLink) -> Playlist:
        """Fetch a playlist and all of its tracks."""

    def find_by_isrc(self, isrc: str) -> List[Track]:
        """Return catalog tracks with the given ISRC."""

    def search(self, title: str, artist: str) -> List[Track]:
        """Search the catalog for a song by title and artist."""

    def create_playlist(self, name: str, description: str, tracks: Sequence[Track]) -> str:
        """Create a playlist for the authenticated user and return its URL."""


class JsonClient:
    """Minimal JSON API client that retries rate limits and server errors."""

    def __init__(
        self,
        base_url: str,
        headers: dict,
        session: Optional[requests.Session] = None,
        timeout: float = 30.0,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.base_url = base_url.rstrip("/")
        self.headers = headers
        self.session = session or requests.Session()
        self.timeout = timeout
        self.max_retries = max_retries
        self.sleep = sleep

    def url_for(self, path_or_url: str) -> str:
        if path_or_url.startswith(self.base_url + "/"):
            return path_or_url
        if "://" in path_or_url:
            # Only follow pagination links that point back at the same API so a
            # response can never redirect credentials to another host.
            raise ApiError(f"Refusing to call URL outside {self.base_url}: {path_or_url}")
        return f"{self.base_url}/{path_or_url.lstrip('/')}"

    def request(self, method: str, path_or_url: str, params=None, json=None) -> dict:
        url = self.url_for(path_or_url)
        # Non-idempotent requests (creating a playlist, appending tracks) are only
        # retried when the server certainly did not act on them, to avoid
        # duplicate playlists or tracks.
        idempotent = method.upper() in ("GET", "HEAD", "PUT", "DELETE")
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.request(
                    method, url, headers=self.headers, params=params, json=json, timeout=self.timeout
                )
            except requests.RequestException as exc:
                retryable = idempotent or isinstance(exc, requests.ConnectTimeout)
                if not retryable or attempt >= self.max_retries:
                    raise ApiError(f"{method} {url} failed: {exc}") from exc
                self.sleep(2**attempt)
                continue

            status = response.status_code
            retryable = status == 429 or (idempotent and status >= 500)
            if retryable and attempt < self.max_retries:
                self.sleep(self._retry_delay(response, attempt))
                continue
            if status >= 400:
                raise ApiError(f"{method} {url} returned HTTP {status}: {response.text[:300]}", status)
            if status == 204 or not response.content:
                return {}
            try:
                return response.json()
            except ValueError as exc:
                raise ApiError(f"{method} {url} returned invalid JSON", status) from exc
        raise ApiError(f"{method} {url} failed after retries")  # pragma: no cover

    @staticmethod
    def _retry_delay(response, attempt: int) -> float:
        try:
            delay = float(response.headers.get("Retry-After", ""))
        except ValueError:
            delay = 2.0**attempt
        return min(max(delay, 0.0), 60.0)

    def get(self, path_or_url: str, params=None) -> dict:
        return self.request("GET", path_or_url, params=params)

    def post(self, path_or_url: str, json=None) -> dict:
        return self.request("POST", path_or_url, json=json)
