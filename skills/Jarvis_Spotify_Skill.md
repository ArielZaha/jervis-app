# Jarvis Spotify Integration Skill

## Purpose

You are an implementation agent working on **Jarvis**, a personal AI voice/chat assistant.

Your job is to implement, repair, or improve Jarvis's Spotify feature so that natural-language **voice and chat commands** can control the user's Spotify playback reliably.

The core requirement is:

1. A user asks Jarvis to play a **song, album, artist, or playlist**.
2. Jarvis identifies the requested Spotify resource, searches Spotify, selects an appropriate result, and starts playback.
3. Jarvis only reports success after the Spotify operation actually succeeds.
4. If anything goes wrong, Jarvis gives a **specific, useful explanation** of what failed and what the user can do next.
5. Do not fake success. Never say that something is playing merely because a search succeeded.

---

## Product Behavior

### Supported natural-language commands

Jarvis should understand commands such as:

- `Play Bohemian Rhapsody on Spotify`
- `Play Bohemian Rhapsody by Queen`
- `Play Queen on Spotify`
- `Play A Night at the Opera`
- `Play my Discover Weekly playlist`
- `Play the playlist called My Favorites`
- `Play the album OK Computer`
- `Play Radiohead`
- `Spotify, play ...`
- `Start playing ... on Spotify`
- `Put ... on Spotify`
- `Play ...`

The exact wording must not matter. Voice recognition and chat input can produce slightly different phrasing.

Jarvis should support at minimum:

- **Track/song**
- **Album**
- **Artist**
- **Playlist**

The implementation should be designed so additional Spotify resource types can be added later without rewriting the entire feature.

---

# Critical Implementation Rules

## 1. Use Spotify's official APIs

Prefer the official Spotify Web API for searching and playback control.

Do not implement the feature by scraping Spotify's website.

Do not invent Spotify API endpoints or request/response fields. Verify endpoint names and schemas against the current Spotify developer documentation before implementing or changing API code.

Relevant official documentation:

- Spotify Web API: https://developer.spotify.com/documentation/web-api
- Authorization: https://developer.spotify.com/documentation/web-api/concepts/authorization
- Search: https://developer.spotify.com/documentation/web-api/reference/search
- Start/Resume Playback: https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback
- Transfer Playback: https://developer.spotify.com/documentation/web-api/reference/transfer-a-users-playback
- Spotify URIs and IDs: https://developer.spotify.com/documentation/web-api/concepts/spotify-uris-ids

---

# Authentication

Playback control is a **user-authorized** Spotify operation.

The implementation must not use Client Credentials for playback control because Client Credentials does not represent the user's Spotify account.

For a desktop application such as Jarvis:

- Use Spotify OAuth user authorization.
- Prefer Authorization Code with PKCE when a client secret cannot safely be stored.
- If Jarvis has a genuinely secure backend where a client secret can be protected, Authorization Code may be appropriate.
- Never use the deprecated Implicit Grant flow.
- Store access/refresh credentials securely.
- Never hard-code secrets into source code.
- Never print access tokens, refresh tokens, or client secrets in logs.

At minimum, playback control requires the appropriate playback-control authorization scope, currently `user-modify-playback-state`.

Only request scopes that Jarvis actually needs.

If authorization is missing, expired, revoked, or insufficient, Jarvis must explain that Spotify needs to be connected/authorized rather than pretending the command worked.

---

# Required Architecture

Separate the Spotify feature into clear layers.

Recommended structure:

```text
Jarvis command input
        |
        v
Intent detection / command parsing
        |
        v
Spotify command object
        |
        v
Spotify authentication manager
        |
        v
Spotify search service
        |
        v
Result selection / disambiguation
        |
        v
Playback service
        |
        v
Playback verification
        |
        v
Jarvis response
```

Do not put all Spotify logic inside the main voice-listening loop.

The main assistant should call a small, predictable Spotify interface.

For example:

```python
result = spotify_service.play(
    query="Bohemian Rhapsody",
    resource_type="track",
    artist="Queen"
)
```

The exact language/API can differ depending on the existing Jarvis codebase, but the architectural separation should remain.

---

# Command Parsing

The command parser should extract:

```text
intent
resource_type
query
artist
album
playlist
optional device
```

Example:

```text
"Play Bohemian Rhapsody by Queen on Spotify"
```

Should become conceptually:

```json
{
  "intent": "spotify_play",
  "resource_type": "track",
  "query": "Bohemian Rhapsody",
  "artist": "Queen"
}
```

Example:

```text
"Play OK Computer by Radiohead"
```

Should become:

```json
{
  "intent": "spotify_play",
  "resource_type": "album",
  "query": "OK Computer",
  "artist": "Radiohead"
}
```

Example:

```text
"Play Radiohead"
```

Should become:

```json
{
  "intent": "spotify_play",
  "resource_type": "artist",
  "query": "Radiohead"
}
```

Example:

```text
"Play my favorite songs playlist"
```

Should be treated as a playlist request if the parser has enough evidence.

---

# Do Not Over-Rely on Exact Phrases

Do not build the feature around one exact sentence.

Avoid logic such as:

```python
if command == "play bohemian rhapsody":
```

Instead, normalize input and extract intent.

The parser should tolerate:

- `play`
- `start`
- `put on`
- `listen to`
- `play me`
- `can you play`
- `I'd like to hear`
- `on Spotify`
- `in Spotify`

The assistant should also tolerate normal speech-recognition noise where reasonable.

Do not make the parser so aggressive that ordinary conversation becomes a Spotify command.

---

# Determining Resource Type

Jarvis should use explicit language when available.

Examples:

```text
"play the album OK Computer"
=> album

"play the playlist Chill"
=> playlist

"play artist Radiohead"
=> artist

"play the song Karma Police"
=> track
```

If no type is specified:

```text
"play Radiohead"
```

the assistant should infer the most likely type from the command and search results.

If multiple resource types are plausible and the ambiguity matters, Jarvis may ask a short clarification question.

Example:

> I found both an album and a playlist called "Favorites. Which one should I play?

Do not ask unnecessary clarification questions when the result is obvious.

---

# Spotify Search

Use Spotify's search endpoint to locate the requested resource.

The Spotify Search API can search for albums, artists, playlists, and tracks.

Search should be performed with the narrowest sensible resource type.

Conceptually:

```text
track request    -> search for tracks
album request    -> search for albums
artist request   -> search for artists
playlist request -> search for playlists
```

When the user supplies an artist:

```text
"Play Imagine by John Lennon"
```

use the artist information to improve matching.

Do not blindly select the first search result if the first result is obviously unrelated.

---

# Result Matching

Result selection is extremely important.

The assistant must consider:

- Exact or near-exact name match
- Artist match
- Album match
- Resource type
- User wording
- Popularity/relevance when useful
- Explicit Spotify result metadata

For a track:

```text
requested title
requested artist
returned track title
returned artist names
```

should all be compared.

Example:

```text
User:
Play Numb by Linkin Park

Preferred:
Numb — Linkin Park
```

Do not accidentally play:

```text
Numb — another artist
```

when a Linkin Park result exists.

---

# Album Playback

When the user explicitly asks for an album:

```text
Play OK Computer
```

and the intent is determined to be an album, use the album Spotify URI/context rather than merely playing a random individual track from the album.

The playback request should use the album context when supported.

Conceptually:

```json
{
  "context_uri": "spotify:album:..."
}
```

This allows Spotify to play the album as a context.

If the user says:

```text
Play track 3 from OK Computer
```

that is a different feature and should use an appropriate track/offset strategy rather than pretending it is a normal album request.

---

# Artist Playback

When the user says:

```text
Play Radiohead
```

the assistant should recognize that the requested object is an artist.

Use the artist Spotify URI/context where supported.

Do not silently replace the request with a random Radiohead track unless that is explicitly the intended fallback behavior and is clearly documented.

If the current Spotify playback API behavior does not support the desired artist context directly, inspect the current Spotify API documentation and implement a supported strategy rather than inventing an endpoint.

---

# Playlist Playback

When the user asks:

```text
Play my workout playlist
```

or:

```text
Play the playlist Chill
```

search for playlists and select the correct playlist.

For user-owned/private playlists, make sure the OAuth permissions and API behavior actually allow the operation.

Never assume that a playlist is publicly searchable.

If the requested playlist cannot be found, tell the user exactly that.

---

# Starting Playback

Use Spotify's current playback endpoint to start/resume playback.

The relevant operation is currently:

```text
PUT /me/player/play
```

It can use a Spotify context URI for albums/playlists/other supported contexts or a track URI for individual tracks.

The user must have an appropriate Spotify account/device state for playback control.

Spotify currently documents that the playback-control endpoint requires Spotify Premium.

Do not hide this requirement behind a generic error.

---

# Active Device Handling

A common failure is that Spotify has no suitable active playback device.

Jarvis should:

1. Check available Spotify devices when necessary.
2. Prefer the user's currently active device when appropriate.
3. If there is no active/suitable device, explain the problem.
4. If the implementation chooses to transfer playback to a selected device, do so only when the user experience and permissions support it.

Example failure response:

> I found "OK Computer" on Spotify, but I couldn't start playback because Spotify doesn't currently have an active device. Open Spotify on one of your devices and try again.

Do not say:

> Done!

when no playback was started.

---

# Playback Verification

This is mandatory.

A successful HTTP response from the search endpoint only proves that the item was found.

A successful request to the playback endpoint should be treated as the playback operation succeeding according to Spotify's API response.

Where practical, verify playback state after starting playback, especially when the existing Jarvis architecture makes verification reliable.

The assistant must distinguish:

```text
FOUND
```

from:

```text
PLAYBACK STARTED
```

These are not the same state.

---

# Success Responses

When playback actually succeeds, Jarvis should give a concise natural response.

Examples:

```text
Playing Bohemian Rhapsody by Queen on Spotify.
```

```text
Playing OK Computer by Radiohead on Spotify.
```

```text
Playing the playlist "My Favorites" on Spotify.
```

Do not produce unnecessarily long success messages.

The success response should use the actual matched Spotify metadata where possible rather than repeating a potentially incorrect user transcription.

---

# Failure Responses

Failure messages must be specific and actionable.

Never use a generic:

```text
Something went wrong.
```

as the only response.

Instead, map failures to useful messages.

## Authentication failure

Example:

```text
I couldn't play that because Jarvis isn't currently authorized to control your Spotify account. Connect Spotify and try again.
```

## Token expired

Example:

```text
Your Spotify authorization expired, and Jarvis couldn't refresh it. Please reconnect Spotify.
```

## Permission/scope failure

Example:

```text
Jarvis is connected to Spotify, but it doesn't have permission to control playback. Re-authorize Spotify with playback-control permission.
```

## Search returned no result

Example:

```text
I couldn't find "OK Computer" on Spotify. Check the spelling or tell me the artist.
```

## Ambiguous result

Example:

```text
I found several close matches for "Favorites". Do you want the playlist, album, or track?
```

## No playback device

Example:

```text
I found the song, but Spotify doesn't have an active playback device right now. Open Spotify on a device and try again.
```

## Premium/account limitation

Example:

```text
Spotify found the item, but playback control isn't available for this account. Spotify's playback API requires Premium.
```

## Rate limit

If Spotify returns HTTP 429:

- Read `Retry-After`.
- Do not retry rapidly in a loop.
- Tell the user that Spotify is temporarily rate-limiting the request.
- Retry according to the API guidance when appropriate.

Example:

```text
Spotify is temporarily rate-limiting Jarvis. Please try again in a moment.
```

## Network/API failure

Example:

```text
I couldn't reach Spotify right now, so I couldn't start playback. Check your internet connection and try again.
```

## Unknown API error

Include useful non-secret information:

```text
I found the song, but Spotify rejected the playback request. Error: 403. Check that Jarvis has playback-control permission and that a supported Spotify device is available.
```

Never expose access tokens, client secrets, refresh tokens, authorization codes, cookies, or other credentials.

---

# Error Handling Contract

Spotify operations should return structured results rather than relying only on exceptions or printed strings.

Recommended conceptual result:

```python
SpotifyResult(
    success=True,
    action="play",
    resource_type="track",
    item_name="Bohemian Rhapsody",
    artist_name="Queen",
    spotify_uri="spotify:track:...",
    device_name="MacBook",
    error_code=None,
    error_message=None
)
```

Failure:

```python
SpotifyResult(
    success=False,
    action="play",
    resource_type="track",
    item_name="Bohemian Rhapsody",
    spotify_uri=None,
    error_code="NO_DEVICE",
    error_message="No active Spotify device is available."
)
```

The UI/voice layer should convert this structured result into a natural Jarvis response.

This separation makes debugging much easier.

---

# Logging

Logs should help developers diagnose failures.

Log:

- Command intent
- Resource type
- Search query
- Search result count
- Selected result name/type
- Spotify HTTP status code
- Sanitized error information
- Device availability
- Playback operation result

Never log:

- Access tokens
- Refresh tokens
- Client secrets
- Authorization codes
- Cookies
- Full Authorization headers

If the project already has a logging system, integrate with it rather than creating a second unrelated logging system.

---

# Existing Jarvis Integration

Before changing code:

1. Inspect the existing Jarvis project.
2. Find the current Spotify integration.
3. Identify how Spotify credentials are currently stored.
4. Identify the existing `spotipy` or raw Web API usage.
5. Identify how voice commands are parsed.
6. Identify how chat commands are parsed.
7. Identify how tool/action results are returned to the main LLM.
8. Reuse existing architecture where possible.

Do not create duplicate Spotify authentication systems unless the existing implementation is fundamentally unusable.

If Jarvis already uses Spotipy, prefer extending the existing Spotipy integration instead of replacing it with raw HTTP without a clear reason.

If the project uses raw HTTP, continue using the established HTTP abstraction if it is reliable.

---

# Voice and Chat Must Behave Consistently

The same Spotify command should work whether it came from:

```text
voice input
```

or:

```text
chat input
```

Both should eventually call the same Spotify service.

Bad architecture:

```text
voice -> separate Spotify implementation
chat  -> different Spotify implementation
```

Preferred architecture:

```text
voice -> command parser -> Spotify service
chat  -> command parser -> Spotify service
```

This prevents inconsistent behavior.

---

# LLM Tool Integration

If Jarvis uses an LLM/tool-calling architecture, expose Spotify playback as a deterministic tool.

Example conceptual schema:

```json
{
  "name": "spotify_play",
  "description": "Search Spotify for a track, album, artist, or playlist and start playback.",
  "parameters": {
    "type": "object",
    "properties": {
      "query": {
        "type": "string"
      },
      "resource_type": {
        "type": "string",
        "enum": [
          "track",
          "album",
          "artist",
          "playlist",
          "auto"
        ]
      },
      "artist": {
        "type": "string"
      }
    },
    "required": ["query"]
  }
}
```

The exact tool format must match the existing Jarvis LLM integration.

The LLM should decide **what the user wants**.

The Spotify service should decide **how to execute it reliably**.

Do not let the LLM directly fabricate Spotify URIs or claim that playback succeeded.

---

# Important LLM Rule

The model must never produce:

```text
"Playing now..."
```

before the tool has returned a successful result.

Correct sequence:

```text
User
  |
  v
LLM identifies Spotify request
  |
  v
spotify_play tool
  |
  v
Spotify search
  |
  v
Spotify playback request
  |
  v
success/failure result
  |
  v
LLM creates final response
```

---

# Handling Natural-Language Ambiguity

Examples:

### User:
```text
Play Queen
```

Possible meaning:

- Artist Queen
- Song called Queen
- Playlist called Queen

Prefer artist when the wording clearly indicates an artist request or the search results strongly support that interpretation.

### User:
```text
Play the song Queen
```

Track intent.

### User:
```text
Play Queen's greatest hits
```

This may refer to an album or playlist.

Search and choose carefully.

If ambiguity materially changes what gets played, ask the user.

---

# User-Friendly Matching

When a voice recognition system makes small errors, use reasonable normalization.

Examples:

```text
"radio head" -> Radiohead
"beeetles" -> Beatles
```

However, do not silently transform a clearly different title into another song.

If confidence is low, ask for clarification.

---

# Do Not Use Browser Automation Unless Necessary

The primary implementation should use the Spotify API.

Do not automate clicking around the Spotify website as the normal playback mechanism.

Browser automation may be considered only if a specific capability is genuinely unavailable through the official API and the project requirements explicitly justify it.

Even then, first verify the current Spotify API capabilities.

---

# Security

Never put secrets in:

- Git commits
- frontend JavaScript
- public GitHub repositories
- HTML
- client-visible configuration
- logs
- error messages

Use environment variables or secure OS credential storage as appropriate.

Recommended conceptual environment variables:

```text
SPOTIFY_CLIENT_ID
SPOTIFY_CLIENT_SECRET
SPOTIFY_REDIRECT_URI
```

Do not assume the client secret should exist in a desktop-distributed app. Follow Spotify's current OAuth guidance for the actual architecture.

---

# Testing Requirements

Before declaring the feature complete, test at least:

## Track

```text
Play Bohemian Rhapsody
Play Bohemian Rhapsody by Queen
Play a song called Numb by Linkin Park
```

Expected:

- Correct track is searched.
- Correct track is selected.
- Playback is started.
- Success is reported only after success.

## Album

```text
Play OK Computer
Play the album The Dark Side of the Moon
```

Expected:

- Album is found.
- Album context is used when appropriate.
- Playback starts.

## Artist

```text
Play Radiohead
Play Queen
```

Expected:

- Artist intent is identified.
- Appropriate Spotify context/playback behavior is used.

## Playlist

```text
Play my Favorites playlist
Play the playlist Discover Weekly
```

Expected:

- Playlist is found.
- Correct playlist is selected.
- Playback starts when possible.

## Failure tests

Test:

- Spotify disconnected
- Expired token
- Invalid credentials
- Missing scope
- No active device
- Spotify unavailable
- No search results
- Ambiguous results
- HTTP 401
- HTTP 403
- HTTP 429
- HTTP 5xx
- Malformed API response

Each should produce a useful Jarvis response.

---

# Acceptance Criteria

The Spotify feature is complete only when all of the following are true:

- [ ] Voice commands can request Spotify playback.
- [ ] Chat commands can request Spotify playback.
- [ ] Songs/tracks can be played.
- [ ] Albums can be played.
- [ ] Artists can be played using a supported Spotify playback strategy.
- [ ] Playlists can be played.
- [ ] Spotify search is used to identify requested content.
- [ ] Search results are matched intelligently.
- [ ] Playback is actually requested through Spotify.
- [ ] Jarvis does not claim success when only a search succeeded.
- [ ] Successful playback produces a concise success message.
- [ ] Every important failure produces a detailed, actionable response.
- [ ] Authentication errors are handled separately from search errors.
- [ ] No-device errors are handled separately.
- [ ] Permission errors are handled separately.
- [ ] Rate limiting is handled using Spotify's retry guidance.
- [ ] Secrets never appear in logs or user responses.
- [ ] Existing Jarvis architecture is reused where practical.
- [ ] The implementation does not duplicate Spotify logic unnecessarily.
- [ ] Tests cover successful and failed playback.
- [ ] Current Spotify API documentation has been checked before relying on endpoint behavior.

---

# Development Workflow

When asked to implement or fix this feature, follow this workflow.

## Step 1 — Inspect

Read the relevant Jarvis files first.

Find:

- Main assistant file
- Command parser
- LLM/tool definitions
- Spotify integration
- Configuration/environment loading
- Voice response code
- Chat response code
- Existing tests

Do not start rewriting files before understanding the current architecture.

## Step 2 — Diagnose

Identify the exact problem.

Examples:

```text
Spotify search works but playback doesn't.
```

```text
Playback works from chat but not voice.
```

```text
Jarvis says it succeeded even when Spotify returned 403.
```

```text
Playlist requests are incorrectly treated as tracks.
```

## Step 3 — Check Current Spotify API Documentation

Before implementing endpoint behavior, verify the current Spotify developer documentation.

Do not rely on old training data or deprecated API examples.

## Step 4 — Implement the Smallest Correct Change

Prefer targeted changes over rewriting the whole Jarvis project.

Preserve working features.

Do not remove unrelated functionality.

## Step 5 — Test

Run the project's existing test suite.

Then perform focused Spotify tests.

## Step 6 — Review Failure Paths

Make sure every important failure returns useful information to the assistant.

## Step 7 — Final Review

Check:

- Security
- API correctness
- Authentication
- Error handling
- Voice behavior
- Chat behavior
- Logging
- Regression risk

---

# Response Style

Jarvis should sound like a personal assistant, not a raw API wrapper.

Good:

> Playing "Bohemian Rhapsody" by Queen on Spotify.

Bad:

> HTTP 204 PUT /v1/me/player/play succeeded.

Good failure:

> I found "Bohemian Rhapsody" by Queen, but Spotify doesn't currently have an active playback device. Open Spotify on your Mac or another device and try again.

Bad failure:

> Spotify error.

Developer-facing logs may contain technical details; user-facing responses should translate those details into understandable language.

---

# Spotify API Compliance

When implementing this feature, follow Spotify's current Developer Terms and API documentation.

In particular:

- Do not use Spotify content to train an AI/ML model.
- Do not unnecessarily cache Spotify content.
- Keep Spotify content in its original form.
- Do not use Spotify content for non-interactive broadcasting.
- Follow current authorization requirements.
- Use least-privilege scopes.
- Respect rate limits.
- Do not bypass Spotify authentication or platform restrictions.

If the current Spotify documentation changes, update the implementation rather than relying on this skill's potentially outdated endpoint details.

---

# Source of Truth

For current Spotify API behavior, use the official Spotify Developer documentation as the source of truth.

Important references:

- Web API overview:
  https://developer.spotify.com/documentation/web-api
- Authorization:
  https://developer.spotify.com/documentation/web-api/concepts/authorization
- Search:
  https://developer.spotify.com/documentation/web-api/reference/search
- Start/Resume Playback:
  https://developer.spotify.com/documentation/web-api/reference/start-a-users-playback
- Transfer Playback:
  https://developer.spotify.com/documentation/web-api/reference/transfer-a-users-playback
- Spotify URIs and IDs:
  https://developer.spotify.com/documentation/web-api/concepts/spotify-uris-ids

---

# Final Instruction to the Coding Agent

You are not merely adding a "Spotify search" feature.

You are implementing a **reliable Spotify playback capability for Jarvis**.

The user's intent is:

> "Tell Jarvis what I want to hear, and Jarvis should find it on Spotify, actually start it, and clearly tell me whether it worked."

Therefore:

**Search is not success.**

**A generated Spotify URL is not success.**

**Calling a function is not success.**

**Saying "done" is not success.**

The feature succeeds only when Jarvis has completed the Spotify playback operation successfully or has accurately explained why it could not.

When modifying the project, preserve existing Jarvis functionality and integrate this feature cleanly into the existing architecture.
