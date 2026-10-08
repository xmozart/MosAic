# Components

Build these in `frontend/src/components/`. Each needs a Storybook story for every listed state. Reference: `docs/ui/reference/DS-Components.dc.html`.

## Shell

| Component | Props | States / notes |
|---|---|---|
| `AppRail` | `active`, `activity?: {pct, jobs[]}` | 72 px wide. Logo, then Home / Library / Edits / Exports / Settings, then the activity ring, theme toggle and help. The active item gets an `accent-soft` background and `accent` icon. |
| `ActivityPopover` | `jobs: JobSummary[]` | Lists running jobs with progress, Pause/Cancel. Opened from the rail ring. The ring pulses while jobs run (unless reduced motion). |
| `ProjectHeader` | `name`, `placement`, `status`, `aiCost`, `crumb?` | 56 px tall. Project name is editable inline. Status chip variants: Analyzed · mode / Analyzing n% / Preliminary / Not analyzed / Scanned. ⌘K hint. |
| `CommandPalette` | — | ⌘K. Searches footage, clips and actions; keyboard-first. |
| `Toast` | `kind`, `message`, `action?` | Bottom-right. Undo action for version creation. |
| `ConfirmDialog` | `title`, `body`, `actions` | Used for the four global dialogs (see S0). |

## Media

| Component | Props | States |
|---|---|---|
| `ClipTile` | `asset`, `disposition?`, `decidedBy: 'ai'\|'user'`, `stars`, `hasSpeech`, `similarCount`, `selected`, `density`, `caption?` | default, hover (scrub + stars), selected, USE/MAYBE/REJECT × ai/user, dimmed REJECT, Live Photo badge, 360 analysis-only overlay, offline overlay (proxy still plays), unsupported overlay with reason, preliminary (chip shimmer, no disposition yet), similar stack (`+n` with a stacked edge) |
| `DispositionChip` | `value`, `by`, `size` | AI: outlined + "AI" tag. User: filled + blue person badge. |
| `DispositionControl` | `value`, `onChange` | Segmented USE/MAYBE/REJECT with U/M/R hints. |
| `StarRating` | `value`, `onChange` | 1–5 keys; the accent color is reserved for filled stars. |
| `IncludeToggle` | `value: always\|never\|none`, `onChange` | Always shown in `user` blue. One value, because a clip cannot be both (L and X toggle it). |
| `Player` | `src`, `rate` (the proxy's frame rate), `usableRange?`, `markers?`, `range?`, `onTime?`; handle `seekTo(SourceTime)` (to the frame that contains it), `toggle()`, `focus()` | Proxy playback through HTTP range requests. Shows the usable range highlighted and markers (moments, findings). Shortcuts: Space, J/K/L, ←/→ (one frame), Shift+←/→ (one second). |
| `Filmstrip`, `Waveform` | `assetId`, `range` | Highlights the selection. |
| `Transcript` | `lines[]` (sentences with timed words), `now`, `language`, `onSeek` | Highlights the current word (`aria-current`); clicking a word or a line's timestamp seeks; each line's timestamp is its tab stop. No speaker labels (ADR 0043). |
| `QualityRow` | `sharpness, steadiness, exposure, audio` | Ordinal words, never numbers. Tooltips explain each. |
| `SimilarShots` | `groupId` | Shows a "Why this one is preferred" line under each alternative. |
| `CameraBadge` | `kind: phone\|actioncam\|360\|drone\|camera\|photo` | Lucide icon plus short label. |

## Library

| Component | Notes |
|---|---|
| `LibraryToolbar` | Search, filter chips (Day, Camera, Type, Disposition, Rating, Shot type, Has speech, plus More), Group (Day/Camera/Similar), Density, "Deepen analysis…", "Create edit". |
| `GroupHeader` | Collapsible; title, plus clip, duration and photo counts. |
| `DayScrubber` | Right-edge D1…Dn jump list for long trips. |
| `BulkBar` | Floating bar at bottom center when 2 or more clips are selected. |
| `ClipInspector` | 400 px sheet. Section order is fixed: player, usable-range note, title line, disposition, AI-vs-you line, include, Why, Moments, Quality, Similar, Tags, Note, Used in edits. |
| `VirtualGrid` | Virtualized grid, tiles at min 220 px (comfortable) / 160 px (compact). At most about 60 tiles mounted. |

## Editing

| Component | Notes |
|---|---|
| `WizardStepNav` | Six steps. Done steps show ✓ and are clickable. Steps not built yet are disabled, with a note under the list (M2: steps 3–5; ADR 0048). `components/edit/Wizard.tsx`. |
| `EditSummaryPanel` | 340 px. Plain-language lines (from `summaryLines(request)`), lock and must-include chips (M4), warnings, estimate (skeleton while loading), primary "Create edit". |
| `DurationChips`, `AspectPicker` | AspectPicker draws visual frames; an option can be disabled (Native in M2). Both are radio groups. `ChoiceChip` is the shared selected style (accent-soft + accent border). |
| `StoryPresetCard` | Collage built from the user's own matching clips (`/api/projects/{id}/presets/{preset}/collage`): one large frame and two small ones; a pulse while loading; a dashed frame for Custom or when no clip matches. |
| `WeightSlider` | Five steps: Avoid · Less · Neutral · More · Strongly prefer. Keyboard ←/→. ARIA slider. |
| `PaceSlider` | Six stops with a live "about n s per shot" readout. |
| `BeatCard` | Title, intent, share, shot chips, Locked state (`user` border), Regenerating state (shimmer), infeasible warning, actions (Regenerate, Faster/Slower, ⋯ menu). Drag handle. |
| `ShotChip` + `ShotPopover` | Popover shows the reason, role, and alternatives with why-not, plus Lock, Remove and Play. |
| `DurationBar` | Proportional beats with target marker and tolerance. |
| `FindingCard` | Severity (Issue / Suggestion), clickable timecode, text, suggested fix, Apply/Ignore, "Applied in vN" state. |
| `EditFacts` | Duration, target, shots, average shot, beats, days covered, photos, AI cost. |
| `VersionList`, `VersionCompare` | Synced/independent players plus a change list (Replaced / Trimmed / Moved / Removed). |
| `EditCard` | Cover (in the edit's shape: 9:16, 4:5 or 1:1 centred), duration, format, versions, status dot and words, a progress ring while generating, created date, preliminary warning. The whole card is one link (`renderLink`). `components/edit/EditCard.tsx`. |

## System

| Component | Notes |
|---|---|
| `StageList` | Each stage is pending / running (ring) / done (✓) / failed / paused, with a mono note. |
| `ModeCard` | Analysis mode with an estimate line in mono; a skeleton line while the estimate loads. |
| `EstimateCard` | Time · cost · storage. |
| `PlacementBadge` | In folder / Split · NAS / Split · iCloud / Stored separately / External drive. |
| `UnsupportedRow` | Icon, title, reason, fix action, optional inline progress; rows divide one "Needs attention" card. |
| `ClockOffsetRow` | Evidence pair (left), explanation, offset stepper (+/− keys: 1 h, Shift: 1 min) and a segmented Accept suggestion / Adjust / Leave as is (right). Without a suggestion: stepper, Adjust and Leave only. |
| `SettingRow` | Shows the effective value, "From: default / your preference / this project", and Reset. |
| `SecretField` | Write-only. Shows "Connected · ••••last4", Validate, Replace. |
| `StorageBreakdown` | Stacked bar with Regenerable/Kept tags. |
