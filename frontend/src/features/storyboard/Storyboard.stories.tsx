import type { Meta, StoryObj } from "@storybook/react-vite";
import type { ReactNode } from "react";

import { frame } from "@/stories/frames";

import { ALTERNATIVES, DRAFT } from "./fixtures";
import type { DraftState } from "./model";
import { StoryboardView, type StoryboardViewProps } from "./StoryboardView";

const meta: Meta = { title: "Screens/S16 Storyboard" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const shell = (children: ReactNode) => <div className="flex h-[900px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">{children}</div>;

const base: StoryboardViewProps = {
  draft: DRAFT,
  frame: (sid) => frame(sid, sid % 7),
  alternatives: () => ALTERNATIVES,
  player: () => null,
  warnings: {},
  onOp: noop,
  onUndo: noop,
  onRedo: noop,
  onSave: noop,
  onRegenerateBeat: noop,
  onRegenerateStory: noop,
  onPreview: noop,
  onChangeSettings: noop,
};
const page = (p: Partial<StoryboardViewProps>, d: Partial<DraftState> = {}) => shell(<StoryboardView {...base} {...p} draft={p.draft === undefined && "draft" in p ? undefined : { ...DRAFT, ...d }} />);

export const Board: Story = { name: "S16 Storyboard", render: () => page({}, { regenerating: ["b5"] }) };
export const ShotOpen: Story = { name: "S16 Shot popover", render: () => page({ defaultOpen: "b3#2" }) };
export const LockedShot: Story = { name: "S16 Locked shot", render: () => page({ defaultOpen: "b4#2" }) };
export const ShotLoading: Story = { name: "S16 Alternatives loading", render: () => page({ defaultOpen: "b2#1", alternatives: () => undefined }) };
export const Unsaved: Story = { name: "S16 Unsaved changes", render: () => page({}, { dirty: true, can_undo: true }) };
export const Infeasible: Story = {
  name: "S16 Locks too long",
  render: () => page({ warnings: { b2: "Into the jungle is already as fast as it gets" } }, { metrics: { locks: { over_frames: 1200, frames: 9000, shots: 40 } } }),
};
export const WholeStory: Story = { name: "S16 Regenerating the story", render: () => page({}, { regenerating_scope: "story" }) };
export const Loading: Story = { name: "S16 Loading", render: () => page({ draft: undefined }) };
export const Failed: Story = { name: "S16 Failed to load", render: () => page({ draft: undefined, error: true, onRetry: noop }) };
export const Light: Story = { name: "S16 Light", globals: { theme: "light" }, render: () => page({}, { regenerating: ["b5"], dirty: true }) };
