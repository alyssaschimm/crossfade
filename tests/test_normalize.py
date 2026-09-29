import pytest

from crossfade.normalize import artist_similarity, normalize_title, score_tracks, search_title
from fakes import track


@pytest.mark.parametrize(
    "a, b",
    [
        ("Here Comes the Sun - Remastered 2009", "Here Comes the Sun (2019 Remaster)"),
        ("Levels - Original Mix", "Levels"),
        ("Levels - Radio Edit", "Levels"),
        ("Sicko Mode (feat. Drake)", "SICKO MODE"),
        ("Rock & Roll", "Rock and Roll"),
        ("Señorita", "Senorita"),
        ("Don’t Stop Me Now", "Don't Stop Me Now"),
        ("Let It Go - From \"Frozen\"/Soundtrack Version", "Let It Go"),
    ],
)
def test_equivalent_titles_normalise_identically(a, b):
    assert normalize_title(a) == normalize_title(b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Song - Live at Wembley 1986", "Song"),
        ("Blinding Lights - Chromatics Remix", "Blinding Lights"),
        ("Creep (Acoustic)", "Creep"),
    ],
)
def test_different_versions_keep_distinguishing_tags(a, b):
    assert normalize_title(a).core == normalize_title(b).core
    assert normalize_title(a).tags != normalize_title(b).tags


def test_meaningful_parentheses_are_kept():
    assert normalize_title("(Don't Fear) The Reaper").core == "dont fear the reaper"
    assert normalize_title("All Too Well (Taylor's Version)").core != normalize_title("All Too Well").core


def test_search_title_drops_noise_but_keeps_versions():
    assert search_title("Sicko Mode (feat. Drake)") == "Sicko Mode"
    assert search_title("Here Comes the Sun - Remastered 2009") == "Here Comes the Sun"
    assert search_title("Creep (Acoustic)") == "Creep (Acoustic)"


def test_artist_similarity_handles_combined_credits():
    assert artist_similarity(["Travis Scott", "Drake"], ["Travis Scott & Drake"]) == 1.0
    assert artist_similarity(["The Beatles"], ["Beatles"]) == 1.0
    assert artist_similarity(["Earth, Wind & Fire"], ["Earth, Wind & Fire"]) == 1.0
    assert artist_similarity(["Adele"], ["Metallica"]) < 0.5


def test_score_exact_and_fuzzy():
    src = track("Here Comes the Sun - Remastered 2009", "The Beatles", duration_ms=185733)
    same = track("Here Comes the Sun", "The Beatles", duration_ms=185800)
    assert score_tracks(src, same).exact

    live = track("Here Comes the Sun (Live)", "The Beatles", duration_ms=185800)
    live_score = score_tracks(src, live)
    assert not live_score.exact
    assert live_score.value < score_tracks(src, same).value

    far = track("Here Comes the Sun", "The Beatles", duration_ms=240000)
    assert not score_tracks(src, far).exact


@pytest.mark.parametrize(
    "a, b",
    [
        (["Queen"], ["Queen Latifah"]),
        (["Prince Royce"], ["Prince"]),
        (["Train"], ["Train Robbers"]),
    ],
)
def test_artist_name_prefix_is_not_a_full_match(a, b):
    assert artist_similarity(a, b) < 1.0
    assert not score_tracks(track("Crazy", *a, duration_ms=200000), track("Crazy", *b, duration_ms=201000)).exact


def test_artist_similarity_matches_listed_artist_inside_combined_credit():
    assert artist_similarity(["Earth, Wind & Fire", "The Emotions"], ["Earth, Wind & Fire & The Emotions"]) == 1.0
    assert artist_similarity(["Drake"], ["Travis Scott feat. Drake"]) == 1.0
    assert artist_similarity(["Lil Nas X", "Billy Ray Cyrus"], ["Lil Nas X & Billy Ray Cyrus"]) == 1.0
