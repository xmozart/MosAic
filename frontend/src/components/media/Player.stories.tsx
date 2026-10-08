import type { Meta, StoryObj } from "@storybook/react-vite";

import { frames } from "@/stories/frames";
import sample from "@/stories/assets/sample.mp4";

import { Filmstrip } from "./Filmstrip";
import { Player } from "./Player";
import { Waveform } from "./Waveform";

const meta: Meta = { title: "Media/Player" };
export default meta;
type Story = StoryObj;

const tb = "1/90000";
const at = (s: number) => ({ ticks: Math.round(s * 90000), tb });

export const Default: Story = {
  render: () => (
    <div className="w-[640px]">
      <Player src={sample} rate="30/1" />
    </div>
  ),
};

export const UsableRangeAndMarkers: Story = {
  render: () => (
    <div className="w-[640px]">
      <Player
        src={sample}
        rate="30/1"
        usableRange={{ start: at(0.6), end: at(3.4) }}
        markers={[
          { at: at(1.2), label: "Toucan lands", kind: "moment" },
          { at: at(2.8), label: "Dialogue cut off", kind: "finding" },
        ]}
      />
    </div>
  ),
};

export const PlayRangeOnly: Story = {
  render: () => (
    <div className="w-[640px]">
      <Player src={sample} rate="30/1" range={{ start: at(1), end: at(2.5) }} />
    </div>
  ),
};

export const BeatSegmentsAndOverlay: Story = {
  name: "Beat segments, overlay and controls (S17)",
  render: () => (
    <div className="w-[640px]">
      <Player
        src={sample}
        rate="30/1"
        length={at(4)}
        segments={[
          { start: at(0), end: at(1.2), label: "Arrival", series: 1 },
          { start: at(1.2), end: at(2.6), label: "Wildlife", series: 2 },
          { start: at(2.6), end: at(4), label: "Finale", series: 3 },
        ]}
        overlay={
          <span data-theme="dark" className="absolute top-3 left-3 rounded-full bg-media-chip px-2 py-0.5 text-micro text-on-media">
            v2 · preview 720p
          </span>
        }
        controlsEnd={<span className="text-caption text-text-muted">v1 · v2</span>}
      />
    </div>
  ),
};

export const NoPreviewYet: Story = {
  render: () => (
    <div className="w-[640px]">
      <Player rate="30/1" />
    </div>
  ),
};

const PEAKS = Uint8Array.from({ length: 300 }, (_, i) => Math.round(40 + 160 * Math.abs(Math.sin(i / 9)) * (i > 20 ? 1 : 0.2)));

export const WaveformStates: Story = {
  render: () => (
    <div className="flex w-[640px] flex-col gap-4">
      <Waveform peaks={PEAKS} />
      <Waveform peaks={PEAKS} selection={[0.2, 0.55]} position={0.4} />
      <Waveform peaks={new Uint8Array()} />
    </div>
  ),
};

export const FilmstripStates: Story = {
  render: () => (
    <div className="flex w-[640px] flex-col gap-4">
      <Filmstrip frames={frames(1, 8)} />
      <Filmstrip frames={frames(2, 8)} selection={[2, 5]} />
    </div>
  ),
};
