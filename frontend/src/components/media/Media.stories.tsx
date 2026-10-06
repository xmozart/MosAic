import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

import { frame, frames } from "@/stories/frames";

import { CameraBadge } from "./CameraBadge";
import { ClipTile, type ClipTileProps } from "./ClipTile";
import { DispositionChip } from "./DispositionChip";
import { DispositionControl } from "./DispositionControl";
import { IncludeToggle, type Include as IncludeValue } from "./IncludeToggle";
import { QualityRow } from "./QualityRow";
import { StarRating } from "./StarRating";
import type { Disposition } from "@/lib/domain";

const meta: Meta = { title: "Media" };
export default meta;
type Story = StoryObj;

const VALUES: Disposition[] = ["USE", "MAYBE", "REJECT"];

export const DispositionChips: Story = {
  render: () => (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2.5">
        {VALUES.map((v) => (
          <DispositionChip key={v} value={v} by="ai" />
        ))}
        <span className="w-6" />
        {VALUES.map((v) => (
          <DispositionChip key={v} value={v} by="user" />
        ))}
      </div>
      <div className="flex flex-wrap gap-2.5">
        {VALUES.map((v) => (
          <DispositionChip key={v} value={v} by="ai" size="sm" />
        ))}
        {VALUES.map((v) => (
          <DispositionChip key={v} value={v} by="user" size="sm" />
        ))}
      </div>
    </div>
  ),
};

export const DispositionControlStates: Story = {
  render: function Render() {
    const [v, setV] = useState<Disposition | undefined>(undefined);
    return (
      <div className="flex flex-col gap-3">
        <DispositionControl value={v} onChange={setV} />
        <DispositionControl value="USE" onChange={() => {}} />
        <DispositionControl value="REJECT" onChange={() => {}} />
      </div>
    );
  },
};

export const Stars: Story = {
  render: function Render() {
    const [v, setV] = useState(3);
    return (
      <div className="flex flex-col gap-3">
        <StarRating value={v} onChange={setV} />
        <StarRating value={0} onChange={() => {}} />
        <StarRating value={5} />
        <StarRating value={2} size="sm" />
      </div>
    );
  },
};

export const Include: Story = {
  render: function Render() {
    const [v, setV] = useState<IncludeValue>("none");
    return (
      <div className="flex flex-col gap-3">
        <IncludeToggle value={v} onChange={setV} />
        <IncludeToggle value="always" onChange={() => {}} />
        <IncludeToggle value="never" onChange={() => {}} />
      </div>
    );
  },
};

export const CameraBadges: Story = {
  render: () => (
    <div className="flex flex-wrap gap-2 rounded-md bg-[#2e5a40] p-3">
      <CameraBadge kind="phone" label="iPhone" />
      <CameraBadge kind="actioncam" label="GoPro" />
      <CameraBadge kind="360" label="X4" />
      <CameraBadge kind="drone" label="DJI" />
      <CameraBadge kind="camera" label="Nikon" />
      <CameraBadge kind="photo" label="Photo" />
    </div>
  ),
};

export const Quality: Story = {
  render: () => <QualityRow sharpness="Excellent" steadiness="Good" exposure="Fair" audio="None" />,
};

const base: ClipTileProps = {
  asset: { name: "DJI_0142.MP4", duration: "0:48", camera: { kind: "drone", label: "DJI" }, thumbnail: frame(0), frames: frames(0) },
};

const TILES: [string, ClipTileProps][] = [
  ["Default · user USE ★5 · +3 similar", { ...base, disposition: "USE", decidedBy: "user", stars: 5, similarCount: 3 }],
  ["AI suggested USE · selected", { asset: { name: "IMG_4471.MOV", duration: "0:19", camera: { kind: "phone", label: "iPhone" }, thumbnail: frame(1), frames: frames(1) }, disposition: "USE", selected: true }],
  ["MAYBE · speech", { asset: { name: "GX020301.MP4", duration: "4:02", camera: { kind: "actioncam", label: "GoPro" }, thumbnail: frame(2) }, disposition: "MAYBE", hasSpeech: true }],
  ["REJECT (accidental) · dimmed", { asset: { name: "IMG_4903.MOV", duration: "0:04", camera: { kind: "phone", label: "iPhone" }, thumbnail: frame(3) }, disposition: "REJECT" }],
  ["User MAYBE", { ...base, disposition: "MAYBE", decidedBy: "user" }],
  ["User REJECT", { ...base, disposition: "REJECT", decidedBy: "user" }],
  ["Live Photo", { asset: { name: "IMG_4907.HEIC", camera: { kind: "photo", label: "Photo" }, thumbnail: frame(4), livePhoto: true }, disposition: "USE", decidedBy: "user", stars: 4 }],
  ["360° · analysis only", { asset: { name: "VID_20250318_101244.insv", duration: "2:10", camera: { kind: "360", label: "X4" }, thumbnail: frame(2), analysisOnly: true } }],
  ["Offline · preview only", { asset: { name: "DSC_0932.MOV", duration: "0:31", camera: { kind: "camera", label: "Nikon" }, thumbnail: frame(1), offline: true }, disposition: "USE" }],
  ["Unsupported", { asset: { name: "DSC_0877.NEV", camera: { kind: "camera", label: "Nikon" }, unsupported: { reason: "N-RAW can't be read.", fix: "Export as MP4 from NX Studio." } } }],
  ["Preliminary (analysis running)", { ...base, preliminary: true }],
  ["Compact density", { ...base, disposition: "USE", density: "compact" }],
  ["Hover · scrubbing, unrated", { ...base, disposition: "USE", scrubIndex: 5 }],
];

export const Tiles: Story = {
  render: () => (
    <div className="grid grid-cols-4 gap-5">
      {TILES.map(([caption, props]) => (
        <ClipTile key={caption} {...props} caption={caption} />
      ))}
    </div>
  ),
};
