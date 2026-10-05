"""Cut refiner and timeline layout (ARCHITECTURE.md §9).

Each solved shot gets a source window inside its usable range, then its in and out points
are snapped:

- after the camera settles (non-dialogue shots slide past a jolt at the in point);
- never inside a word (in moves to a word start, out to a word end);
- dialogue shots start at a sentence start and end at a sentence end (extended when the
  sentence fits, otherwise ended at the previous sentence);
- onto the source frame grid, with the length a whole number of timeline frames.

Segments never span a shot cut, so neither does an event. Then adjacent jump cuts (same
recording, < 2 s apart) are removed by merging, reordering or dropping, and the out points
of non-dialogue shots absorb the last frames so the edit lands on its exact target.
All arithmetic is in integer ticks and frames (invariant 3).
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from mosaic.core.time import Rounding, parse_rational, round_fraction
from mosaic.editing.request import PaceFrames
from mosaic.editing.solver import Shot, bounds

JUMP_GAP = Fraction(2)  # seconds: closer same-recording neighbours are a jump cut
WORD_MARGIN = Fraction(1, 50)  # seconds: word timestamps are approximate (±20 ms)
SETTLE_LOOKAHEAD = Fraction(1)  # seconds a non-dialogue in point may slide to settle
SETTLE_FACTOR = 2.0
SETTLE_FLOOR = 0.008
FADE_FRAMES = 2
GAIN_DB = {"dialogue": 0, "natural_sound": -6, "natural_sound_low": -14, "mute": 0}


@dataclass(frozen=True)
class ClipContext:
    """Speech and motion around one segment, in the asset's ticks."""

    words: list[tuple[int, int]] = field(default_factory=list)
    sentences: list[tuple[int, int]] = field(default_factory=list)
    motion: list[tuple[int, int, float]] = field(default_factory=list)
    best_ticks: int | None = None


@dataclass
class Cut:
    shot: Shot
    src_in: int
    src_out: int
    frames: int
    ctx: ClipContext
    merged_refs: list[str] = field(default_factory=list)
    end_at_speech: bool = False
    merged_shots: list[Shot] = field(default_factory=list)  # shots merged into this cut
    # The usable source range this cut may use: its segment's, or after a merge the span of
    # the merged segments (adjacent segments of one take).
    ua: int = -1
    ub: int = -1

    def __post_init__(self) -> None:
        if self.ua < 0:
            self.ua = self.shot.cand.usable_start
        if self.ub < 0:
            self.ub = self.shot.cand.usable_end

    @property
    def tb(self) -> Fraction:
        return parse_rational(self.shot.cand.tb)


def ticks_for_frames(n: int, rate: str, tb: Fraction, rounding: Rounding) -> int:
    return round_fraction(Fraction(n) / parse_rational(rate) / tb, rounding)


def frames_for_ticks(t: int, rate: str, tb: Fraction, rounding: Rounding) -> int:
    return round_fraction(Fraction(t) * tb * parse_rational(rate), rounding)


def inside(t: int, span: tuple[int, int], margin: int) -> bool:
    s, e = span
    return s + margin < t < e - margin


def margin_ticks(tb: Fraction) -> int:
    return round_fraction(WORD_MARGIN / tb, Rounding.FLOOR)


def word_at(t: int, words: list[tuple[int, int]], margin: int) -> tuple[int, int] | None:
    return next((w for w in words if inside(t, w, margin)), None)


# --------------------------------------------------------------------- placing


def place(shot: Shot, ctx: ClipContext, rate: str) -> tuple[int, int]:
    """A window of ``shot.frames`` inside the usable range: dialogue from the first
    sentence that starts in it, other shots centred on the best frame."""
    c = shot.cand
    tb = parse_rational(c.tb)
    length = ticks_for_frames(shot.frames, rate, tb, Rounding.CEIL)
    ua, ub = c.usable_start, c.usable_end
    length = min(length, ub - ua)
    if shot.dialogue:
        starts = [s for s, _ in ctx.sentences if ua <= s < ub] or [
            s for s, _ in ctx.words if ua <= s < ub
        ]
        start = starts[0] if starts else ua
        start = min(start, ub - length)
        return start, start + length
    centre = ctx.best_ticks if ctx.best_ticks is not None else (ua + ub) // 2
    start = max(ua, min(centre - length // 2, ub - length))
    return start, start + length


def settle(shot: Shot, ctx: ClipContext, a: int, b: int) -> tuple[int, int]:
    """Slide a non-dialogue window forward (≤ 1 s) past a camera jolt at its in point."""
    if shot.dialogue or not ctx.motion:
        return a, b
    c = shot.cand
    tb = parse_rational(c.tb)
    values = [v for _, _, v in ctx.motion]
    limit = max(SETTLE_FLOOR, SETTLE_FACTOR * statistics.median(values))
    room = min(c.usable_end - b, round_fraction(SETTLE_LOOKAHEAD / tb, Rounding.FLOOR))
    for s, e, v in ctx.motion:
        if s <= a < e and v > limit:
            shift = min(e - a, room)
            return a + shift, b + shift
    return a, b


def snap_speech(
    shot: Shot, ctx: ClipContext, a: int, b: int, pace: PaceFrames, rate: str
) -> tuple[int, int, bool]:
    """Move cuts out of words; dialogue cuts onto sentence boundaries. Returns the window
    and whether the out point sits on a speech end (so alignment rounds outward)."""
    c = shot.cand
    tb = parse_rational(c.tb)
    m = margin_ticks(tb)
    ua, ub = c.usable_start, c.usable_end
    hi = ticks_for_frames(shot.hi or pace.max, rate, tb, Rounding.FLOOR)
    lo = ticks_for_frames(min(pace.min, shot.hi or pace.min), rate, tb, Rounding.CEIL)
    at_speech_end = False
    if shot.dialogue and ctx.sentences:
        sent = next((s for s in ctx.sentences if inside(a, s, m)), None)
        if sent and sent[0] >= ua:
            a = sent[0]
        sent = next((s for s in ctx.sentences if inside(b, s, m)), None)
        if sent:
            if sent[1] <= ub and sent[1] - a <= hi:
                b, at_speech_end = sent[1], True
            else:
                ends = [e for s, e in ctx.sentences if a < e <= b and e - a >= lo]
                if ends:
                    b, at_speech_end = max(ends), True
    w = word_at(a, ctx.words, m)
    if w:
        a = w[0] if w[0] >= ua else w[1]
    w = word_at(b, ctx.words, m)
    if w:
        if w[1] <= ub and w[1] - a <= max(hi, b - a):
            b, at_speech_end = w[1], True
        elif w[0] - a >= lo:
            b = w[0]
    return a, max(b, a + 1), at_speech_end


def align(cut: Cut, rate: str) -> None:
    """In point onto the source frame grid; length a whole number of timeline frames,
    never past the usable range and never ending inside a word."""
    c = cut.shot.cand
    tb = cut.tb
    m = margin_ticks(tb)
    ua, ub = cut.ua, cut.ub
    a, b = cut.src_in, cut.src_out
    if c.rate:
        src = parse_rational(c.rate)
        k = round_fraction(Fraction(a) * tb * src, Rounding.FLOOR)
        down = round_fraction(Fraction(k) / src / tb, Rounding.CEIL)
        up = round_fraction(Fraction(k + 1) / src / tb, Rounding.CEIL)
        # Round down onto the grid unless that leaves the usable range or enters a word.
        a = down if down >= ua and word_at(down, cut.ctx.words, m) is None else up
    one = ticks_for_frames(1, rate, tb, Rounding.CEIL)
    if a + one > ub:  # less than a frame of room after rounding up: step back inside
        a = max(ua, ub - one)
    want = Fraction(b - a) * tb * parse_rational(rate)
    n = round_fraction(want, Rounding.CEIL if cut.end_at_speech else Rounding.FLOOR)
    n = max(1, n)
    while n > 1:
        out = a + ticks_for_frames(n, rate, tb, Rounding.CEIL)
        if out <= ub and word_at(out, cut.ctx.words, m) is None:
            break
        n -= 1
    cut.src_in = a
    cut.src_out = a + ticks_for_frames(n, rate, tb, Rounding.CEIL)
    cut.frames = n


def refine(shot: Shot, ctx: ClipContext, pace: PaceFrames, rate: str) -> Cut:
    a, b = place(shot, ctx, rate)
    a, b = settle(shot, ctx, a, b)
    a, b, at_end = snap_speech(shot, ctx, a, b, pace, rate)
    cut = Cut(shot, a, b, 0, ctx, [shot.selection_ref], at_end)
    align(cut, rate)
    return cut


# ------------------------------------------------------------------- jump cuts


def is_jump(prev: Cut, nxt: Cut) -> bool:
    if prev.shot.cand.asset_id != nxt.shot.cand.asset_id:
        return False
    gap = round_fraction(JUMP_GAP / prev.tb, Rounding.CEIL)
    overlap = nxt.src_in < prev.src_out and prev.src_in < nxt.src_out
    return overlap or abs(nxt.src_in - prev.src_out) < gap or abs(prev.src_in - nxt.src_out) < gap


def _swap_is_clean(cuts: list[Cut], a: int, b: int) -> bool:
    """Swapping positions ``a`` and ``b`` creates no jump cut around either."""
    trial = list(cuts)
    trial[a], trial[b] = trial[b], trial[a]
    for k in {a - 1, a, b - 1, b}:
        if 0 <= k < len(trial) - 1 and is_jump(trial[k], trial[k + 1]):
            return False
    return True


def fix_jump_cuts(cuts: list[Cut], rate: str, pace: PaceFrames) -> tuple[list[Cut], list[str]]:
    """No adjacent jump cuts: merge into one continuous shot when the two are in order in
    the same shot, else move the next cut away within its beat, else drop the weaker."""
    notes: list[str] = []
    out = list(cuts)
    changed = True
    guard = 0
    while changed and guard < 4 * len(cuts) + 4:
        guard += 1
        changed = False
        for i in range(len(out) - 1):
            prev, nxt = out[i], out[i + 1]
            if not is_jump(prev, nxt):
                continue
            changed = True
            same_shot = prev.shot.cand.shot_id == nxt.shot.cand.shot_id
            span = frames_for_ticks(nxt.src_out - prev.src_in, rate, prev.tb, Rounding.FLOOR)
            limit = max(prev.shot.hi, nxt.shot.hi, pace.max)
            if (
                same_shot
                and nxt.src_in >= prev.src_in
                and nxt.src_out > prev.src_out
                and span <= limit
            ):
                # One continuous take across both segments: its range and speech context
                # are the union of the two.
                prev.ua, prev.ub = min(prev.ua, nxt.ua), max(prev.ub, nxt.ub)
                prev.ctx = ClipContext(
                    words=sorted(set(prev.ctx.words) | set(nxt.ctx.words)),
                    sentences=sorted(set(prev.ctx.sentences) | set(nxt.ctx.sentences)),
                    motion=sorted(set(prev.ctx.motion) | set(nxt.ctx.motion)),
                    best_ticks=prev.ctx.best_ticks,
                )
                prev.src_out = nxt.src_out
                prev.frames = span
                prev.shot.hi = max(prev.shot.hi, span)
                prev.end_at_speech = nxt.end_at_speech
                prev.merged_refs += nxt.merged_refs
                prev.merged_shots += [nxt.shot, *nxt.merged_shots]
                align(prev, rate)
                del out[i + 1]
                notes.append(f"{nxt.shot.cand.ref}: merged into {prev.shot.cand.ref} (same take)")
                break
            swap = next(
                (
                    j
                    for j in range(i + 2, len(out))
                    if out[j].shot.beat_id == nxt.shot.beat_id
                    and out[j].shot.cand.asset_id != prev.shot.cand.asset_id
                    and _swap_is_clean(out, i + 1, j)
                ),
                None,
            )
            if swap is not None:
                out[i + 1], out[swap] = out[swap], out[i + 1]
                notes.append(f"{nxt.shot.cand.ref}: moved to avoid a jump cut")
                break
            weaker = min(
                (c for c in (prev, nxt) if not c.shot.locked and not c.shot.cand.user_use),
                key=lambda c: (c.shot.priority, -c.shot.order),
                default=None,
            )
            if weaker is None:
                changed = False
                notes.append(
                    f"{prev.shot.cand.ref}/{nxt.shot.cand.ref}: jump cut between locked shots"
                )
                continue
            out.remove(weaker)
            notes.append(f"{weaker.shot.cand.ref}: dropped to avoid a jump cut")
            break
    return out, notes


# -------------------------------------------------------------------- backfill


def backfill(
    cuts: list[Cut],
    spares: list[tuple[Shot, ClipContext]],
    target: int,
    tolerance: int,
    pace: PaceFrames,
    rate: str,
    chronological: bool = True,
) -> tuple[list[Cut], list[str]]:
    """While the edit is short, insert spare shots (best first) inside their own beat at a
    position that creates no jump cut, as close to its place in time as possible when the
    edit is chronological. Spares are shots the solver or the jump-cut fixer
    dropped, and the selector's named alternatives."""
    notes: list[str] = []
    out = list(cuts)
    used = {c.shot.cand.segment_id for c in out}
    for shot, ctx in sorted(
        spares, key=lambda sc: (-sc[0].priority, sc[0].beat_index, sc[0].order)
    ):
        if sum(c.frames for c in out) >= target - tolerance:
            break
        if shot.cand.segment_id in used:
            continue
        shot.lo, shot.hi = bounds(shot, pace, rate)
        shot.frames = shot.hi
        if shot.frames < pace.min:
            continue
        cut = refine(shot, ctx, pace, rate)
        beat_positions = [i for i, c in enumerate(out) if c.shot.beat_index == shot.beat_index]
        if beat_positions:
            candidates = range(beat_positions[0], beat_positions[-1] + 2)
        else:
            later = [i for i, c in enumerate(out) if c.shot.beat_index > shot.beat_index]
            candidates = range(
                later[0] if later else len(out), (later[0] if later else len(out)) + 1
            )
        positions = list(candidates)
        if chronological and beat_positions:
            key = shot.cand.sort_key()
            ideal = next(
                (i for i in beat_positions if out[i].shot.cand.sort_key() > key),
                beat_positions[-1] + 1,
            )
            positions.sort(key=lambda p: (abs(p - ideal), p))
        for pos in positions:
            prev = out[pos - 1] if pos > 0 else None
            nxt = out[pos] if pos < len(out) else None
            if (prev and is_jump(prev, cut)) or (nxt and is_jump(cut, nxt)):
                continue
            out.insert(pos, cut)
            used.add(shot.cand.segment_id)
            notes.append(f"{shot.cand.ref}: added to reach the target duration")
            break
    return out, notes


# ------------------------------------------------------------------ final fit


def land_on_target(cuts: list[Cut], target: int, rate: str, pace: PaceFrames) -> int:
    """Move the out points of non-dialogue cuts, one frame at a time, so the total is
    exactly ``target`` where the material allows; a step is refused if it would end inside
    a word, leave the usable range or create a jump cut. Returns the remaining difference."""
    diff = target - sum(c.frames for c in cuts)
    step = 1 if diff > 0 else -1
    progress = True
    while diff != 0 and progress:
        progress = False
        order = sorted(
            (i for i, c in enumerate(cuts) if not c.shot.dialogue and not c.shot.locked),
            key=lambda i: cuts[i].frames if step > 0 else -cuts[i].frames,
        )
        for i in order:
            if diff == 0:
                break
            c = cuts[i]
            n = c.frames + step
            if step < 0 and n < min(pace.min, c.frames):
                continue
            if step > 0 and n > max(c.shot.hi, c.frames):
                continue
            out = c.src_in + ticks_for_frames(n, rate, c.tb, Rounding.CEIL)
            m = margin_ticks(c.tb)
            if out > c.ub or word_at(out, c.ctx.words, m) is not None:
                continue
            old = (c.src_out, c.frames)
            c.src_out, c.frames = out, n
            if (i > 0 and is_jump(cuts[i - 1], c)) or (
                i + 1 < len(cuts) and is_jump(c, cuts[i + 1])
            ):
                c.src_out, c.frames = old
                continue
            diff -= step
            progress = True
    return diff


# ----------------------------------------------------------------------- events


def events(cuts: list[Cut], rate: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    pos = 0
    for i, c in enumerate(cuts, 1):
        s = c.shot
        audio_on = s.audio_intent != "mute"
        out.append(
            {
                "event_id": f"evt_{i:04d}",
                "kind": "video",
                "asset_id": f"ast_{s.cand.asset_id:04d}",
                "segment_id": s.cand.ref,
                "source_in": {"ticks": c.src_in, "tb": s.cand.tb},
                "source_out": {"ticks": c.src_out, "tb": s.cand.tb},
                "timeline_in": {"frames": pos, "rate": rate},
                "timeline_out": {"frames": pos + c.frames, "rate": rate},
                "speed": "1/1",
                "transform": {"crop": None, "reframe": None, "stabilize": False},
                "audio": {
                    "source_enabled": audio_on,
                    "gain_db": GAIN_DB[s.audio_intent],
                    "fade_in_frames": FADE_FRAMES if audio_on else 0,
                    "fade_out_frames": FADE_FRAMES if audio_on else 0,
                    "intent": s.audio_intent,
                },
                "transition_out": {"type": "cut"},
                "role": s.role,
                "beat_id": s.beat_id,
                "origin": {
                    "selection_ref": c.merged_refs[0],
                    "merged": c.merged_refs[1:],
                    "merged_segments": [m.cand.ref for m in c.merged_shots],
                    "locked": s.locked,
                },
            }
        )
        pos += c.frames
    return out
