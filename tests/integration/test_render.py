"""Rendering on the analyzed synthetic corpus (M0 step 11)."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select

from mosaic.core.time import Rounding, parse_rational
from mosaic.devtools.render_check import SourceInfo, check_render
from mosaic.editing.request import EditRequest
from mosaic.editing.service import create_edit, get_version, submit_generate
from mosaic.jobs.executor import LocalExecutor
from mosaic.jobs.store import JobStore
from mosaic.media.ffmpeg.builders import ffprobe_video_pts
from mosaic.media.ffmpeg.capabilities import FFmpegBinaries
from mosaic.media.ffmpeg.run import run
from mosaic.render.plan import samples_for
from mosaic.render.service import create_render, get_render, submit_render
from mosaic.render.tasks import output_path
from mosaic.storage.control import ControlDB
from mosaic.storage.models_project import (
    Artifact,
    Asset,
    AssetFile,
    EditVersion,
    MediaFile,
    MediaStream,
    Segment,
)
from mosaic.storage.projects import Project
from tests.support.runner import run_job

pytestmark = [pytest.mark.integration, pytest.mark.models]


@pytest.fixture(scope="module")
def edit(analyzed_session: Any) -> tuple[Project, ControlDB, int, int]:
    project, control = analyzed_session
    edit_id = create_edit(
        project, EditRequest(duration_s=45, chronology="strict"), control, control.local_principal
    )
    job = submit_generate(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, edit_id
    )
    assert run_job(control, job, timeout=600) == "done"
    return project, control, edit_id, get_version(project, edit_id).version


def _render(
    project: Project,
    control: ControlDB,
    edit_id: int,
    version: int,
    kind: str,
    lossless: bool,
    **options: Any,
) -> int:
    rid = create_render(project, edit_id, version, kind, lossless, **options)
    job = submit_render(LocalExecutor(JobStore(control.db)), control.local_principal, project, rid)
    assert run_job(control, job, timeout=900) == "done"
    return rid


def _sources(project: Project, binaries: FFmpegBinaries, assets: set[int]) -> dict[str, SourceInfo]:
    out = {}
    with project.db.session() as s:
        for aid in assets:
            a = s.get(Asset, aid)
            assert a is not None
            assert a.tb is not None
            pts = None
            if a.vfr:
                rows = list(
                    s.execute(
                        select(MediaFile.rel_path, MediaStream.time_base, MediaStream.start_pts)
                        .join(AssetFile, AssetFile.media_file_id == MediaFile.id)
                        .join(MediaStream, MediaStream.media_file_id == MediaFile.id)
                        .where(
                            AssetFile.asset_id == aid,
                            MediaStream.stream_index == a.video_stream_index,
                        )
                    )
                )
                rel, tb, start = rows[0]
                res = run(
                    binaries, ffprobe_video_pts(project.root / rel, a.video_stream_index or 0)
                )
                ticks = sorted(
                    int(x) for x in res.stdout.decode().split() if x.strip().lstrip("-").isdigit()
                )
                pts = [Fraction(t - start) * parse_rational(tb) for t in ticks]
            out[f"ast_{aid:04d}"] = SourceInfo(
                rate=None if a.vfr else parse_rational(a.rate or "30"),
                pts=pts,
                offset=0,
                display=(a.display_width or 640, a.display_height or 360),
            )
    return out


def _samples(binaries: FFmpegBinaries, path: Any) -> int:
    raw = subprocess.run(
        [
            str(binaries.ffmpeg),
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a",
            "-f",
            "s16le",
            "-ac",
            "2",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return len(raw) // 4


def _frames(binaries: FFmpegBinaries, path: Any) -> int:
    out = subprocess.run(
        [
            str(binaries.ffprobe),
            "-v",
            "error",
            "-count_frames",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=nb_read_frames",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return int(json.loads(out)["streams"][0]["nb_read_frames"])


def test_final_render_is_frame_exact(
    edit: tuple[Project, ControlDB, int, int], ffmpeg_bin: FFmpegBinaries
) -> None:
    project, control, edit_id, version = edit
    v = get_version(project, edit_id, version)
    rid = _render(project, control, edit_id, version, "final", lossless=True)
    r = get_render(project, rid)
    assert r is not None
    assert r.status == "done"
    path = output_path(project.workspace, r)
    total = v.timeline["duration"]["frames"]
    rate = parse_rational(v.rate)
    assert _frames(ffmpeg_bin, path) == total
    assert _samples(ffmpeg_bin, path) == samples_for(total, rate)
    assert r.metrics["true_peak_dbtp"] is not None  # the corpus edit has audio
    assert r.metrics["true_peak_dbtp"] <= -1.0
    if r.metrics["normalized"]:
        assert abs(r.metrics["loudness_lufs"] - (-14.0)) <= 1.0
    events = v.timeline["tracks"][0]["events"]
    assets = {int(e["asset_id"][4:]) for e in events}
    checks = check_render(ffmpeg_bin, path, v.timeline, _sources(project, ffmpeg_bin, assets))
    bad = [(c.event_id, c.asset_id, c.decoded, c.frames, c.errors) for c in checks if not c.ok]
    assert not bad, bad


def test_preview_and_chunk_reuse(
    edit: tuple[Project, ControlDB, int, int], ffmpeg_bin: FFmpegBinaries
) -> None:
    project, control, edit_id, version = edit
    v = get_version(project, edit_id, version)
    rid = _render(project, control, edit_id, version, "preview", lossless=False)
    r = get_render(project, rid)
    assert r is not None
    path = output_path(project.workspace, r)
    assert path.suffix == ".mp4"
    assert _frames(ffmpeg_bin, path) == v.timeline["duration"]["frames"]
    # Constant frame rate on the exact timeline grid; true peak within the limit after AAC.
    from mosaic.media.ffmpeg.builders import ffprobe_stream_counts

    streams = json.loads(run(ffmpeg_bin, ffprobe_stream_counts(path)).stdout)["streams"]
    video = next(st for st in streams if st["codec_type"] == "video")
    assert parse_rational(video["avg_frame_rate"]) == parse_rational(v.rate)
    # Decoded AAC length (container durations include priming; M0 eval finding).
    from mosaic.render.plan import samples_for
    from mosaic.render.tasks import decoded_samples

    expected = samples_for(v.timeline["duration"]["frames"], parse_rational(v.rate))
    assert abs(decoded_samples(ffmpeg_bin, path) - expected) <= 1024
    assert r.metrics["true_peak_dbtp"] is not None
    assert r.metrics["true_peak_dbtp"] <= -1.0
    with project.db.session() as s:
        before = s.query(Artifact).filter(Artifact.kind == "chunk").count()
    _render(project, control, edit_id, version, "preview", lossless=False)
    with project.db.session() as s:
        after = s.query(Artifact).filter(Artifact.kind == "chunk").count()
    assert after == before, "an unchanged event's chunk is reused"


def test_render_api(edit: tuple[Project, ControlDB, int, int]) -> None:
    from fastapi.testclient import TestClient

    from mosaic.app.main import create_app
    from mosaic.app.services import Services
    from mosaic.storage.models_project import Edit

    project, control, edit_id, _ = edit
    app = create_app(Services.create(control))
    app.state.allowed_hosts = {"testserver"}
    client = TestClient(app)
    with project.db.session() as s:
        e = s.get(Edit, edit_id)
        assert e is not None
        uid = e.uid
    started = client.post(f"/api/edits/{uid}/preview")
    assert started.status_code == 202
    assert run_job(control, started.json()["job_id"], timeout=900) == "done"
    items = client.get(f"/api/projects/{project.id}/renders").json()["items"]
    mine = next(i for i in items if i["render_id"] == started.json()["render_id"])
    assert mine["status"] == "done"
    assert "-preview-r" in mine["file"]
    assert mine["file"].endswith(".mp4")
    assert mine["label"] == "Preview · 720p"
    assert mine["size_bytes"] > 0
    assert mine["seconds"] is not None
    rid = mine["render_id"]
    assert mine["cover_sample_id"] is not None
    # S17 finds the version's renders on the edit itself.
    on_edit = client.get(f"/api/edits/{uid}/versions/{mine['version']}").json()["renders"]
    assert rid in [r["render_id"] for r in on_edit]
    assert all(r["version"] == mine["version"] for r in on_edit)
    assert all(r["edit_id"] == uid for r in on_edit), "another edit's renders stay out"
    base = f"/api/projects/{project.id}/renders/{rid}"
    # The S17 player seeks with Range requests.
    part = client.get(f"{base}/file", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206
    assert len(part.content) == 100
    assert part.headers["content-type"] == "video/mp4"
    got = client.get(f"{base}/file?download=true")
    assert "attachment" in got.headers["content-disposition"]
    assert client.post(f"{base}/cancel").status_code == 409, "a finished render"
    assert client.post(f"{base}/explode").status_code == 404
    again = client.post(f"{base}/rerender")
    assert again.status_code == 202
    assert run_job(control, again.json()["job_id"], timeout=900) == "done"
    assert client.delete(f"{base}/file").status_code == 200
    assert client.get(f"{base}/file").status_code == 404
    rows = client.get(f"/api/projects/{project.id}/renders").json()["items"]
    assert next(i for i in rows if i["render_id"] == rid)["status"] == "deleted"
    assert next(i for i in rows if i["render_id"] == again.json()["render_id"])["status"] == "done"
    assert client.delete(f"{base}/file").status_code == 409
    assert client.get(f"/api/projects/{project.id}/renders/99999/file").status_code == 404
    # A queued render (no worker runs here) is cancelled, its job too.
    queued = client.post(f"/api/edits/{uid}/preview").json()
    row = next(
        i
        for i in client.get(f"/api/projects/{project.id}/renders").json()["items"]
        if i["render_id"] == queued["render_id"]
    )
    assert row["status"] == "queued"
    cancel = f"/api/projects/{project.id}/renders/{queued['render_id']}/cancel"
    assert client.post(cancel).status_code == 202
    assert client.get(f"/api/jobs/{queued['job_id']}").json()["state"] == "cancelled"
    rows = client.get(f"/api/projects/{project.id}/renders").json()["items"]
    assert next(i for i in rows if i["render_id"] == queued["render_id"])["status"] == "cancelled"
    assert client.post(cancel).status_code == 409
    assert client.post("/api/renders", json={"edit_id": uid, "version": "x"}).status_code == 422
    assert client.post("/api/renders", json={"edit_id": "nope"}).status_code == 404


def test_a_vertical_edit_renders_vertical_with_the_same_plan(
    edit: tuple[Project, ControlDB, int, int], ffmpeg_bin: FFmpegBinaries
) -> None:
    """ADR 0046: aspect is render-only. The 9:16 edit plans exactly like the 16:9 one (no
    new AI call), and its preview is 720 × 1280, frame-exact."""
    from mosaic.ai.adapters.fake import adapter as fake

    project, control, edit_id, version = edit
    before = len(fake.CALLS)
    vertical = create_edit(
        project,
        EditRequest(duration_s=45, chronology="strict", aspect="9:16"),
        control,
        control.local_principal,
    )
    job = submit_generate(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, vertical
    )
    assert run_job(control, job, timeout=600) == "done"
    assert len(fake.CALLS) == before, "the same plan: no AI call"
    v = get_version(project, vertical)
    landscape = get_version(project, edit_id, version)
    assert v.timeline["tracks"] == landscape.timeline["tracks"]
    rid = _render(project, control, vertical, v.version, "preview", lossless=False)
    r = get_render(project, rid)
    assert r is not None
    path = output_path(project.workspace, r)
    from mosaic.media.ffmpeg.builders import ffprobe_json

    streams = json.loads(run(ffmpeg_bin, ffprobe_json(path)).stdout)["streams"]
    video = next(st for st in streams if st["codec_type"] == "video")
    assert (video["width"], video["height"]) == (720, 1280)
    assert _frames(ffmpeg_bin, path) == v.timeline["duration"]["frames"]


@pytest.mark.parametrize("when", ["before", "while_assembling", "while_reusing"])
def test_a_cancelled_render_keeps_no_file(
    edit: tuple[Project, ControlDB, int, int], monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    """ADR 0047: a render cancelled from S20 before or while it is assembled ends with no
    output file and stays cancelled (the race between Cancel and the assembler)."""
    from mosaic.render import tasks
    from mosaic.storage.models_project import Render

    project, control, edit_id, version = edit
    rid = create_render(project, edit_id, version, "preview")

    def cancel() -> None:
        with project.write() as s:
            row = s.get(Render, rid)
            assert row is not None
            row.status = "cancelled"

    if when == "while_reusing":  # an identical earlier render is linked, then Cancel
        _render(project, control, edit_id, version, "preview", lossless=False)
        found = tasks._same_render

        def found_then_cancel(*args: Any) -> Any:
            earlier = found(*args)
            assert earlier is not None, "the earlier preview is reused"
            cancel()
            return earlier

        monkeypatch.setattr(tasks, "_same_render", found_then_cancel)
    else:  # the race is with the assembler: never reuse an earlier preview
        monkeypatch.setattr(tasks, "_same_render", lambda *a: None)
    if when == "before":
        cancel()
    else:
        measure = tasks.parse_ebur128  # runs after the concat wrote the file

        def cancel_then_measure(text: str) -> Any:
            cancel()
            return measure(text)

        monkeypatch.setattr(tasks, "parse_ebur128", cancel_then_measure)
    job = submit_render(LocalExecutor(JobStore(control.db)), control.local_principal, project, rid)
    assert run_job(control, job, timeout=900) == "done"
    r = get_render(project, rid)
    assert r is not None
    assert r.status == "cancelled"
    assert r.path is None
    out = output_path(project.workspace, r)
    assert not out.exists()
    assert not out.with_suffix(".concat.txt").exists()
    assert [p for p in out.parent.glob(f"*r{rid:04d}*")] == []


def test_a_photo_renders_as_a_still_with_no_orientation_artifact(
    analyzed_session: Any, ffmpeg_bin: FFmpegBinaries
) -> None:
    """M4 acceptance 4 (ADR 0075): a photo-heavy edit mixes stills and video. The
    corpus's photo is stored landscape with an EXIF rotation; on a 16:9 edit it shows
    upright and whole, on a blurred fill, never stretched or sideways."""
    import numpy as np

    from mosaic.editing.draft import LockShot
    from mosaic.editing.service import change_draft, save_draft

    project, control = analyzed_session
    edit_id = create_edit(
        project, EditRequest(duration_s=20, photo_share="many"), control, control.local_principal
    )
    job = submit_generate(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, edit_id
    )
    assert run_job(control, job, timeout=600) == "done"
    v = get_version(project, edit_id)
    with project.db.session() as s:  # the corpus's one photo; its id depends on scan order
        seg = s.scalars(
            select(Segment.id)
            .join(Asset, Segment.asset_id == Asset.id)
            .where(Asset.kind == "photo")
        ).one()
    photo = next(
        ref
        for ref, sel in v.timeline["selections"].items()
        if sel["segment_id"] == f"seg_{seg:06d}"
    )
    change_draft(project, edit_id, "op", LockShot(ref=photo))  # kept, however short the edit
    version = save_draft(project, edit_id)
    assert version is not None
    v = get_version(project, edit_id, version)
    events = v.timeline["tracks"][0]["events"]
    still = next(e for e in events if e["kind"] == "still")
    assert {e["kind"] for e in events} == {"video", "still"}
    rid = _render(project, control, edit_id, version, "preview", lossless=False)
    r = get_render(project, rid)
    assert r is not None
    path = output_path(project.workspace, r)
    total = v.timeline["duration"]["frames"]
    assert _frames(ffmpeg_bin, path) == total
    videos = {int(e["asset_id"][4:]) for e in events if e["kind"] == "video"}
    checks = check_render(ffmpeg_bin, path, v.timeline, _sources(project, ffmpeg_bin, videos))
    assert all(c.ok for c in checks), [(c.event_id, c.decoded, c.frames) for c in checks]
    # The still's middle frame: a sharp portrait in the middle, a soft fill at the sides.
    middle = (still["timeline_in"]["frames"] + still["timeline_out"]["frames"]) // 2
    w, h = r.profile["width"], r.profile["height"]
    frame = None
    for n, data in enumerate(stream_frames(ffmpeg_bin, path, w, h)):
        if n == middle:
            frame = data
            break
    assert frame is not None

    def detail(region: np.ndarray) -> float:
        return float(np.abs(np.diff(region.astype(np.int32), axis=1)).mean())

    centre = frame[:, w * 2 // 5 : w * 3 // 5]
    sides = np.concatenate([frame[:, : w // 10], frame[:, -w // 10 :]], axis=1)
    assert detail(centre) > 4 * detail(sides), (detail(centre), detail(sides))


def stream_frames(ffmpeg_bin: FFmpegBinaries, path: Any, w: int, h: int) -> Any:
    """Gray frames of a render at its own size, one at a time."""
    import numpy as np

    from mosaic.media.ffmpeg.builders import raw_frames
    from mosaic.media.ffmpeg.run import stream_stdout

    for data in stream_stdout(ffmpeg_bin, raw_frames(path, w, h, "gray"), w * h):
        yield np.frombuffer(data, dtype=np.uint8).reshape(h, w)


def test_a_crop_to_another_shape_keeps_the_subject_in_frame(
    ffmpeg_bin: FFmpegBinaries, tmp_path: Any
) -> None:
    """ADR 0076: a 9:16 crop of a 16:9 clip whose subject is near its left edge keeps the
    subject with its focus, and loses it centred; the crop never leaves the picture."""
    import numpy as np

    from mosaic.media.ffmpeg import render as rb

    src = tmp_path / "left_subject.mp4"
    from mosaic.media.ffmpeg.command import (
        FFmpegCommand,
        Filter,
        InputSpec,
        OutputSpec,
        chain,
        media_path,
    )

    run(
        ffmpeg_bin,
        FFmpegCommand(
            inputs=[InputSpec("color=c=0x203040:s=1280x720:d=1:r=30", [("-f", "lavfi")])],
            outputs=[
                OutputSpec(
                    media_path(src),
                    [
                        (
                            "-vf",
                            chain(
                                Filter.of(
                                    "drawbox", x=90, y=310, w=100, h=100, color="white", t="fill"
                                )
                            ),
                        ),
                        ("-c:v", "ffv1"),
                        ("-pix_fmt", "yuv420p"),
                    ],
                )
            ],
            description="a clip with its subject near the left edge",
        ),
    )

    def render(focus: tuple[int, int] | None) -> np.ndarray:
        out = tmp_path / f"crop_{focus}.mov"
        spec = rb.ChunkSpec(
            pieces=[rb.Piece(src, Fraction(0), Fraction(1, 3), Fraction(0))],
            video_index=0,
            audio_index=None,
            audio_enabled=False,
            gain_db=0,
            fade_in=Fraction(0),
            fade_out=Fraction(0),
            width=360,
            height=640,
            rate=Fraction(30),
            frames=10,
            samples=samples_for(10, Fraction(30)),
            hdr=None,
            full_range=False,
            encoder="ffv1",
            bitrate="5M",
            out=out,
            source_rate=Fraction(30),
            framing="crop",
            focus=focus,
        )
        run(ffmpeg_bin, rb.chunk(spec))
        assert _frames(ffmpeg_bin, out) == 10
        frame = next(stream_frames(ffmpeg_bin, out, 360, 640))
        return frame

    def subject_seen(frame: np.ndarray) -> bool:
        return bool((frame > 200).mean() > 0.01)

    assert subject_seen(render((110, 500))), "focused on the subject: it stays in"
    assert not subject_seen(render(None)), "centred: the left-edge subject is cut away"
    assert subject_seen(render((0, 0))), "clamped at the left edge, still the right size"
    assert not subject_seen(render((1000, 1000))), "clamped at the right edge"


def test_an_l_cut_plays_the_sound_on_under_the_next_picture(
    edit: tuple[Project, ControlDB, int, int], ffmpeg_bin: FFmpegBinaries
) -> None:
    """ADR 0077: a version whose events carry their own audio windows renders the sound
    from separate audio chunks. With an L-cut, the first shot's tone runs on under the
    second picture, then the second shot's tone takes over; length and samples exact."""
    import copy

    import numpy as np

    from mosaic.editing.refiner import ticks_for_frames
    from mosaic.media.ffmpeg.builders import audio_pcm

    project, control, edit_id, version = edit
    v = get_version(project, edit_id, version)
    rate = parse_rational(v.rate)
    k = 20
    sr = 8000

    def pcm(path: Any) -> np.ndarray:
        raw = run(ffmpeg_bin, audio_pcm(path, sr, 1)).stdout
        return np.frombuffer(raw, dtype="<f4")

    def tone(x: np.ndarray, a: int, b: int) -> float:
        seg = x[round(a / rate * sr) : round(b / rate * sr)]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg)), n=8 * len(seg)))
        return float(np.argmax(spec[8:]) + 8) * sr / (8 * len(seg))

    base = get_render(project, _render(project, control, edit_id, version, "final", True))
    assert base is not None
    plain = pcm(output_path(project.workspace, base))
    events = v.timeline["tracks"][0]["events"]
    pair = next(
        i
        for i in range(len(events) - 1)
        if all(
            e["kind"] == "video"
            and e["audio"]["source_enabled"]
            and e["timeline_out"]["frames"] - e["timeline_in"]["frames"] > 3 * k
            for e in events[i : i + 2]
        )
        and abs(
            tone(
                plain,
                events[i]["timeline_out"]["frames"] - 2 * k,
                events[i]["timeline_out"]["frames"] - 2,
            )
            - tone(
                plain,
                events[i + 1]["timeline_in"]["frames"] + k + 2,
                events[i + 1]["timeline_in"]["frames"] + 2 * k + 2,
            )
        )
        > 40
    )
    a, b = events[pair], events[pair + 1]
    cut = b["timeline_in"]["frames"]
    tl = copy.deepcopy(v.timeline)
    ea, eb = tl["tracks"][0]["events"][pair : pair + 2]
    tb = parse_rational(a["source_in"]["tb"])
    shift_a = ticks_for_frames(k, v.rate, tb, Rounding.CEIL)
    shift_b = ticks_for_frames(k, v.rate, parse_rational(b["source_in"]["tb"]), Rounding.CEIL)
    ea["audio"] |= {
        "source_in": a["source_in"],
        "source_out": {"ticks": a["source_out"]["ticks"] + shift_a, "tb": a["source_in"]["tb"]},
        "timeline_in": a["timeline_in"],
        "timeline_out": {"frames": cut + k, "rate": v.rate},
    }
    eb["audio"] |= {
        "source_in": {"ticks": b["source_in"]["ticks"] + shift_b, "tb": b["source_in"]["tb"]},
        "source_out": b["source_out"],
        "timeline_in": {"frames": cut + k, "rate": v.rate},
        "timeline_out": b["timeline_out"],
    }
    with project.write() as s:
        row = s.scalar(
            select(EditVersion).where(
                EditVersion.edit_id == edit_id, EditVersion.version == version
            )
        )
        assert row is not None
        top = max(s.scalars(select(EditVersion.version).where(EditVersion.edit_id == edit_id)))
        split = EditVersion(
            edit_id=edit_id,
            version=top + 1,
            parent_version=version,
            creator="user",
            reason="L-cut test",
            key=row.key + "-split",
            request=row.request,
            rate=row.rate,
            beats=row.beats,
            timeline=tl,
            metrics=row.metrics,
            findings=row.findings,
            provenance_id=row.provenance_id,
            created_at=row.created_at,
        )
        s.add(split)
        s.flush()
        new = split.version
    r = get_render(project, _render(project, control, edit_id, new, "final", True))
    assert r is not None
    path = output_path(project.workspace, r)
    total = v.timeline["duration"]["frames"]
    assert _frames(ffmpeg_bin, path) == total
    assert _samples(ffmpeg_bin, path) == samples_for(total, rate)
    heard = pcm(path)
    first = tone(plain, cut - 2 * k, cut - 2)
    second = tone(plain, cut + k + 2, cut + 2 * k + 2)
    assert abs(tone(heard, cut + 2, cut + k - 2) - first) < 15, "the first tone runs on"
    assert abs(tone(heard, cut + k + 2, cut + 2 * k + 2) - second) < 15
    # Everything away from the split sounds as before.
    assert abs(tone(heard, cut - 2 * k, cut - 2) - first) < 15


def test_a_dissolve_renders_frame_exact_between_two_shots(
    edit: tuple[Project, ControlDB, int, int], ffmpeg_bin: FFmpegBinaries
) -> None:
    """ADR 0078: a dissolve renders as its own chunk between the two pictures, each half
    a dissolve shorter. The render keeps its exact frames and samples, every frame
    outside a blend shows its source frame, and the dissolve's middle frame mixes the
    frames either side. (The corpus clips are used almost whole, so the edit itself has
    no handles to dissolve over; this version adds one where the files have them.)"""
    import copy

    import numpy as np

    from mosaic.editing.refiner import ticks_for_frames

    project, control, edit_id, version = edit
    v = get_version(project, edit_id, version)
    n, half = 14, 7
    events = v.timeline["tracks"][0]["events"]
    with project.db.session() as s:
        length = {
            f"ast_{a.id:04d}": a.duration_ticks or 0
            for a in s.scalars(select(Asset).where(Asset.kind == "video"))
        }

    def handles(a: dict[str, Any], b: dict[str, Any]) -> bool:
        t_a = ticks_for_frames(half, v.rate, parse_rational(a["source_in"]["tb"]), Rounding.CEIL)
        t_b = ticks_for_frames(half, v.rate, parse_rational(b["source_in"]["tb"]), Rounding.CEIL)
        return (
            a["kind"] == b["kind"] == "video"
            and a["asset_id"] != b["asset_id"]
            and a["source_out"]["ticks"] + t_a <= length[a["asset_id"]]
            and b["source_in"]["ticks"] - t_b >= 0
            and min(
                a["timeline_out"]["frames"] - a["timeline_in"]["frames"],
                b["timeline_out"]["frames"] - b["timeline_in"]["frames"],
            )
            > 3 * n
        )

    pair = next(i for i in range(1, len(events) - 2) if handles(events[i], events[i + 1]))
    tl = copy.deepcopy(v.timeline)
    tl["tracks"][0]["events"][pair]["transition_out"] = {
        "type": "dissolve",
        "frames": n,
        "rate": v.rate,
    }
    with project.write() as s:
        row = s.scalar(
            select(EditVersion).where(
                EditVersion.edit_id == edit_id, EditVersion.version == version
            )
        )
        assert row is not None
        top = max(s.scalars(select(EditVersion.version).where(EditVersion.edit_id == edit_id)))
        dissolved = EditVersion(
            edit_id=edit_id,
            version=top + 1,
            parent_version=version,
            creator="user",
            reason="dissolve test",
            key=row.key + "-dissolve",
            request=row.request,
            rate=row.rate,
            beats=row.beats,
            timeline=tl,
            metrics=row.metrics,
            findings=row.findings,
            provenance_id=row.provenance_id,
            created_at=row.created_at,
        )
        s.add(dissolved)
        s.flush()
        new = dissolved.version
    r = get_render(project, _render(project, control, edit_id, new, "final", True))
    assert r is not None
    path = output_path(project.workspace, r)
    total = tl["duration"]["frames"]
    rate = parse_rational(v.rate)
    assert _frames(ffmpeg_bin, path) == total
    assert _samples(ffmpeg_bin, path) == samples_for(total, rate)
    videos = {int(e["asset_id"][4:]) for e in tl["tracks"][0]["events"] if e["kind"] == "video"}
    checks = check_render(ffmpeg_bin, path, tl, _sources(project, ffmpeg_bin, videos))
    assert all(c.ok for c in checks), [(c.event_id, c.decoded, c.frames, c.blended) for c in checks]
    assert checks[pair].blended == half
    assert checks[pair + 1].blended == half
    # Its middle frame: half the outgoing shot just past its cut, half the incoming
    # shot's first frame - closer to their mix than to either. The plain render of the
    # same version shows the frames on either side of the cut.
    cut = events[pair]["timeline_out"]["frames"]
    w, h = r.profile["width"], r.profile["height"]
    plain = get_render(project, _render(project, control, edit_id, version, "final", True))
    assert plain is not None

    def at(file: Any, wanted: set[int]) -> dict[int, np.ndarray]:
        got = {}
        for k, data in enumerate(stream_frames(ffmpeg_bin, file, w, h)):
            if k in wanted:
                got[k] = data.astype(np.float64)
            if k >= max(wanted):
                break
        return got

    middle = at(path, {cut})[cut]
    sides = at(output_path(project.workspace, plain), {cut - 1, cut})
    out_going, in_coming = sides[cut - 1], sides[cut]

    def far(x: np.ndarray, y: np.ndarray) -> float:
        return float(np.abs(x - y).mean())

    assert far(out_going, in_coming) > 5, "two different pictures"
    mix = far(middle, (out_going + in_coming) / 2)
    assert mix < far(middle, out_going)
    assert mix < far(middle, in_coming)


def test_title_cards_open_and_close_the_edit_and_render_frame_exact(
    analyzed_session: Any, ffmpeg_bin: FFmpegBinaries
) -> None:
    """ADR 0079: with a trip name in the trip context, the edit opens on a card with the
    name (over the footage's dates, when they are known) and closes on the name. Cards
    fade in from and out to black, render to their exact frames and are part of the
    edit's length."""

    from mosaic.library import context

    project, control = analyzed_session
    with project.write() as s:
        before = context.load(s)
        context.save(s, before.model_copy(update={"trip_name": "Corpus trip"}), "user")
    try:
        edit_id = create_edit(
            project,
            EditRequest(duration_s=45, chronology="strict"),
            control,
            control.local_principal,
        )
        job = submit_generate(
            LocalExecutor(JobStore(control.db)), control.local_principal, project, edit_id
        )
        assert run_job(control, job, timeout=600) == "done"
    finally:
        with project.write() as s:
            context.save(s, before, "user")
    v = get_version(project, edit_id)
    events = v.timeline["tracks"][0]["events"]
    opening, closing = events[0], events[-1]
    assert opening["kind"] == closing["kind"] == "title"
    assert opening["title"]["title"] == "Corpus trip"
    # The synthetic corpus has no capture dates, so no date line (the unit tests cover it).
    assert v.metrics["days_used"] == []
    assert opening["title"]["subtitle"] == ""
    assert closing["title"]["title"] == "Corpus trip"
    rate = parse_rational(v.rate)
    total = v.timeline["duration"]["frames"]
    assert abs(total - round(45 * rate)) <= v.metrics["tolerance_frames"]
    assert v.metrics["titles"] == {"cards": 2, "frames": 180}
    r = get_render(project, _render(project, control, edit_id, v.version, "final", True))
    assert r is not None
    path = output_path(project.workspace, r)
    assert _frames(ffmpeg_bin, path) == total
    assert _samples(ffmpeg_bin, path) == samples_for(total, rate)
    w, h = r.profile["width"], r.profile["height"]
    frames = {}
    for k, data in enumerate(stream_frames(ffmpeg_bin, path, w, h)):
        if k in (0, 45):
            frames[k] = data
        if k >= 45:
            break
    assert frames[0].max() < 40, "the card fades in from black"
    card = frames[45]
    assert card[: h // 4].max() < 30, "a dark ground"
    assert card[h // 3 : 2 * h // 3].max() > 200, "the name, drawn in the middle"

    # With a J- or L-cut anywhere the sound comes from audio chunks (ADR 0077): a card
    # is heard as silence for its length (found by the M4 eval, where a cut edit with
    # cards failed to render).
    import copy

    tl = copy.deepcopy(v.timeline)
    shot = next(e for e in tl["tracks"][0]["events"] if e["kind"] == "video")
    shot["audio"] |= {
        k: shot[k] for k in ("source_in", "source_out", "timeline_in", "timeline_out")
    }
    with project.write() as s:
        row = s.scalar(
            select(EditVersion).where(
                EditVersion.edit_id == edit_id, EditVersion.version == v.version
            )
        )
        assert row is not None
        s.add(
            EditVersion(
                edit_id=edit_id,
                version=v.version + 1,
                parent_version=v.version,
                creator="user",
                reason="split sound with cards",
                key=row.key + "-split",
                request=row.request,
                rate=row.rate,
                beats=row.beats,
                timeline=tl,
                metrics=row.metrics,
                findings=row.findings,
                provenance_id=row.provenance_id,
                created_at=row.created_at,
            )
        )
    split = get_render(project, _render(project, control, edit_id, v.version + 1, "final", True))
    assert split is not None
    out = output_path(project.workspace, split)
    assert _frames(ffmpeg_bin, out) == total
    assert _samples(ffmpeg_bin, out) == samples_for(total, rate)


def test_a_music_bed_plays_under_the_edit_and_ducks_under_dialogue(
    edit: tuple[Project, ControlDB, int, int], ffmpeg_bin: FFmpegBinaries, tmp_path: Any
) -> None:
    """ADR 0080: a 1 kHz track, shorter than the edit, loops under it at its level and
    drops by about 12 dB while the edit plays dialogue. Frames and samples stay exact."""
    import copy

    import numpy as np

    from mosaic.media.ffmpeg.builders import audio_pcm
    from mosaic.media.ffmpeg.command import FFmpegCommand, InputSpec, OutputSpec, media_path

    project, control, edit_id, version = edit
    track = tmp_path / "tone.wav"
    run(
        ffmpeg_bin,
        FFmpegCommand(
            inputs=[
                InputSpec("sine=frequency=1000:sample_rate=48000:duration=7", [("-f", "lavfi")])
            ],
            outputs=[OutputSpec(media_path(track), [("-ac", 2), ("-c:a", "pcm_s16le")])],
            description="a 1 kHz music track",
        ),
    )
    v = get_version(project, edit_id, version)
    rate = parse_rational(v.rate)
    tl = copy.deepcopy(v.timeline)
    events = tl["tracks"][0]["events"]
    talk = next(
        i
        for i, e in enumerate(events)
        if e["kind"] == "video"
        and e["timeline_in"]["frames"] > 120
        and e["timeline_out"]["frames"] - e["timeline_in"]["frames"] > 90
        and e["timeline_out"]["frames"] < tl["duration"]["frames"] - 180
    )
    for e in events:  # one dialogue window only: the "outside" window never ducks
        if e["audio"].get("intent") == "dialogue":
            e["audio"]["intent"] = "natural_sound"
    events[talk]["audio"] |= {"intent": "dialogue", "source_enabled": True}
    request = v.request | {
        "music": {"path": str(track), "level_db": -12, "fade_in_ms": 500, "fade_out_ms": 500}
    }
    with project.write() as s:
        row = s.scalar(
            select(EditVersion).where(
                EditVersion.edit_id == edit_id, EditVersion.version == version
            )
        )
        assert row is not None
        top = max(s.scalars(select(EditVersion.version).where(EditVersion.edit_id == edit_id)))
        scored = EditVersion(
            edit_id=edit_id,
            version=top + 1,
            parent_version=version,
            creator="user",
            reason="music test",
            key=row.key + "-music",
            request=request,
            rate=row.rate,
            beats=row.beats,
            timeline=tl,
            metrics=row.metrics,
            findings=row.findings,
            provenance_id=row.provenance_id,
            created_at=row.created_at,
        )
        s.add(scored)
        s.flush()
        new = scored.version
    r = get_render(project, _render(project, control, edit_id, new, "final", True))
    assert r is not None
    path = output_path(project.workspace, r)
    total = tl["duration"]["frames"]
    assert _frames(ffmpeg_bin, path) == total
    assert _samples(ffmpeg_bin, path) == samples_for(total, rate)
    plain = get_render(project, _render(project, control, edit_id, version, "final", True))
    assert plain is not None
    sr = 8000

    def pcm(file: Any) -> np.ndarray:
        return np.frombuffer(run(ffmpeg_bin, audio_pcm(file, sr, 1)).stdout, dtype="<f4")

    def at_1k(x: np.ndarray, a: int, b: int) -> float:
        seg = x[round(a / rate * sr) : round(b / rate * sr)]
        spec = np.abs(np.fft.rfft(seg * np.hanning(len(seg))))
        freqs = np.fft.rfftfreq(len(seg), 1 / sr)
        return float(spec[(freqs > 980) & (freqs < 1020)].max())

    a, b = events[talk]["timeline_in"]["frames"], events[talk]["timeline_out"]["frames"]
    inside = (a + 15, b - 15)
    outside = (60, a - 30) if a - 30 - 60 > 30 else (b + 30, b + 90)
    heard, without = pcm(path), pcm(output_path(project.workspace, plain))
    assert at_1k(heard, *outside) > 20 * at_1k(without, *outside), "the music plays"
    # After loudness normalization (which may adapt its gain over time) the duck is
    # still clearly there; the mixer's own depth is checked exactly below.
    drop = 20 * np.log10(at_1k(heard, *inside) / at_1k(heard, *outside))
    assert -20 < drop < -8, drop


def test_the_music_mixer_ducks_exactly_twelve_db(ffmpeg_bin: FFmpegBinaries, tmp_path: Any) -> None:
    """ADR 0080: over a silent edit, a 1 kHz track sits at its level, drops by exactly
    12 dB inside a speech window and comes back after it; the mix is sample exact."""
    import numpy as np

    from mosaic.media.ffmpeg import render as rb
    from mosaic.media.ffmpeg.builders import audio_pcm
    from mosaic.media.ffmpeg.command import FFmpegCommand, InputSpec, OutputSpec, media_path

    def make(name: str, source: str) -> Any:
        out = tmp_path / name
        run(
            ffmpeg_bin,
            FFmpegCommand(
                inputs=[InputSpec(source, [("-f", "lavfi")])],
                outputs=[OutputSpec(media_path(out), [("-ac", 2), ("-c:a", "pcm_s16le")])],
                description=name,
            ),
        )
        return out

    from mosaic.render.tasks import _has_audio

    silent = make("edit.wav", "anullsrc=r=48000:cl=stereo:d=10")
    tone = make("tone.wav", "sine=frequency=1000:sample_rate=48000:duration=3")
    assert _has_audio(ffmpeg_bin, tone)
    (tmp_path / "notes.mp3").write_text("not audio")
    assert not _has_audio(ffmpeg_bin, tmp_path / "notes.mp3"), "refused with a plain message"
    mix = tmp_path / "mix.mov"
    run(
        ffmpeg_bin,
        rb.music_mix(
            rb.MusicSpec(
                audio=silent,
                audio_concat=False,
                music=tone,
                samples=480000,
                level_db=-6,
                fade_in=Fraction(0),
                fade_out=Fraction(0),
                duck=[(Fraction(4), Fraction(6))],
                duck_db=-12,
                ramp=Fraction(1, 4),
                out=mix,
            )
        ),
    )
    x = np.frombuffer(run(ffmpeg_bin, audio_pcm(mix, 48000, 1)).stdout, dtype="<f4")
    assert len(x) == 480000, "exact samples, the 3 s track looped"

    def rms(a: float, b: float) -> float:
        return float(np.sqrt(np.mean(x[int(a * 48000) : int(b * 48000)] ** 2)))

    # lavfi's sine has a peak of 1/8 (-18 dBFS); at -6 dB it peaks at -24 dBFS. A sine's
    # peak is √2 × its RMS.
    level = 20 * np.log10(rms(1, 3) * np.sqrt(2))
    assert abs(level - -24) < 0.5, level
    assert abs(20 * np.log10(rms(4.5, 5.5) / rms(1, 3)) - -12) < 0.3
    assert abs(20 * np.log10(rms(7, 9) / rms(1, 3))) < 0.3, "back up after the speech"
    assert abs(20 * np.log10(rms(3.3, 3.6) / rms(1, 3))) < 0.3, "the loop has no gap"


def test_reverting_to_v1_after_five_versions_renders_the_same_file(
    analyzed_session: Any, ffmpeg_bin: FFmpegBinaries
) -> None:
    """M4 acceptance 5 (ADR 0083): reverting to v1 after five versions makes v6 equal to
    v1; its render reuses every chunk (the same keys, none rendered again) and, its
    assembly key matching v1's render, is byte for byte the same file."""
    import hashlib

    from mosaic.editing import versions
    from mosaic.editing.service import set_duration
    from mosaic.storage.models_project import Artifact as ArtifactRow

    project, control = analyzed_session
    edit_id = create_edit(
        project, EditRequest(duration_s=30, variant=41), control, control.local_principal
    )
    job = submit_generate(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, edit_id
    )
    assert run_job(control, job, timeout=600) == "done"
    first = get_render(project, _render(project, control, edit_id, 1, "final", True))
    assert first is not None
    for seconds in (26, 34, 28, 32):  # v2..v5, each a different cut
        assert set_duration(project, edit_id, seconds) is not None
    assert get_version(project, edit_id).version == 5
    assert versions.compare(project, edit_id, 1, 5)["changes"], "v5 is another cut"
    v6 = versions.revert(project, edit_id, 1)
    assert v6 == 6
    same = versions.compare(project, edit_id, 1, 6)
    assert same["same"]
    assert same["changes"] == []
    with project.db.session() as s:
        chunks_before = s.scalar(
            select(func.count(ArtifactRow.key)).where(ArtifactRow.kind == "chunk")
        )
    again = get_render(project, _render(project, control, edit_id, 6, "final", True))
    assert again is not None
    with project.db.session() as s:
        assert (
            s.scalar(select(func.count(ArtifactRow.key)).where(ArtifactRow.kind == "chunk"))
            == chunks_before
        ), "no chunk rendered"
    assert again.metrics["assembly_key"] == first.metrics["assembly_key"]
    assert again.metrics["reused_from"] == first.id

    def digest(r: Any) -> str:
        return hashlib.sha256(output_path(project.workspace, r).read_bytes()).hexdigest()

    assert digest(again) == digest(first), "the same file"
    with pytest.raises(versions.RevertError):
        versions.revert(project, edit_id, 6)


def _video_stream(ffmpeg_bin: FFmpegBinaries, path: Any) -> dict[str, Any]:
    from mosaic.media.ffmpeg.builders import ffprobe_json

    probe = json.loads(run(ffmpeg_bin, ffprobe_json(path)).stdout)
    return next(st for st in probe["streams"] if st["codec_type"] == "video")


def test_a_prores_master_is_422_in_mov_with_exact_frames(
    edit: tuple[Project, ControlDB, int, int], ffmpeg_bin: FFmpegBinaries
) -> None:
    """ADR 0084: the Master ProRes preset - ProRes 422, 10-bit 4:2:2, in MOV with PCM
    sound - from the originals, frame and sample exact, every frame the right one."""
    project, control, edit_id, version = edit
    v = get_version(project, edit_id, version)
    r = get_render(
        project, _render(project, control, edit_id, version, "final", False, codec="prores")
    )
    assert r is not None
    assert r.profile["codec"] == "prores"
    path = output_path(project.workspace, r)
    assert path.suffix == ".mov"
    video = _video_stream(ffmpeg_bin, path)
    assert video["codec_name"] == "prores"
    assert video["pix_fmt"] == "yuv422p10le"
    total = v.timeline["duration"]["frames"]
    assert _frames(ffmpeg_bin, path) == total
    assert _samples(ffmpeg_bin, path) == samples_for(total, parse_rational(v.rate))
    videos = {
        int(e["asset_id"][4:]) for e in v.timeline["tracks"][0]["events"] if e["kind"] == "video"
    }
    checks = check_render(ffmpeg_bin, path, v.timeline, _sources(project, ffmpeg_bin, videos))
    assert all(c.ok for c in checks), [(c.event_id, c.decoded, c.frames) for c in checks]


def test_a_hevc_render_is_tagged_hvc1_where_a_hardware_encoder_works(
    edit: tuple[Project, ControlDB, int, int], ffmpeg_bin: FFmpegBinaries
) -> None:
    """ADR 0084: High quality HEVC through a hardware encoder (software x265 is GPL), in
    MP4 tagged hvc1, frame exact. Machines without one (CI runners) skip it."""
    from mosaic.media.tools import working_encoders

    if not working_encoders("hevc"):
        pytest.skip("no hardware HEVC encoder works on this machine")
    project, control, edit_id, version = edit
    v = get_version(project, edit_id, version)
    r = get_render(
        project, _render(project, control, edit_id, version, "final", False, codec="hevc")
    )
    assert r is not None
    path = output_path(project.workspace, r)
    video = _video_stream(ffmpeg_bin, path)
    assert (video["codec_name"], video["codec_tag_string"]) == ("hevc", "hvc1")
    assert _frames(ffmpeg_bin, path) == v.timeline["duration"]["frames"]


def test_a_final_render_writes_its_sidecars_and_meets_the_tv_loudness(
    analyzed_session: Any,
    ffmpeg_bin: FFmpegBinaries,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ADR 0084: with the EDL, SRT and report asked for, a final render writes them beside
    it: the EDL is the version's JSON, the captions are the transcript words heard in
    the edit (inside dialogue events, in order) and the report lists the shots. A TV
    request is normalized to -23 LUFS (EBU R128). With "Save to" (ADR 0091) the video and
    its sidecars are copied into that folder, never over a file already there."""
    import re

    from mosaic.editing.generate import version_json
    from mosaic.render.tasks import sidecar_path
    from mosaic.storage.models_project import Edit

    project, control = analyzed_session
    edit_id = create_edit(
        project,
        EditRequest(duration_s=60, weights={"conversations": "strong"}, loudness="tv"),
        control,
        control.local_principal,
    )
    job = submit_generate(
        LocalExecutor(JobStore(control.db)), control.local_principal, project, edit_id
    )
    assert run_job(control, job, timeout=600) == "done"
    v = get_version(project, edit_id)
    folder = tmp_path / "exports"
    folder.mkdir()
    taken = folder / f"Edit {edit_id} v{v.version}.mp4"
    with project.write() as s:
        e = s.get(Edit, edit_id)
        assert e is not None
        e.name = f"Edit {edit_id}"
    taken.write_bytes(b"the owner's own file")
    rid = _render(
        project,
        control,
        edit_id,
        v.version,
        "final",
        False,
        sidecars=("edl", "srt", "report"),
        save_to=str(folder),
    )
    r = get_render(project, rid)
    assert r is not None
    assert r.metrics["sidecars"] == ["edl", "srt", "report"]
    out = output_path(project.workspace, r)
    assert taken.read_bytes() == b"the owner's own file", "never overwritten"
    saved = Path(r.metrics["saved_to"])
    assert saved == folder / f"Edit {edit_id} v{v.version} (2).mp4"
    assert saved.read_bytes() == out.read_bytes()
    for part, suffix in (("edl", ".edl.json"), ("srt", ".srt"), ("report", ".report.txt")):
        copy = folder / f"{saved.stem}{suffix}"
        assert copy.read_bytes() == sidecar_path(out, part).read_bytes(), part
    # The same export again without Save to reuses the file, not the earlier copy's record;
    # on a server a stored Save to is never acted on (ADR 0091).
    again = get_render(project, _render(project, control, edit_id, v.version, "final", False))
    assert again is not None
    assert again.metrics.get("reused_from") == rid
    assert "saved_to" not in again.metrics
    before = sorted(p.name for p in folder.iterdir())
    monkeypatch.setattr("mosaic.core.runtime.server_mode", lambda: True)
    served = get_render(
        project,
        _render(project, control, edit_id, v.version, "final", False, save_to=str(folder)),
    )
    monkeypatch.undo()
    assert served is not None
    assert "saved_to" not in served.metrics
    assert sorted(p.name for p in folder.iterdir()) == before
    with project.db.session() as s:
        edit = s.get(Edit, edit_id)
        assert edit is not None
        assert json.loads(sidecar_path(out, "edl").read_text()) == json.loads(
            json.dumps(version_json(edit, v))
        )
    assert "events" in sidecar_path(out, "report").read_text()
    srt = sidecar_path(out, "srt").read_text()
    rate = parse_rational(v.rate)
    talk = [
        (
            e["audio"].get("timeline_in", e["timeline_in"])["frames"] / rate,
            e["audio"].get("timeline_out", e["timeline_out"])["frames"] / rate,
        )
        for e in v.timeline["tracks"][0]["events"]
        if e["audio"].get("intent") == "dialogue"
    ]
    assert talk, "the edit has dialogue"
    stamps = re.findall(r"(\d\d):(\d\d):(\d\d),(\d{3}) --> (\d\d):(\d\d):(\d\d),(\d{3})", srt)
    assert stamps, srt[:200]

    def sec(h: str, m: str, s_: str, ms: str) -> Fraction:
        return Fraction(int(h) * 3600 + int(m) * 60 + int(s_)) + Fraction(int(ms), 1000)

    starts = [sec(*t[:4]) for t in stamps]
    assert starts == sorted(starts)
    for start in starts:
        assert any(a - Fraction(1, 1000) <= start < b for a, b in talk), start
    assert r.metrics["normalized"], "the edit has sound to normalize"
    assert abs(r.metrics["loudness_lufs"] - (-23.0)) <= 1.0

    # Deleting the render's file takes its sidecars with it.
    from mosaic.render.service import delete_file

    delete_file(project, rid)
    assert not out.exists()
    assert [p for p in ("edl", "srt", "report") if sidecar_path(out, p).exists()] == []


def test_a_final_render_cancelled_after_its_sidecars_keeps_none(
    edit: tuple[Project, ControlDB, int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    """ADR 0084: Cancel arriving once the sidecars are written leaves no video and no
    sidecar (nor a half-written one)."""
    from mosaic.render import tasks
    from mosaic.storage.models_project import Render

    project, control, edit_id, version = edit
    rid = create_render(project, edit_id, version, "final", True, sidecars=("edl", "report"))
    written = tasks._sidecars

    def then_cancel(ctx: Any, r: Any, v: Any, out: Any) -> Any:
        parts = written(ctx, r, v, out)
        assert tasks.sidecar_path(out, "edl").exists()
        half = tasks.sidecar_path(out, "report")
        half.with_name(half.name + ".part").write_text("half")
        with project.write() as s:
            row = s.get(Render, rid)
            assert row is not None
            row.status = "cancelled"
        return parts

    monkeypatch.setattr(tasks, "_sidecars", then_cancel)
    job = submit_render(LocalExecutor(JobStore(control.db)), control.local_principal, project, rid)
    assert run_job(control, job, timeout=900) == "done"
    r = get_render(project, rid)
    assert r is not None
    assert r.status == "cancelled"
    out = output_path(project.workspace, r)
    assert [p.name for p in out.parent.glob(f"*r{rid:04d}*")] == []
