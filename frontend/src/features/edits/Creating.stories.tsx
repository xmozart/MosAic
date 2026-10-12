import type { Meta, StoryObj } from "@storybook/react-vite";

import { frame } from "@/stories/frames";

import { CreatingView, type CreatingViewProps } from "./CreatingView";
import type { Creating, CreatingJob } from "./creating";

const meta: Meta = { title: "Screens/S15 Creating edit" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const BEATS: NonNullable<Creating["beats"]> = [
  { beat_id: "b1", title: "Arrival", intent: "The landing, the drive and a first look at the volcano", sample_ids: [1, 2, 3] },
  { beat_id: "b2", title: "Into the jungle", intent: "The rainforest, and the excitement of getting there", sample_ids: [4, 5, 6] },
  { beat_id: "b3", title: "Waterfalls", intent: "Falls and the turquoise river", sample_ids: [7, 8, 9] },
  { beat_id: "b4", title: "Wildlife", intent: "Birds, sloths and monkeys up close", sample_ids: [] },
  { beat_id: "b5", title: "Up in the canopy", intent: "Hanging bridges and the zipline", sample_ids: [] },
  { beat_id: "b6", title: "The coast", intent: "Beach, boat and dolphins", sample_ids: [] },
  { beat_id: "b7", title: "Finale", intent: "Sunset and a calm pull-away", sample_ids: [] },
];
const job = (state: CreatingJob["state"], creating: Creating, error: string | null = null): CreatingJob => ({ job_id: 7, state, error, result: { creating } });
const counts = { moments: 412, candidates: 186 };

function Screen(p: Partial<CreatingViewProps>) {
  return (
    <div className="flex h-[900px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">
      <CreatingView
        title="Costa Rica — 5 min cinematic"
        seconds={300}
        // Shots are chosen in one call: no beat has frames until they all do (ADR 0087).
        generation={job("running", { step: "selecting", ...counts, beats: BEATS.map((b) => ({ ...b, sample_ids: [] })) })}
        preview={undefined}
        frame={(sid) => frame(sid, sid)}
        onBackground={noop}
        onCancel={noop}
        onRetry={noop}
        onView={noop}
        {...p}
      />
    </div>
  );
}

export const Planning: Story = { name: "S15 Planning", render: () => <Screen generation={job("running", { step: "planning", ...counts })} /> };
export const Running: Story = { name: "S15 Choosing shots", render: () => <Screen /> };
export const Failed: Story = {
  name: "S15 Failed",
  render: () => <Screen generation={job("failed", { step: "planning", ...counts }, "PermanentError: only one usable clip: an edit needs at least two")} />,
};
export const Cancelled: Story = { name: "S15 Cancelled", render: () => <Screen generation={job("cancelled", { step: "selecting", ...counts, beats: BEATS })} /> };
export const RenderingPreview: Story = {
  name: "S15 Rendering preview",
  render: () => <Screen generation={job("done", { step: "checking", ...counts, beats: BEATS.map((b, i) => ({ ...b, sample_ids: [i * 3 + 1, i * 3 + 2, i * 3 + 3] })) })} preview={{ state: "running" }} />,
};
export const Ready: Story = {
  name: "S15 Ready",
  render: () => <Screen generation={job("done", { step: "checking", ...counts, beats: BEATS.map((b, i) => ({ ...b, sample_ids: [i * 3 + 1, i * 3 + 2, i * 3 + 3] })) })} preview={{ state: "done" }} />,
};
export const RunningLight: Story = { name: "S15 Light", globals: { theme: "light" }, render: () => <Screen /> };
