import pytest

from crossfade.llm import Resolution
from crossfade.matcher import Matcher
from crossfade.models import MatchStatus
from crossfade.services.base import ApiError
from fakes import FakeResolver, FakeService, track


def test_isrc_match_wins():
    target_track = track("Totally Different Title", "Someone", isrc="USUM71703861", id="1")
    target = FakeService("apple_music", [target_track])
    result = Matcher(target).match(track("Song", "Artist", isrc="USUM71703861"))
    assert result.status is MatchStatus.MATCHED
    assert result.method == "isrc"
    assert result.match == target_track
    assert result.confidence == 1.0


def test_exact_metadata_match_when_isrc_missing():
    wanted = track("Here Comes the Sun (2019 Mix)", "The Beatles", id="a")
    target = FakeService(
        "apple_music",
        [
            track("Here Comes the Sun (Live)", "The Beatles", id="live"),
            track("Here Comes the Sun - 2019 Mix", "The Beatles", id="b"),
        ],
    )
    result = Matcher(target).match(wanted)
    assert result.status is MatchStatus.MATCHED
    assert result.method == "exact"
    assert result.match.id == "b"


def test_exact_match_used_when_isrc_lookup_finds_nothing():
    target = FakeService("spotify", [track("Levels", "Avicii", id="spotify:track:1", isrc="OTHER")])
    result = Matcher(target).match(track("Levels (Radio Edit)", "Avicii", isrc="SE123"))
    assert result.method == "exact"
    assert result.status is MatchStatus.MATCHED


def test_fuzzy_match_above_threshold():
    target = FakeService("spotify", [track("Dont Stop Believing", "Journey", id="x", duration_ms=250000)])
    result = Matcher(target).match(track("Don't Stop Believin'", "Journey", duration_ms=251000))
    assert result.status is MatchStatus.MATCHED
    assert result.method == "fuzzy"
    assert 0.85 <= result.confidence < 1.0


def test_unmatched_when_nothing_found():
    result = Matcher(FakeService("spotify", [])).match(track("Obscure", "Nobody"))
    assert result.status is MatchStatus.UNMATCHED
    assert result.match is None


def test_unmatched_when_candidates_score_too_low():
    target = FakeService("spotify", [track("Completely Else", "Nobody", id="x")])
    result = Matcher(target).match(track("Hello", "Nobody"))
    assert result.status is MatchStatus.UNMATCHED
    assert result.candidates


LOW_CONFIDENCE_SOURCE = track("Creep", "Radiohead", duration_ms=238000)
LOW_CONFIDENCE_CANDIDATES = [
    track("Creep (Acoustic)", "Radiohead", id="acoustic", duration_ms=238000),
    track("Creep (Live)", "Radiohead", id="live", duration_ms=238000),
]


def low_confidence_target():
    return FakeService("spotify", LOW_CONFIDENCE_CANDIDATES)


def test_low_confidence_without_resolver_is_uncertain():
    result = Matcher(low_confidence_target()).match(LOW_CONFIDENCE_SOURCE)
    assert result.status is MatchStatus.UNCERTAIN
    assert result.match is not None
    assert "no LLM resolver" in result.reason


def test_low_confidence_goes_to_llm_which_can_pick():
    resolver = FakeResolver(Resolution(1, 0.9, "the live take"))
    result = Matcher(low_confidence_target(), resolver=resolver).match(LOW_CONFIDENCE_SOURCE)
    assert len(resolver.calls) == 1
    assert result.status is MatchStatus.MATCHED
    assert result.method == "llm"
    assert result.match == resolver.calls[0][1][1]
    assert result.confidence == 0.9


def test_llm_low_confidence_pick_is_uncertain():
    resolver = FakeResolver(Resolution(0, 0.4, "maybe"))
    result = Matcher(low_confidence_target(), resolver=resolver).match(LOW_CONFIDENCE_SOURCE)
    assert result.status is MatchStatus.UNCERTAIN
    assert result.method == "llm"


def test_llm_rejecting_all_candidates_is_unmatched():
    resolver = FakeResolver(Resolution(None, 0.95, "all are alternate versions"))
    result = Matcher(low_confidence_target(), resolver=resolver).match(LOW_CONFIDENCE_SOURCE)
    assert result.status is MatchStatus.UNMATCHED
    assert result.match is None
    assert "alternate versions" in result.reason


def test_llm_failure_falls_back_to_uncertain():
    resolver = FakeResolver(Resolution(None, 0.0, "LLM request failed", ok=False))
    result = Matcher(low_confidence_target(), resolver=resolver).match(LOW_CONFIDENCE_SOURCE)
    assert result.status is MatchStatus.UNCERTAIN


def test_resolver_not_called_for_confident_matches():
    resolver = FakeResolver(Resolution(None, 1.0))
    target = FakeService("spotify", [track("Creep", "Radiohead", id="x")])
    Matcher(target, resolver=resolver).match(track("Creep", "Radiohead"))
    assert resolver.calls == []


def test_duplicate_tracks_are_looked_up_once():
    target = FakeService("spotify", [track("Creep", "Radiohead", id="x")])
    matcher = Matcher(target)
    matcher.match(track("Creep", "Radiohead"))
    matcher.match(track("Creep", "Radiohead"))
    assert len(target.searches) == 1


def test_api_errors_become_unmatched():
    class Broken(FakeService):
        def search(self, title, artist):
            raise ApiError("boom", 500)

    result = Matcher(Broken("spotify")).match(track("Creep", "Radiohead"))
    assert result.status is MatchStatus.UNMATCHED
    assert "boom" in result.reason


def test_invalid_thresholds():
    with pytest.raises(ValueError):
        Matcher(FakeService("spotify"), accept_threshold=0.5, review_threshold=0.7)
