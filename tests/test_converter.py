import json

import pytest

from crossfade import cli
from crossfade.converter import convert_playlist
from crossfade.links import InvalidLinkError
from crossfade.llm import Resolution
from crossfade.models import APPLE_MUSIC, SPOTIFY, MatchStatus
from crossfade.report import build_report, format_report
from fakes import FakeResolver, FakeService, make_playlist, track

SPOTIFY_ID = "37i9dQZF1DXcBWIGoYBM5M"
SPOTIFY_LINK = f"https://open.spotify.com/playlist/{SPOTIFY_ID}"

SOURCE_TRACKS = [
    track("Here Comes the Sun - Remastered 2009", "The Beatles", isrc="GBAYE0601690", duration_ms=185733),
    track("SICKO MODE", "Travis Scott", "Drake", duration_ms=312820),
    track("Creep", "Radiohead", duration_ms=238640),
    track("Obscure B-Side", "Nobody Special"),
]
APPLE_CATALOG = [
    track("Here Comes the Sun", "The Beatles", isrc="GBAYE0601690", id="am1", duration_ms=185733),
    track("SICKO MODE (feat. Drake)", "Travis Scott", id="am2", duration_ms=312820),
    track("Creep (Acoustic)", "Radiohead", id="am3", duration_ms=238000),
]


def services():
    spotify = FakeService(SPOTIFY, playlists={SPOTIFY_ID: make_playlist(SPOTIFY, SPOTIFY_ID, SOURCE_TRACKS)})
    apple = FakeService(APPLE_MUSIC, APPLE_CATALOG)
    return {SPOTIFY: spotify, APPLE_MUSIC: apple}


def test_spotify_to_apple_music():
    svcs = services()
    progress = []
    result = convert_playlist(SPOTIFY_LINK, svcs, progress=lambda i, n, r: progress.append((i, n)))
    assert [r.status for r in result.results] == [
        MatchStatus.MATCHED, MatchStatus.MATCHED, MatchStatus.UNCERTAIN, MatchStatus.UNMATCHED]
    assert [r.method for r in result.results[:2]] == ["isrc", "exact"]
    assert result.playlist_url == "https://example.test/apple_music/playlist/1"
    name, description, added = svcs[APPLE_MUSIC].created[0]
    assert name == "Road Trip"
    assert "Spotify" in description
    assert [t.id for t in added] == ["am1", "am2"]
    assert progress[-1] == (4, 4)


def test_include_uncertain_and_custom_name():
    svcs = services()
    result = convert_playlist(SPOTIFY_LINK, svcs, include_uncertain=True, name="Copy")
    name, _, added = svcs[APPLE_MUSIC].created[0]
    assert name == "Copy" == result.playlist_name
    assert [t.id for t in added] == ["am1", "am2", "am3"]


def test_llm_resolves_low_confidence_track():
    svcs = services()
    resolver = FakeResolver(Resolution(None, 0.9, "acoustic version is a different recording"))
    result = convert_playlist(SPOTIFY_LINK, svcs, resolver=resolver)
    assert result.results[2].status is MatchStatus.UNMATCHED
    assert result.results[2].method == "llm"
    assert len(resolver.calls) == 1


def test_apple_music_to_spotify():
    apple_pl = make_playlist(APPLE_MUSIC, "pl.abc", [track("Creep", "Radiohead", duration_ms=238640)])
    spotify = FakeService(SPOTIFY, [track("Creep", "Radiohead", id="spotify:track:1", duration_ms=238640)])
    svcs = {SPOTIFY: spotify, APPLE_MUSIC: FakeService(APPLE_MUSIC, playlists={"pl.abc": apple_pl})}
    result = convert_playlist("https://music.apple.com/us/playlist/x/pl.abc", svcs)
    assert result.target_service == SPOTIFY
    assert spotify.created[0][2][0].id == "spotify:track:1"


def test_dry_run_creates_nothing():
    svcs = services()
    result = convert_playlist(SPOTIFY_LINK, svcs, dry_run=True)
    assert result.playlist_url is None
    assert svcs[APPLE_MUSIC].created == []


def test_invalid_link():
    with pytest.raises(InvalidLinkError):
        convert_playlist("https://example.com", services())


def test_reports():
    result = convert_playlist(SPOTIFY_LINK, services())
    report = build_report(result)
    assert report["summary"] == {"total": 4, "matched": 2, "uncertain": 1, "unmatched": 1}
    assert report["target"]["url"] == result.playlist_url
    assert report["tracks"][2]["match"]["id"] == "am3"
    assert report["tracks"][2]["candidates"]
    json.dumps(report)

    text = format_report(result)
    assert "Matched (2):" in text
    assert "Uncertain (review these) (1):" in text
    assert "Unmatched (1):" in text
    assert "  4. Nobody Special - Obscure B-Side" in text


def test_cli_prints_new_link(monkeypatch, tmp_path, capsys):
    svcs = services()
    monkeypatch.setattr(cli.SpotifyService, "from_env", classmethod(lambda cls: svcs[SPOTIFY]))
    monkeypatch.setattr(cli.AppleMusicService, "from_env", classmethod(lambda cls: svcs[APPLE_MUSIC]))
    monkeypatch.setattr(cli.OpenAIResolver, "from_env", classmethod(lambda cls: None))
    report_path = tmp_path / "report.json"

    assert cli.main([SPOTIFY_LINK, "--report", str(report_path)]) == 0
    out, err = capsys.readouterr()
    assert out.strip() == "https://example.test/apple_music/playlist/1"
    assert "Unmatched (1):" in err
    assert json.loads(report_path.read_text())["summary"]["matched"] == 2


def test_cli_reports_errors(capsys):
    assert cli.main(["https://example.com/nope", "--no-llm"]) == 2
    assert "error" in capsys.readouterr().err
