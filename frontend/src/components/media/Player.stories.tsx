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
