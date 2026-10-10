import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

import { Button } from "@/components/ui/Button";
import { Segmented } from "@/components/ui/Segmented";
import { frame } from "@/stories/frames";

import { ClockOffsetRow, type ClockChoice } from "./ClockOffsetRow";
import { EstimateCard } from "./EstimateCard";
import { ModeCard } from "./ModeCard";
import { PlacementBadge } from "./PlacementBadge";
import { SecretField } from "./SecretField";
import { SectionNav } from "./SectionNav";
import { SettingRow } from "./SettingRow";
import { StageList } from "./StageList";
import { StorageBreakdown } from "./StorageBreakdown";
import { UnsupportedRow } from "./UnsupportedRow";
import { Lock } from "lucide-react";

import { ChoiceCard } from "./ChoiceCard";

const meta: Meta = { title: "System" };
export default meta;
type Story = StoryObj;

export const Stages: Story = {
  render: () => (
    <div className="w-[520px]">
      <StageList
        stages={[
          { key: "scan", label: "Looking through your footage", state: "done", note: "412 clips · 1,180 photos" },
          { key: "proxy", label: "Making previews", state: "done", note: "412 of 412" },
          { key: "shots", label: "Finding shots", state: "done", note: "2,380 shots" },
          { key: "vision", label: "Understanding scenes", state: "running", pct: 45, note: "GX030211.MP4 · sheet 96 of 214" },
          { key: "paused", label: "Deep review", state: "paused", note: "Paused at the cost limit" },
          { key: "failed", label: "Listening", state: "failed", note: "2 clips couldn't be processed" },
          { key: "group", label: "Grouping similar shots", state: "pending" },
        ]}
      />
    </div>
  ),
};

export const Modes: Story = {
  render: function Render() {
    const [m, setM] = useState("balanced");
    const modes = [
      ["quick", "Quick", "See results fast. Good for short trips or a first look.", "About 35 min · $0.80–1.50 · 6 GB"],
      ["balanced", "Balanced", "Great edits for most trips.", "About 1 h 40 m · $2–4 · 18 GB"],
      ["thorough", "Thorough", "Best shot selection and cut points. Deep review of your best clips.", "About 4 h 30 m · $6–10 · 19 GB"],
    ] as const;
    return (
      <div className="flex flex-col gap-4">
        <div role="radiogroup" aria-label="Analysis mode" className="grid grid-cols-3 gap-4">
          {modes.map(([id, t, d, e]) => (
            <ModeCard key={id} title={t} description={d} estimate={e} recommended={id === "balanced"} selected={m === id} onSelect={() => setM(id)} />
          ))}
        </div>
        <EstimateCard time="About 1 h 40 m" cost="$2–4" storage="18 GB" basis="Time from this computer's benchmark." />
      </div>
    );
  },
};

export const ModesEstimating: Story = {
  render: () => (
    <div role="radiogroup" aria-label="Analysis mode" className="grid w-[1100px] grid-cols-3 gap-4">
      <ModeCard title="Quick" description="See results fast. Good for short trips or a first look." estimate="" loading />
      <ModeCard title="Balanced" description="Great edits for most trips." estimate="" loading recommended selected />
      <ModeCard title="Thorough" description="Best shot selection and cut points. Deep review of your best clips." estimate="" loading />
    </div>
  ),
};

export const Placements: Story = {
  render: () => (
    <div className="flex flex-wrap gap-2">
      <PlacementBadge placement="in_folder" />
      <PlacementBadge placement="split_nas" />
      <PlacementBadge placement="split_icloud" />
      <PlacementBadge placement="separate" />
      <PlacementBadge placement="external_drive" />
    </div>
  ),
};

export const NeedsAttention: Story = {
  render: () => (
    <div className="flex w-[720px] flex-col rounded-lg border border-border bg-surface-1 px-[18px]">
      <UnsupportedRow
        kind="unreadable"
        title="3 Nikon N-RAW clips can't be read"
        reason="Export them as MP4 from NX Studio, then rescan."
        actions={<><Button size="sm">Show files</Button><Button size="sm" variant="ghost">Ignore</Button></>}
      />
      <UnsupportedRow
        kind="limited"
        title="14 Insta360 clips are 360°"
        reason="MosAic will analyze them but can't edit 360 video yet. Export flat versions from Insta360 Studio."
        actions={<Button size="sm">Show files</Button>}
      />
      <UnsupportedRow
        kind="cloud"
        title="22 files (48 GB) are only in iCloud"
        reason="They're not on this Mac yet."
        actions={<><Button size="sm" variant="primary">Download now</Button><Button size="sm" variant="ghost">Skip these</Button></>}
      />
      <UnsupportedRow kind="damaged" title="1 file couldn't be read" reason="GX050233.MP4 looks damaged." actions={<Button size="sm">Show</Button>} />
    </div>
  ),
};

export const ClockOffset: Story = {
  render: function Render() {
    const [choice, setChoice] = useState<ClockChoice>("accept");
    return (
      <div className="flex w-[832px] flex-col gap-4">
        <ClockOffsetRow
          device="GoPro HERO12 Black"
          summary="Appears 5 h 00 m ahead"
          offset="−5 h 00 m"
          evidence={{ reference: "iPhone · Jul 15 10:42", device: "GoPro · Jul 15 15:43", frames: [frame(0), frame(0, 2)], moment: "the waterfall trail on Day 2." }}
          choice={choice}
          onChoice={setChoice}
          onStep={() => setChoice("adjust")}
        />
        <ClockOffsetRow device="Sony ZV-1" summary="No matching moments found yet." offset="0 h 00 m" choice="leave" onChoice={() => {}} onStep={() => {}} />
      </div>
    );
  },
};

export const Settings: Story = {
  render: function Render() {
    const [mode, setMode] = useState<"quick" | "balanced" | "thorough">("balanced");
    return (
      <div className="w-[720px]">
        <SettingRow
          label="Default analysis mode"
          source="default"
          control={<Segmented label="Mode" value={mode} onChange={setMode} options={[{ value: "quick", label: "Quick" }, { value: "balanced", label: "Balanced" }, { value: "thorough", label: "Thorough" }]} />}
          onReset={() => setMode("balanced")}
        />
        <SettingRow label="Speech" description="whisper · medium · On this Mac" source="user" control={<Button size="sm">Change</Button>} onReset={() => {}} />
        <SettingRow label="Cost limit" source="project" control={<span className="mono text-timecode">$10.00</span>} onReset={() => {}} />
        <SettingRow label="Sample interval" description="Decided by the analysis mode" source="mode" control={<span className="mono text-timecode">2.0 s</span>} onReset={() => {}} />
      </div>
    );
  },
};

export const Secret: Story = {
  render: () => (
    <div className="flex w-[560px] flex-col gap-6">
      <SecretField label="Anthropic API key" where="Stored in macOS Keychain · added Sep 29" last4="7F3A" onSave={() => {}} onValidate={() => {}} />
      <SecretField label="Anthropic API key" onSave={() => {}} onValidate={() => {}} />
      <SecretField label="Anthropic API key" last4="7F3A" validating onSave={() => {}} onValidate={() => {}} />
      <SecretField label="Anthropic API key" last4="7F3A" status="invalid" onSave={() => {}} onValidate={() => {}} />
    </div>
  ),
};

export const Storage: Story = {
  render: () => (
    <div className="w-[520px]">
      <StorageBreakdown
        parts={[
          { label: "Previews", bytes: 12.4e9, size: "12.4 GB", regenerable: true },
          { label: "Frames and contact sheets", bytes: 3.1e9, size: "3.1 GB", regenerable: true },
          { label: "Renders", bytes: 2.2e9, size: "2.2 GB", regenerable: false },
          { label: "Library database", bytes: 0.3e9, size: "310 MB", regenerable: false },
        ]}
      />
    </div>
  ),
};

export const Sections: Story = {
  name: "SectionNav",
  render: function Render() {
    const [active, setActive] = useState("storage");
    return (
      <div className="flex h-[400px] bg-bg">
        <SectionNav
          title="Project settings"
          active={active}
          onSelect={setActive}
          sections={[
            { id: "general", label: "General" },
            { id: "analysis", label: "Analysis" },
            { id: "storage", label: "Storage" },
            { id: "danger", label: "Danger zone", danger: true },
          ]}
        />
      </div>
    );
  },
};

export const SecretFieldStates: Story = {
  name: "SecretField · remove and blocked validate",
  render: () => (
    <div className="flex w-[640px] flex-col gap-6">
      <SecretField label="Anthropic API key" where="Stored in the system keychain" last4="7F3A" onSave={() => {}} onValidate={() => {}} onRemove={() => {}} />
      <SecretField label="Anthropic API key" where="Stored in the system keychain" last4="7F3A" onSave={() => {}} onValidate={() => {}} validateBlocked="Local only is on: nothing is sent to check the key." />
    </div>
  ),
};

export const ChoiceCards: Story = {
  render: () => (
    <div className="grid w-[760px] grid-cols-2 gap-3">
      <ChoiceCard selected title="Hybrid" badge="Recommended" text="Processing stays on this Mac; the AI sees selected frames and text." onClick={() => {}} />
      <ChoiceCard selected={false} title="Local only" icon={<Lock className="size-4" />} text="Most private. Story editing and scene understanding are limited." onClick={() => {}} />
    </div>
  ),
};

