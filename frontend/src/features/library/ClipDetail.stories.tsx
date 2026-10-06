import type { Meta, StoryObj } from "@storybook/react-vite";

import { frame } from "@/stories/frames";

import { ClipDetailView, type ClipDetailViewProps } from "./ClipDetailView";
import { DETAIL, PHOTO, THREE_SIXTY, TRANSCRIPT, UNSUPPORTED } from "./fixtures";

const meta: Meta = { title: "Screens/S11 Clip detail" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const peaks = new Uint8Array(Array.from({ length: 400 }, (_, i) => Math.round(60 + 120 * Math.abs(Math.sin(i / 9)) * (i % 7 === 0 ? 1.3 : 1))));
const base: ClipDetailViewProps = {
  clip: { ...DETAIL, transcript: { segments: 1, language: "en" } },
  frameUrl: (i) => frame(i),
  filmstrip: Array.from({ length: 12 }, (_, i) => frame(i % 5, i)),
  peaks,
  transcript: TRANSCRIPT,
  onDecide: noop,
  onBack: noop,
  onNext: noop,
  onShowClip: noop,
};
const page = (p: Partial<ClipDetailViewProps>) => (
  <div className="flex h-[900px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">
    <ClipDetailView {...base} {...p} />
  </div>
);

export const VideoWithSpeech: Story = { render: () => page({}) };
export const VideoWithoutSpeech: Story = { render: () => page({ transcript: [] }) };
export const Photo: Story = { render: () => page({ clip: PHOTO, transcript: [], peaks: null, filmstrip: [] }) };
export const Unsupported: Story = { render: () => page({ clip: UNSUPPORTED, transcript: [], peaks: null, filmstrip: [] }) };
export const ThreeSixty: Story = { render: () => page({ clip: THREE_SIXTY, transcript: [] }) };
export const Light: Story = { globals: { theme: "light" }, render: () => page({}) };
