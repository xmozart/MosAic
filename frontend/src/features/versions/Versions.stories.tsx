import type { Meta, StoryObj } from "@storybook/react-vite";

import sample from "@/stories/assets/sample.mp4";

import { COMPARE, VERSIONS } from "./fixtures";
import { VersionsView, type VersionsViewProps } from "./VersionsView";

const meta: Meta = { title: "Screens/S18 Versions" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const base: VersionsViewProps = {
  title: "Costa Rica — 5 min cinematic",
  versions: VERSIONS,
  pair: [2, 3],
  compare: COMPARE,
  previews: { 2: { url: sample }, 3: { url: sample } },
  onSelect: noop,
  onLatestPair: noop,
  onRevert: noop,
  onBack: noop,
  now: new Date("2026-07-26T18:00:00"),
};
const page = (p: Partial<VersionsViewProps>) => (
  <div className="flex h-[900px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">
    <VersionsView {...base} {...p} />
  </div>
);

export const Comparing: Story = { name: "S18 Comparing", render: () => page({}) };
export const OlderPair: Story = { name: "S18 Compare v1 with the latest", render: () => page({ pair: [1, 3], compare: { ...COMPARE, a: 1 } }) };
export const NoPreview: Story = { name: "S18 Preview missing", render: () => page({ previews: { 2: { onRender: noop }, 3: { status: "Rendering 45%" } } }) };
export const Same: Story = { name: "S18 Same versions", render: () => page({ compare: { ...COMPARE, same: true, changes: [] } }) };
export const Single: Story = { name: "S18 Single version", render: () => page({ versions: VERSIONS.slice(0, 1), pair: null, compare: undefined }) };
export const Loading: Story = { name: "S18 Loading", render: () => page({ versions: undefined, pair: null, compare: undefined }) };
export const Light: Story = { name: "S18 Light", globals: { theme: "light" }, render: () => page({}) };
