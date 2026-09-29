"""LLM-backed resolver for low-confidence matches.

The resolver is shown the source track and a short list of candidates from the
target service and asked to pick the one that is the same recording (or none).
Any OpenAI-compatible chat completions endpoint can be used.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional, Protocol, Sequence

import requests

from .models import Track

DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_BASE_URL = "https://api.openai.com/v1"

SYSTEM_PROMPT = (
    "You match songs between music streaming services. Given a source track and "
    "numbered candidate tracks, pick the candidate that is the same recording as the "
    "source. Different featured-artist formatting, remaster labels and punctuation are "
    "fine. Live, remix, acoustic, instrumental, cover, karaoke, sped-up or re-recorded "
    "versions are NOT the same recording unless the source is also that version. "
    "Respond with a JSON object: {\"choice\": <candidate number or null>, "
    "\"confidence\": <number between 0 and 1>, \"reason\": <short explanation>}."
)


@dataclass(frozen=True)
class Resolution:
    """The resolver's verdict.

    ``index`` is the 0-based index into the candidate list, or None when the
    resolver thinks no candidate matches. ``ok`` is False when the resolver
    could not produce a verdict (e.g. network or parsing errors).
    """

    index: Optional[int]
    confidence: float
    reason: str = ""
    ok: bool = True


class Resolver(Protocol):
    def resolve(self, source: Track, candidates: Sequence[Track]) -> Resolution: ...


def _describe(track: Track) -> dict:
    return {
        "title": track.title,
        "artists": list(track.artists),
        "album": track.album,
        "duration_seconds": round(track.duration_ms / 1000) if track.duration_ms else None,
        "isrc": track.isrc,
        "explicit": track.explicit,
    }


def build_messages(source: Track, candidates: Sequence[Track]) -> List[dict]:
    payload = {
        "source": _describe(source),
        "candidates": [dict(number=i + 1, **_describe(c)) for i, c in enumerate(candidates)],
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def parse_resolution(content: str, num_candidates: int) -> Resolution:
    """Validate the model's JSON reply; never trust it blindly."""
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return Resolution(None, 0.0, "LLM returned invalid JSON", ok=False)
    if not isinstance(data, dict):
        return Resolution(None, 0.0, "LLM returned unexpected JSON", ok=False)

    reason = str(data.get("reason") or "")[:500]
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        return Resolution(None, 0.0, "LLM returned a non-numeric confidence", ok=False)
    if confidence != confidence:  # NaN
        return Resolution(None, 0.0, "LLM returned a non-numeric confidence", ok=False)
    confidence = min(max(confidence, 0.0), 1.0)

    choice = data.get("choice")
    if choice is None:
        return Resolution(None, confidence, reason)
    if isinstance(choice, bool) or not isinstance(choice, (int, float)) or int(choice) != choice:
        return Resolution(None, 0.0, f"LLM returned an invalid choice: {choice!r}", ok=False)
    choice = int(choice)
    if not 1 <= choice <= num_candidates:
        return Resolution(None, 0.0, f"LLM chose non-existent candidate {choice}", ok=False)
    return Resolution(choice - 1, confidence, reason)


class OpenAIResolver:
    """Resolver using an OpenAI-compatible ``/chat/completions`` endpoint."""

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[requests.Session] = None,
        timeout: float = 60.0,
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.timeout = timeout

    @classmethod
    def from_env(cls, env=None) -> Optional["OpenAIResolver"]:
        """Build a resolver from ``OPENAI_API_KEY`` (+ optional overrides), or None."""
        env = os.environ if env is None else env
        api_key = env.get("OPENAI_API_KEY")
        if not api_key:
            return None
        return cls(
            api_key,
            model=env.get("CROSSFADE_LLM_MODEL") or DEFAULT_MODEL,
            base_url=env.get("OPENAI_BASE_URL") or DEFAULT_BASE_URL,
        )

    def resolve(self, source: Track, candidates: Sequence[Track]) -> Resolution:
        if not candidates:
            return Resolution(None, 1.0, "No candidates")
        try:
            response = self.session.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": "Bearer " + self.api_key},
                json={
                    "model": self.model,
                    "messages": build_messages(source, candidates),
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError) as exc:
            return Resolution(None, 0.0, f"LLM request failed: {type(exc).__name__}", ok=False)
        return parse_resolution(content, len(candidates))
