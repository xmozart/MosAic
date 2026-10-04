# Product

## 1. Vision

Point the app at a folder of trip footage and photos. It builds a persistent semantic understanding of the material and then produces many finished edits from it: a 60-second reel, a 5-minute film, a wildlife cut, a vertical version. Each edit takes minutes and needs no re-analysis.

The core asset is the **semantic footage library**. It is not a one-shot "auto edit."

Target users:
- **v1:** the owner, a technically fluent non-editor.
- **Later:** consumers and prosumers with any camera and any trip length.

## 2. Primary workflow

1. **Open a footage folder.** The app shows the storage placement it will use and states: *Original footage stays where it is and will not be modified.*
2. **Inventory (L0).** Shows cameras, days, duration, photos, unsupported files with reasons, cloud-only files, and suggested device clock offsets to confirm.
3. **Trip context (optional).** Skippable, and can be added or edited at any time (§3).
4. **Pick an analysis mode** (Quick / Balanced / Thorough / Custom). The screen shows time, storage and cost estimates.
5. **Analysis runs in the background.** The user can browse and review footage as results arrive.
6. **Review footage (optional).** Star ratings, USE/MAYBE/REJECT, always/never include, notes and tags.
7. **Create an edit.** Pick goals in a wizard. Settings are pre-filled from preferences.
8. **Storyboard.** The proposed beats appear as cards. The user can reorder, lock or regenerate a beat.
9. **Preview.** A proxy render plus critic findings, each with an Apply or Ignore action.
10. **Final render.** Output from the original media.
11. **More versions.** Create additional edits from the same library.

## 3. Trip context (optional)

A `TripContext` improves summaries, story beats, titles and chronology. It is never required. Every prompt must work without it.

```json
{
  "trip_name": "Costa Rica 2026",
  "home_timezone": "America/Toronto",
  "days": [
    {"date": "2026-07-14", "place": "San José → La Fortuna", "timezone": "America/Costa_Rica", "notes": "Arrival, drive"},
    {"date": "2026-07-15", "place": "Arenal / La Fortuna waterfall", "notes": "Hike, hanging bridges"}
  ],
  "people": [
    {"label": "Maya", "description": "younger daughter, yellow raincoat"}
  ],
  "must_include": ["the toucan at breakfast on day 3"],
  "avoid": ["car interiors"],
  "free_notes": "Celebrating our 20th anniversary."
}
```

Behaviour:
- **Entry points:** a form, pasted free text (an itinerary or notes, parsed by AI into the structure above for the user to confirm), or both.
- **Changing context** re-runs only the summary and labeling tasks. Vision analysis is not re-run.
- **"Help me label" (optional):** after L2, the app may ask up to 5 targeted, skippable questions, for example "Where was Day 3?" or "Is this the same person in these clips?"
- **People** are handled through text descriptions only in v1. There is no face recognition. Descriptions let the model match "girl in yellow raincoat."

## 4. Edit request

Wizard sections. Every section has a default, and the always-visible summary panel restates the current choices.

**Duration**
- Presets: 15 s, 30 s, 60 s, 90 s, 2, 3, 5, 10, 15, 20 min, or custom.
- Strict or approximate (± tolerance, default ±5%).

**Destination**
- Presets: 16:9 (YouTube/TV), 9:16 (Reels/TikTok/Shorts), 4:5, 1:1, 2.39:1, native, or custom.
- Resolution: 720p, 1080p, 1440p, 4K, or source.
- Frame rate: native, 23.976, 24, 25, 29.97, 30, 50, 59.94, 60, or a custom rational.
- Non-native aspect ratios use a center/subject crop in v1. Smart reframing comes later.

**Story**
- Preset: chronological diary, cinematic journey, adventure highlights, family memories, people-first, nature, wildlife, food & culture, city, road trip, relaxed, high-energy montage, documentary, funny moments, drone showcase, event recap, or custom.
- Chronology: strict, mostly chronological, thematic, or story-driven.
- Arc: classic travel, fast highlight, documentary, or custom beats (the user enters an ordered list).

**Content weights**
- Each category is weighted Avoid / Less / Neutral / More / Strongly prefer.
- Categories: people, reactions, landscapes, wildlife, architecture, food, culture, activities/action, drone, POV, selfies, conversations, natural sound, humor, transport, sunsets, water, night, city, slow motion, timelapse, photos.

**Editing rules**
- Avoid repetition.
- Allow imperfect but emotional clips.
- Unique moments over technical quality, or the reverse.
- Drone as openers.
- Aggressively remove dead time.
- Allow long cinematic holds.
- Photo share (none / some / many).

**Pace**
- Very slow, slow/cinematic, balanced, energetic, fast, very fast.
- Advanced: min, preferred and max shot length. Exceptions are allowed for dialogue, reactions and hero shots.

**Transitions**
- Mostly cuts (default), soft dissolves, or minimal.
- The editor prefers simple professional cuts. Synthetic transitions are the exception.

**Audio**
- Preserve dialogue.
- Prioritize natural sound.
- Suppress wind/noisy audio.
- Loudness target: web or TV.

**Music**
- v1 behaviour: none, or a user track laid under the edit with fades and a static level.
- Beat and phrase awareness come later.

**Custom instructions**
- Free text.

## 5. Screens

The screens are designed and approved. The visual reference is the canvas: https://claude.ai/artifact/K5A2TuoKdXjcnoSrFxXNSc. Behavior, states, data and keyboard rules are specified in `docs/ui/` (see `docs/ui/README.md` for the screen index S0–S26 and their milestones).

Visual direction:
- Dark-first, with a complete light theme.
- Golden-hour amber as the single accent.
- Geist and Geist Mono typefaces.
- Footage as the interface.
- A strict AI-vs-you visual distinction.

## 6. Configuration scopes

Resolution order, highest priority first:

```text
Render override > Edit override > Project setting > User preference > Built-in default
```

Each scope stores only the values that differ from the scope below it. Every setting shows its effective value and where it came from, and has a Reset button. Config schemas are versioned and migrated automatically. Unknown fields are preserved.

## 7. Inspectability

Every selected event shows its role, the reason it was chosen, its alternatives with the reasons they were not chosen, source file and time range, quality indicators and the AI description. Every rejected segment shows its reasons.

## 8. Regeneration granularity

Available actions:
- regenerate the whole edit, the story only, or one beat
- replace one shot from its alternatives
- make a section faster or slower
- more or less of a content category
- stronger opening, different ending
- change duration

Every action creates a new version and respects locks.
