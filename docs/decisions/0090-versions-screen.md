# 0090 — S18 Versions: the list, the pair compared, synced players

- Status: accepted (M4 step 14e)
- Deciders: agent (autonomous; no human gate)

## Context

S18 lists an edit's versions (who made each, why, when, how long) and compares two side by side. It has two players, Synced / Independent, a "What changed" list (Replaced / Trimmed / Moved / Removed with timecodes) and Revert. ADR 0083 made `/compare` and `/revert`. The version list had no creator or reason, and the compare gave segment refs with no file names or lengths.

## Decision

- **`GET /versions`** items gain `creator`, `reason` and `parent_version`. **`/compare`** changes gain `file_a/b` (the clip's file name), `frames_a/b` (its length on each timeline) and `beat_a/b` (its beat's title). These are for display; the frames stay exact.
- **The pair**: by default, the latest version and the one before it. Clicking a version compares it with the latest; clicking the latest returns to the default. "Compare vN-1 ↔ vN" also returns to it. The pair is in the URL (`?a=&b=`).
- **Revert** goes to the older of the pair. It is offered only while the newer one is the latest version and the two differ: after a revert the two are the same, and another click would only add a copy. The new version is shown against the version it equals, and its render reuses the earlier file (ADR 0083, M4 acceptance 5).
- **The words**:
  - "A → B" for a replaced shot;
  - "extended +1.2 s" or "shortened −0.8 s" for a trimmed one, from the frames;
  - "→ Finale" for a shot moved to another beat, else "moved";
  - the file name for a removed shot.
  
  A timecode seeks both players to that point.
- **Synced** mirrors play, pause and seeks from one player to the other. `Player` gained `onPlayState`, `onSeeked` and `play()`, `pause()` and `seekSeconds()` on its handle; the seconds are display values. Nothing echoes back: `play()` on a playing video, `pause()` on a paused one and a seek to where the player already is (within half a frame) fire no event. **Independent** leaves each player alone.
- **Previews**: a compared version without a preview offers Render preview. The page does not start two renders by itself, as S17 does for one.
- **Route**: `/p/:pid/edits/:eid/versions`. S17 shows Versions once an edit has more than one.

## Consequences

- The compare reads one file name per change, so it costs one query per change.
