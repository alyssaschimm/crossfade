"""Human-readable and JSON reports for a conversion."""

from __future__ import annotations

from typing import List

from .converter import ConversionResult
from .models import SERVICE_NAMES, MatchResult, MatchStatus

_SECTIONS = [
    (MatchStatus.MATCHED, "Matched"),
    (MatchStatus.UNCERTAIN, "Uncertain (review these)"),
    (MatchStatus.UNMATCHED, "Unmatched"),
]


def build_report(conversion: ConversionResult) -> dict:
    """A JSON-serialisable report of every track's outcome."""
    counts = {status.value: len(conversion.by_status(status)) for status, _ in _SECTIONS}
    return {
        "source": {
            "service": conversion.source.service,
            "name": conversion.source.name,
            "url": conversion.source.url,
            "track_count": len(conversion.source.tracks),
        },
        "target": {
            "service": conversion.target_service,
            "name": conversion.playlist_name,
            "url": conversion.playlist_url,
        },
        "summary": {"total": len(conversion.results), **counts},
        "tracks": [
            {
                "position": position,
                "status": r.status.value,
                "method": r.method,
                "confidence": round(r.confidence, 4),
                "reason": r.reason,
                "source": r.source.to_dict(),
                "match": r.match.to_dict() if r.match else None,
                "candidates": [{"score": round(score, 4), **t.to_dict()} for t, score in r.candidates],
            }
            for position, r in enumerate(conversion.results, start=1)
        ],
    }


def _line(position: int, r: MatchResult) -> List[str]:
    lines = [f"  {position:>3}. {r.source.display()}"]
    if r.match is not None:
        lines.append(f"       -> {r.match.display()}  [{r.method}, {r.confidence:.2f}]")
    if r.reason and r.status is not MatchStatus.MATCHED:
        lines.append(f"       {r.reason}")
    return lines


def format_report(conversion: ConversionResult) -> str:
    source = conversion.source
    target = SERVICE_NAMES[conversion.target_service]
    total = len(conversion.results)
    out = [
        f'"{source.name}": {SERVICE_NAMES[source.service]} -> {target}',
        "  " + ", ".join(
            f"{len(conversion.by_status(status))}/{total} {status.value}" for status, _ in _SECTIONS
        ),
    ]
    positions = {id(r): i for i, r in enumerate(conversion.results, start=1)}
    for status, title in _SECTIONS:
        results = conversion.by_status(status)
        out.append("")
        out.append(f"{title} ({len(results)}):")
        if not results:
            out.append("  (none)")
        for r in results:
            out.extend(_line(positions[id(r)], r))
    return "\n".join(out)
