import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

import { frame } from "@/stories/frames";

import { AnalysisProgressView, type AnalysisProgressViewProps } from "./AnalysisProgressView";
import { AnalysisSetupView, type AnalysisSetupViewProps } from "./AnalysisSetupView";
import { DeepenBody, type DeepenBodyProps } from "./DeepenDialog";
import { ESTIMATES, JOB, PROGRESS, SETTINGS } from "./fixtures";
import type { Preset } from "./model";

const meta: Meta = { title: "Screens/S8 Analysis setup, S9 Progress, S25 Deepen" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const page = (children: React.ReactNode) => <div className="flex h-[900px] w-[1368px] bg-bg">{children}</div>;

const setup: AnalysisSetupViewProps = {
  selected: "balanced",
  onSelect: noop,
  estimates: ESTIMATES,
  settings: SETTINGS,
  edited: new Set(),
  onEdit: noop,
  sceneModel: "anthropic · claude-haiku-4-5",
  storyModel: "anthropic · claude-sonnet-5-5",
  device: "Auto · Apple M4",
  localOnly: false,
  starting: false,
  onBack: noop,
  onAnalyze: noop,
};
export const Setup: Story = {
  render: function Render() {
    const [m, setM] = useState<Preset>("balanced");
    return page(<AnalysisSetupView {...setup} selected={m} onSelect={setM} />);
  },
};
export const SetupEstimating: Story = { render: () => page(<AnalysisSetupView {...setup} estimates={{}} />) };
export const SetupLocalOnly: Story = { render: () => page(<AnalysisSetupView {...setup} localOnly />) };

const progress: AnalysisProgressViewProps = {
  progress: PROGRESS,
  job: JOB,
  sheetUrl: () => frame(2),
  onPause: noop,
  onResume: noop,
  onCancel: noop,
  onRaiseLimit: noop,
  onRetry: noop,
  onRestart: noop,
  onDetails: noop,
  onOpenLibrary: noop,
  onCreateEdit: noop,
};
export const Progress: Story = { render: () => page(<AnalysisProgressView {...progress} />) };
export const ProgressPaused: Story = { render: () => page(<AnalysisProgressView {...progress} job={{ ...JOB, state: "paused" }} />) };
export const ProgressCostLimit: Story = {
  render: () => page(<AnalysisProgressView {...progress} job={{ ...JOB, state: "paused_cost_limit", cost_usd: 10 }} />),
};
export const ProgressComplete: Story = {
  render: () =>
    page(<AnalysisProgressView {...progress} progress={{ ...PROGRESS, failures: { count: 0, items: [] } }} job={{ ...JOB, state: "done", cost_usd: 3.2 }} />),
};
export const ProgressCompleteWithFailures: Story = {
  render: () => page(<AnalysisProgressView {...progress} job={{ ...JOB, state: "done", cost_usd: 3.2 }} />),
};
export const ProgressCancelled: Story = { render: () => page(<AnalysisProgressView {...progress} job={{ ...JOB, state: "cancelled" }} />) };

const deepen: DeepenBodyProps = {
  days: [
    { n: 2, place: "Arenal", clips: 38 },
    { n: 3, place: "Hanging bridges", clips: 44 },
    { n: 4, place: "Zipline", clips: 51 },
    { n: 5, place: "Río Celeste", clips: 29 },
    { n: 9, place: "Manuel Antonio", clips: 62 },
  ],
  selectionSize: 0,
  scope: "days",
  onScope: noop,
  picked: new Set([2, 3, 4]),
  onToggleDay: noop,
  target: "thorough",
  onTarget: noop,
  estimate: { ...ESTIMATES.thorough, scope: "deepen", videos: 195, days: 4, wall_seconds: [3000, 3600], cost_usd: [1.8, 2.6] },
  estimating: false,
  starting: false,
  onStart: noop,
  onCancel: noop,
};
const dialog = (children: React.ReactNode) => <div className="w-[560px] rounded-[16px] border border-border bg-surface-1 p-6">{children}</div>;
export const Deepen: Story = { render: () => dialog(<DeepenBody {...deepen} />) };
export const DeepenNothingSelected: Story = { render: () => dialog(<DeepenBody {...deepen} picked={new Set()} estimate={undefined} />) };
export const DeepenEstimating: Story = { render: () => dialog(<DeepenBody {...deepen} estimating estimate={undefined} />) };
