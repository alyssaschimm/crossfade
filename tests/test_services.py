import pytest

from crossfade.links import PlaylistLink
from crossfade.models import APPLE_MUSIC, SPOTIFY
from crossfade.services.apple_music import AppleMusicService
from crossfade.services.base import ApiError, JsonClient
from crossfade.services.spotify import API_URL as SPOTIFY_API, SpotifyService
from fakes import FakeHttpResponse, FakeHttpSession, track

APPLE_API = "https://api.music.apple.com"


def spotify_track(n, isrc=None):
    return {
        "type": "track", "id": f"id{n}", "uri": f"spotify:track:id{n}", "name": f"Song {n}",
        "artists": [{"name": "Artist"}, {"name": "Guest"}], "album": {"name": "Album"},
        "duration_ms": 200000 + n, "explicit": False,
        "external_ids": {"isrc": isrc} if isrc else {},
        "external_urls": {"spotify": f"https://open.spotify.com/track/id{n}"},
    }


def spotify(session, market=None):
    return SpotifyService("tok", market=market, client=JsonClient(SPOTIFY_API, {"Authorization": "x"}, session=session, sleep=lambda s: None))


def apple(session, user_token=True):
    service = AppleMusicService("dev", user_token="user" if user_token else None, storefront="us")
    service.client = JsonClient(APPLE_API, service.client.headers, session=session, sleep=lambda s: None)
    return service


# -- JsonClient -----------------------------------------------------------

def test_json_client_retries_rate_limits():
    delays = []
    session = FakeHttpSession({("GET", "https://api.test/x"): [
        FakeHttpResponse(429, {}, {"Retry-After": "3"}), FakeHttpResponse(200, {"ok": True})]})
    client = JsonClient("https://api.test", {}, session=session, sleep=delays.append)
    assert client.get("/x") == {"ok": True}
    assert delays == [3.0]


def test_json_client_raises_on_client_errors():
    session = FakeHttpSession({("GET", "https://api.test/x"): FakeHttpResponse(404, {"error": "nope"})})
    with pytest.raises(ApiError) as exc:
        JsonClient("https://api.test", {}, session=session).get("/x")
    assert exc.value.status == 404


def test_json_client_refuses_foreign_urls():
    client = JsonClient("https://api.test", {"Authorization": "secret"}, session=FakeHttpSession({}))
    with pytest.raises(ApiError):
        client.get("https://evil.test/steal")


# -- Spotify ----------------------------------------------------------------

def test_spotify_get_playlist_paginates_and_skips_non_tracks():
    pid = "37i9dQZF1DXcBWIGoYBM5M"
    page2 = f"{SPOTIFY_API}/playlists/{pid}/items?offset=2&limit=2"
    session = FakeHttpSession({
        ("GET", f"{SPOTIFY_API}/playlists/{pid}"): {
            "name": "Mix", "description": "desc", "external_urls": {"spotify": "https://open.spotify.com/playlist/x"},
            "items": {"items": [{"item": spotify_track(1, "usabc1")}, {"item": {"type": "episode", "name": "Pod"}}],
                      "next": page2},
        },
        ("GET", page2): {"items": [{"track": spotify_track(2)}, {"item": None}], "next": None},
    })
    playlist = spotify(session).get_playlist(PlaylistLink(SPOTIFY, pid))
    assert playlist.name == "Mix"
    assert [t.title for t in playlist.tracks] == ["Song 1", "Song 2"]
    first = playlist.tracks[0]
    assert first.isrc == "USABC1"
    assert first.artists == ("Artist", "Guest")
    assert first.id == "spotify:track:id1"


def test_spotify_search_falls_back_to_plain_query():
    session = FakeHttpSession({("GET", f"{SPOTIFY_API}/search"): [
        {"tracks": {"items": []}}, {"tracks": {"items": [spotify_track(1)]}}]})
    results = spotify(session, market="US").search('Say "Hi"', "Artist")
    assert [t.id for t in results] == ["spotify:track:id1"]
    first, second = (c["params"] for c in session.calls)
    assert first["q"] == 'track:"Say  Hi" artist:"Artist"'
    assert second["q"] == "Say  Hi Artist"
    assert first["market"] == "US" and first["limit"] == 10


def test_spotify_find_by_isrc():
    session = FakeHttpSession({("GET", f"{SPOTIFY_API}/search"): {"tracks": {"items": [spotify_track(1, "X")]}}})
    assert spotify(session).find_by_isrc("X")[0].isrc == "X"
    assert session.calls[0]["params"]["q"] == "isrc:X"


def test_spotify_create_playlist_batches_items():
    session = FakeHttpSession({
        ("POST", f"{SPOTIFY_API}/me/playlists"): {"id": "new", "external_urls": {"spotify": "https://open.spotify.com/playlist/new"}},
        ("POST", f"{SPOTIFY_API}/playlists/new/items"): {"snapshot_id": "s"},
    })
    tracks = [track(f"T{i}", "A", id=f"spotify:track:{i}") for i in range(150)]
    url = spotify(session).create_playlist("Name", "Desc", tracks)
    assert url == "https://open.spotify.com/playlist/new"
    adds = [c["json"]["uris"] for c in session.calls if c["url"].endswith("/items")]
    assert [len(a) for a in adds] == [100, 50]
    assert session.calls[0]["json"]["public"] is False


def test_spotify_from_env_requires_token():
    with pytest.raises(ApiError):
        SpotifyService.from_env({})


# -- Apple Music --------------------------------------------------------------

def apple_song(n, isrc="USX1"):
    return {"id": str(n), "type": "songs", "attributes": {
        "name": f"Song {n}", "artistName": "Artist & Guest", "albumName": "Album", "durationInMillis": 200000,
        "isrc": isrc, "contentRating": "explicit", "url": f"https://music.apple.com/us/song/{n}"}}


def test_apple_catalog_playlist_paginates():
    base = f"{APPLE_API}/v1/catalog/gb/playlists/pl.abc"
    session = FakeHttpSession({
        ("GET", base): {"data": [{"attributes": {"name": "Hits", "description": {"standard": "Best"}}}]},
        ("GET", f"{base}/tracks"): {"data": [apple_song(1), {"id": "mv", "type": "music-videos", "attributes": {"name": "Video"}}],
                                    "next": "/v1/catalog/gb/playlists/pl.abc/tracks?offset=100"},
        ("GET", f"{base}/tracks?offset=100"): {"data": [apple_song(2)]},
    })
    playlist = apple(session, user_token=False).get_playlist(PlaylistLink(APPLE_MUSIC, "pl.abc", storefront="gb"))
    assert playlist.name == "Hits" and playlist.description == "Best"
    assert [t.id for t in playlist.tracks] == ["1", "2"]
    assert playlist.tracks[0].explicit is True
    assert playlist.tracks[0].artists == ("Artist & Guest",)
    # The next link already has an offset; limit must be re-applied without duplicating it.
    assert session.calls[2]["params"] == {"limit": 100}


def test_apple_library_playlist_uses_catalog_relationship():
    base = f"{APPLE_API}/v1/me/library/playlists/p.lib"
    library_song = {"id": "i.1", "type": "library-songs",
                    "attributes": {"name": "Song", "artistName": "Artist", "playParams": {"catalogId": "fallback"}},
                    "relationships": {"catalog": {"data": [apple_song(99, isrc="usabc")]}}}
    session = FakeHttpSession({
        ("GET", base): {"data": [{"attributes": {"name": "Mine"}}]},
        ("GET", f"{base}/tracks"): {"data": [library_song]},
    })
    playlist = apple(session).get_playlist(PlaylistLink(APPLE_MUSIC, "p.lib", library=True))
    assert playlist.tracks[0].id == "99"
    assert playlist.tracks[0].isrc == "USABC"
    assert session.calls[1]["params"]["include"] == "catalog"


def test_apple_library_playlist_requires_user_token():
    with pytest.raises(ApiError):
        apple(FakeHttpSession({}), user_token=False).get_playlist(PlaylistLink(APPLE_MUSIC, "p.lib", library=True))


def test_apple_search_and_isrc():
    session = FakeHttpSession({
        ("GET", f"{APPLE_API}/v1/catalog/us/search"): {"results": {"songs": {"data": [apple_song(1)]}}},
        ("GET", f"{APPLE_API}/v1/catalog/us/songs"): {"data": [apple_song(2)]},
    })
    service = apple(session)
    assert service.search("Song", "Artist")[0].id == "1"
    assert session.calls[0]["params"]["term"] == "Song Artist"
    assert service.find_by_isrc("USX1")[0].id == "2"
    assert session.calls[1]["params"] == {"filter[isrc]": "USX1"}


def test_apple_create_playlist_batches_tracks():
    session = FakeHttpSession({
        ("POST", f"{APPLE_API}/v1/me/library/playlists"): {"data": [{"id": "p.new"}]},
        ("POST", f"{APPLE_API}/v1/me/library/playlists/p.new/tracks"): FakeHttpResponse(204),
    })
    tracks = [track(f"T{i}", "A", id=str(i)) for i in range(250)]
    url = apple(session).create_playlist("Name", "Desc", tracks)
    assert url == "https://music.apple.com/library/playlist/p.new"
    create = session.calls[0]["json"]
    assert len(create["relationships"]["tracks"]["data"]) == 100
    assert [len(c["json"]["data"]) for c in session.calls[1:]] == [100, 50]


def test_apple_create_requires_user_token():
    with pytest.raises(ApiError):
        apple(FakeHttpSession({}), user_token=False).create_playlist("n", "d", [])


def test_apple_headers():
    service = AppleMusicService("dev", user_token="user")
    assert service.client.headers["Music-User-Token"] == "user"
    assert service.client.headers["Authorization"].split() == ["Bearer", "dev"]
