import pytest

from crossfade.links import InvalidLinkError, parse_playlist_link
from crossfade.models import APPLE_MUSIC, SPOTIFY

SPOTIFY_ID = "37i9dQZF1DXcBWIGoYBM5M"


@pytest.mark.parametrize(
    "link",
    [
        f"https://open.spotify.com/playlist/{SPOTIFY_ID}",
        f"https://open.spotify.com/playlist/{SPOTIFY_ID}?si=abc123",
        f"https://open.spotify.com/intl-de/playlist/{SPOTIFY_ID}",
        f"https://open.spotify.com/user/someone/playlist/{SPOTIFY_ID}",
        f"open.spotify.com/playlist/{SPOTIFY_ID}",
        f"spotify:playlist:{SPOTIFY_ID}",
        f"  spotify:user:someone:playlist:{SPOTIFY_ID}  ",
    ],
)
def test_spotify_links(link):
    parsed = parse_playlist_link(link)
    assert parsed.service == SPOTIFY
    assert parsed.playlist_id == SPOTIFY_ID


def test_apple_catalog_link():
    parsed = parse_playlist_link("https://music.apple.com/gb/playlist/todays-hits/pl.f4d106fed2bd41149aaacabb233eb5eb?l=en")
    assert parsed.service == APPLE_MUSIC
    assert parsed.playlist_id == "pl.f4d106fed2bd41149aaacabb233eb5eb"
    assert parsed.storefront == "gb"
    assert not parsed.library


def test_apple_catalog_link_without_slug():
    parsed = parse_playlist_link("https://music.apple.com/us/playlist/pl.u-abc123")
    assert parsed.playlist_id == "pl.u-abc123"


def test_apple_library_link():
    parsed = parse_playlist_link("https://music.apple.com/library/playlist/p.AbCd1234")
    assert parsed.service == APPLE_MUSIC
    assert parsed.playlist_id == "p.AbCd1234"
    assert parsed.library


@pytest.mark.parametrize(
    "link",
    [
        "",
        "https://example.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "https://open.spotify.com/album/37i9dQZF1DXcBWIGoYBM5M",
        "https://open.spotify.com.evil.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
        "https://music.apple.com/us/album/foo/123",
        "https://spotify.link/abcdef",
    ],
)
def test_invalid_links(link):
    with pytest.raises(InvalidLinkError):
        parse_playlist_link(link)
