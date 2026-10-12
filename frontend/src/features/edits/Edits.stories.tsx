import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type ReactNode } from "react";

import { frame } from "@/stories/frames";

import { EditsView, type EditsViewProps } from "./EditsView";
import { CARDS, ESTIMATE, PRESETS } from "./fixtures";
import { DEFAULT_REQUEST, defaultName, type CategoryCount, type EditRequest } from "./model";
import { WizardView, type WizardViewProps } from "./WizardView";

const meta: Meta = { title: "Screens/S13 S14 Edits" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const NOW = new Date("2026-07-26T18:00:00");
const shell = (children: ReactNode) => <div className="flex h-[900px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">{children}</div>;

const edits: EditsViewProps = {
  items: CARDS,
  coverUrl: (i) => frame(i),
  renderLink: (_e, children, className) => (
    <a href="#edit" className={className}>
      {children}
    </a>
  ),
  onCreate: noop,
  onStartFrom: noop,
  now: NOW,
};
const editsPage = (p: Partial<EditsViewProps>) => shell(<EditsView {...edits} {...p} />);

export const EditsGrid: Story = { name: "S13 Edits", render: () => editsPage({}) };
export const EditsEmpty: Story = { name: "S13 Empty", render: () => editsPage({ items: [] }) };
export const EditsLoading: Story = { name: "S13 Loading", render: () => editsPage({ items: undefined }) };
export const EditsFailed: Story = { name: "S13 Failed to load", render: () => editsPage({ items: undefined, error: true, onRetry: noop }) };
export const EditsLight: Story = { name: "S13 Light", globals: { theme: "light" }, render: () => editsPage({}) };

const collages = Object.fromEntries(PRESETS.filter((x) => x.featured).map((x, i) => [x.id, [frame(i), frame(i + 1, 3), frame(i + 2, 5)]]));

function Wizard(p: Partial<WizardViewProps> & { start?: Partial<EditRequest> }) {
  const [request, setRequest] = useState<EditRequest>({ ...DEFAULT_REQUEST, duration_s: 300, ...p.start });
  const [step, setStep] = useState(p.step ?? 1);
  return shell(
    <WizardView
      step={step}
      onStep={setStep}
      request={request}
      onChange={(patch) => setRequest((r) => ({ ...r, ...patch }))}
      title={defaultName("Costa Rica 2026", request)}
      presets={PRESETS}
      collages={collages}
      estimate={ESTIMATE}
      creating={false}
      onCreate={noop}
      onWait={noop}
      {...p}
    />,
  );
}

export const WizardLength: Story = { name: "S14 Step 1 Length & format", render: () => <Wizard /> };
export const WizardStory: Story = { name: "S14 Step 2 Story", render: () => <Wizard step={2} /> };
export const WizardCustomStory: Story = { name: "S14 Step 2 Custom story", render: () => <Wizard step={2} start={{ story: "road_trip" }} /> };
export const WizardAnythingElse: Story = {
  name: "S14 Step 6 Anything else",
  render: () => <Wizard step={6} start={{ instructions: "Avoid long driving clips. Include funny reactions." }} />,
};
export const WizardPreliminary: Story = {
  name: "S14 Preliminary analysis",
  render: () => <Wizard estimate={{ ...ESTIMATE, preliminary: true, analysis_pct: 42 }} />,
};
export const WizardShortFootage: Story = {
  name: "S14 Not enough footage",
  render: () => <Wizard start={{ duration_s: 1200 }} estimate={{ ...ESTIMATE, enough_footage: false, usable_seconds: 380 }} />,
};
export const WizardNothingToEdit: Story = {
  name: "S14 Nothing to edit",
  render: () => <Wizard estimate={{ ...ESTIMATE, candidates: 0, enough_footage: false, usable_seconds: 0 }} />,
};
export const WizardEstimating: Story = { name: "S14 Estimate loading", render: () => <Wizard estimate={undefined} /> };
export const WizardReuse: Story = { name: "S14 Plan reused", render: () => <Wizard estimate={{ ...ESTIMATE, reuses_plan: true, cost_usd: [0, 0] }} /> };
export const WizardLight: Story = { name: "S14 Light", globals: { theme: "light" }, render: () => <Wizard step={2} /> };

const CATEGORIES_IN_LIBRARY: CategoryCount[] = (
  ["wildlife", "people", "reactions", "landscapes", "drone", "selfies", "food", "action", "pov", "conversations", "natural_sound", "humor", "sunsets", "water", "city", "night", "photos"] as const
).map((category, i) => ({ category, count: 120 - i * 6 }));
const FEATURE: Partial<EditRequest> = {
  weights: { wildlife: "strong", people: "more", reactions: "more", selfies: "less" },
  rules: { ...DEFAULT_REQUEST.rules, drone_openers: true },
};
const TRACK = {
  name: "Horizon.mp3",
  duration_ms: 228000,
  sample_rate: 44100,
  peaks: [30, 50, 40, 60, 45, 70, 55, 80, 65, 90, 70, 60, 85, 75, 95, 80, 70, 90, 100, 85, 70, 80, 60, 75, 90, 70, 55, 80, 65, 50, 70, 85, 60, 45, 65, 55, 40, 60, 50, 35, 45, 40, 30, 35, 25, 30, 20, 15],
};
const pickNothing = () => Promise.resolve(true);
const MUSIC = { music: { path: "/Users/me/Music/Horizon.mp3", level_db: -18, fade_in_ms: 2000, fade_out_ms: 3000 } };

export const WizardCustomBeats: Story = {
  name: "S14 Step 2 Custom beats",
  render: () => (
    <Wizard
      step={2}
      start={{ arc: "custom", beats: ["Arrival", "Into the jungle", "Waterfalls", "Wildlife", "Up in the canopy", "The coast", "Finale"] }}
    />
  ),
};
export const WizardBeatsUnnamed: Story = {
  name: "S14 Step 2 Beats to name",
  render: () => <Wizard step={2} start={{ arc: "custom", beats: ["Arrival", ""] }} />,
};
export const WizardFeature: Story = {
  name: "S14 Step 3 What to feature",
  render: () => <Wizard step={3} categories={CATEGORIES_IN_LIBRARY} start={FEATURE} />,
};
export const WizardFeatureLoading: Story = { name: "S14 Step 3 Loading", render: () => <Wizard step={3} categories={undefined} /> };
export const WizardStyle: Story = {
  name: "S14 Step 4 Style",
  render: () => <Wizard step={4} start={{ ...FEATURE, pace: "balanced", rules: { ...DEFAULT_REQUEST.rules, allow_imperfect: true, drone_openers: true } }} />,
};
export const WizardSound: Story = { name: "S14 Step 5 Sound", render: () => <Wizard step={5} /> };
export const WizardSoundTrack: Story = {
  name: "S14 Step 5 Track",
  render: () => <Wizard step={5} start={{ ...FEATURE, ...MUSIC }} track={TRACK} onChooseTrack={pickNothing} />,
};
export const WizardSoundReading: Story = {
  name: "S14 Step 5 Reading the track",
  render: () => <Wizard step={5} start={MUSIC} track={null} onChooseTrack={pickNothing} />,
};
export const WizardSoundTrackError: Story = {
  name: "S14 Step 5 Track can't be read",
  render: () => <Wizard step={5} start={MUSIC} track={null} trackError="Horizon.mp3: it has no audio" onChooseTrack={pickNothing} />,
};
export const WizardFeatureLight: Story = {
  name: "S14 Step 3 Light",
  globals: { theme: "light" },
  render: () => <Wizard step={3} categories={CATEGORIES_IN_LIBRARY} start={FEATURE} />,
};
