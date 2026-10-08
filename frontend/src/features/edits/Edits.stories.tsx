import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState, type ReactNode } from "react";

import { frame } from "@/stories/frames";

import { EditsView, type EditsViewProps } from "./EditsView";
import { CARDS, ESTIMATE, PRESETS } from "./fixtures";
import { DEFAULT_REQUEST, defaultName, type EditRequest } from "./model";
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
