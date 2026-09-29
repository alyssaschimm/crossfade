import json

import requests

from crossfade.llm import OpenAIResolver, build_messages, parse_resolution
from fakes import track


def test_parse_valid_choice():
    r = parse_resolution(json.dumps({"choice": 2, "confidence": 0.8, "reason": "same"}), 3)
    assert (r.index, r.confidence, r.reason, r.ok) == (1, 0.8, "same", True)


def test_parse_null_choice():
    r = parse_resolution('{"choice": null, "confidence": 0.9}', 3)
    assert r.index is None and r.ok and r.confidence == 0.9


def test_parse_clamps_confidence():
    assert parse_resolution('{"choice": 1, "confidence": 7}', 1).confidence == 1.0


def test_parse_rejects_bad_output():
    for content in ["not json", "[]", '{"choice": 4, "confidence": 1}', '{"choice": 0}',
                    '{"choice": "1"}', '{"choice": true}', '{"choice": 1.5}', '{"choice": 1, "confidence": "x"}',
                    '{"choice": 1, "confidence": NaN}']:
        assert not parse_resolution(content, 3).ok, content


def test_build_messages_numbers_candidates():
    messages = build_messages(track("A", "B"), [track("C", "D"), track("E", "F")])
    payload = json.loads(messages[1]["content"])
    assert [c["number"] for c in payload["candidates"]] == [1, 2]
    assert payload["source"]["title"] == "A"


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_openai_resolver_request_and_response():
    content = json.dumps({"choice": 1, "confidence": 0.75, "reason": "ok"})
    session = FakeSession(FakeResponse({"choices": [{"message": {"content": content}}]}))
    resolver = OpenAIResolver("key", model="m", base_url="https://llm.test/v1/", session=session)
    result = resolver.resolve(track("A", "B"), [track("A", "B")])
    assert result.index == 0 and result.ok
    url, kwargs = session.calls[0]
    assert url == "https://llm.test/v1/chat/completions"
    assert kwargs["headers"]["Authorization"].split() == ["Bearer", "key"]
    assert kwargs["json"]["model"] == "m"


def test_openai_resolver_http_error_is_not_ok():
    resolver = OpenAIResolver("key", session=FakeSession(FakeResponse({}, status=500)))
    assert not resolver.resolve(track("A", "B"), [track("A", "B")]).ok


def test_from_env():
    assert OpenAIResolver.from_env({}) is None
    resolver = OpenAIResolver.from_env({"OPENAI_API_KEY": "k", "CROSSFADE_LLM_MODEL": "x"})
    assert resolver.model == "x"
