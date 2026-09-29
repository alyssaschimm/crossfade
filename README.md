# crossfade
Crossfade is an easy way for friends to convert playlists between Apple Music and Spotify. As an active Apple Music user, this is a problem I have regularly and wanted to build something to fix it.

## How it works

Give crossfade a Spotify or Apple Music playlist link and it builds the same playlist on the other service, then prints the new playlist's link.

Each track goes through these steps, in order:

1. **Exact match**: looks the track up by its ISRC (the recording's unique ID). If that doesn't find it, crossfade searches the other service and accepts a result whose normalized title, artist and version (live, remix, acoustic, ...) are identical and whose length is within 5 seconds.
2. **Fuzzy match**: normalizes the titles first. That means removing `feat.` credits, "Remastered 2009", "Radio Edit" and "Original Mix" labels, accents and punctuation, and treating `&` the same as `and`. It then scores each result on how similar its title, artist and length are. A score of at least `0.85` counts as a match.
3. **LLM resolver**: a low-confidence score (between `0.6` and `0.85`) goes to an LLM. The LLM sees the source track and up to 5 search results and picks the same recording, or says none of them match. If it isn't confident (below `0.7`), the track is marked uncertain.

At the end you get a report grouping tracks into **matched**, **uncertain** and **unmatched**, with the reason for each. Only matched tracks go into the new playlist unless you pass `--include-uncertain`.

## Setup

```sh
pip install .
```

Set these environment variables:

| Variable | Required | Purpose |
| --- | --- | --- |
| `SPOTIFY_ACCESS_TOKEN` | yes | Spotify user access token with scopes `playlist-read-private playlist-modify-private playlist-modify-public` |
| `SPOTIFY_MARKET` | no | Country code for Spotify search results, e.g. `US` |
| `APPLE_MUSIC_DEVELOPER_TOKEN` | yes | Apple Music developer token (a signed JWT) |
| `APPLE_MUSIC_USER_TOKEN` | to create playlists or read library playlists | Music User Token for the listener's account |
| `APPLE_MUSIC_STOREFRONT` | no | Apple Music storefront to search (default `us`) |
| `OPENAI_API_KEY` | no | Turns on the LLM resolver. Without it, low-confidence tracks are reported as uncertain |
| `OPENAI_BASE_URL` / `CROSSFADE_LLM_MODEL` | no | Use a different OpenAI-compatible endpoint or model (default `gpt-4o-mini`) |

## Usage

```sh
crossfade https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
crossfade https://music.apple.com/us/playlist/todays-hits/pl.f4d106fed2bd41149aaacabb233eb5eb
crossfade https://music.apple.com/library/playlist/p.AbCd1234 --report report.json
```

The new playlist's link goes to stdout. Progress and the report go to stderr. Useful options:

- `--dry-run`: match tracks and show the report without creating a playlist
- `--include-uncertain`: also add uncertain matches to the new playlist
- `--report PATH`: also write the full report, including the top candidates for each track, as JSON
- `--name NAME`: name the new playlist something other than the original's name
- `--no-llm`, `--accept-threshold`, `--review-threshold`: control the matching pipeline

Apple Music playlists are created in your library, so their links (`https://music.apple.com/library/playlist/p....`) only open for your account. New Spotify playlists are private.

## Development

```sh
pip install -e '.[test]'
python -m pytest
```
