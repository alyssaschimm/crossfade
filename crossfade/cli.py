"""Command line interface: ``crossfade <playlist link>``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

from . import __version__
from .converter import convert_playlist
from .links import InvalidLinkError, parse_playlist_link
from .llm import OpenAIResolver
from .matcher import DEFAULT_ACCEPT_THRESHOLD, DEFAULT_REVIEW_THRESHOLD
from .models import APPLE_MUSIC, SERVICE_NAMES, SPOTIFY
from .report import build_report, format_report
from .services.apple_music import AppleMusicService
from .services.base import ApiError
from .services.spotify import SpotifyService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crossfade",
        description="Convert a Spotify playlist to Apple Music or an Apple Music playlist to Spotify.",
    )
    parser.add_argument("link", help="Spotify or Apple Music playlist link")
    parser.add_argument("--name", help="name for the new playlist (defaults to the source playlist's name)")
    parser.add_argument("--report", metavar="PATH", help="also write a JSON report to PATH")
    parser.add_argument(
        "--include-uncertain", action="store_true", help="add uncertain (low-confidence) matches to the new playlist"
    )
    parser.add_argument("--dry-run", action="store_true", help="match tracks and report without creating a playlist")
    parser.add_argument("--no-llm", action="store_true", help="don't use the LLM resolver even if configured")
    parser.add_argument("--accept-threshold", type=float, default=DEFAULT_ACCEPT_THRESHOLD,
                        help="fuzzy score needed to accept a match (default: %(default)s)")
    parser.add_argument("--review-threshold", type=float, default=DEFAULT_REVIEW_THRESHOLD,
                        help="fuzzy score below which a track is unmatched (default: %(default)s)")
    parser.add_argument("-q", "--quiet", action="store_true", help="only print the new playlist link")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    def log(message: str = "") -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    def progress(position, total, result) -> None:
        log(f"[{position}/{total}] {result.status.value:<9} {result.source.display()}")

    try:
        parse_playlist_link(args.link)
        services = {SPOTIFY: SpotifyService.from_env(), APPLE_MUSIC: AppleMusicService.from_env()}
        resolver = None if args.no_llm else OpenAIResolver.from_env()
        if resolver is None and not args.no_llm:
            log("Note: OPENAI_API_KEY is not set; low-confidence matches will be reported as uncertain.")
        conversion = convert_playlist(
            args.link,
            services,
            resolver=resolver,
            name=args.name,
            include_uncertain=args.include_uncertain,
            dry_run=args.dry_run,
            progress=progress,
            accept_threshold=args.accept_threshold,
            review_threshold=args.review_threshold,
        )
    except (InvalidLinkError, ApiError, ValueError) as exc:
        print(f"crossfade: error: {exc}", file=sys.stderr)
        return 2

    log()
    log(format_report(conversion))
    log()

    if args.report:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(build_report(conversion), fh, indent=2, ensure_ascii=False)
        log(f"JSON report written to {args.report}")

    if conversion.playlist_url:
        log(f"New {SERVICE_NAMES[conversion.target_service]} playlist:")
        print(conversion.playlist_url)
    elif args.dry_run:
        log("Dry run: no playlist was created.")
    else:
        log("No tracks matched; no playlist was created.")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
