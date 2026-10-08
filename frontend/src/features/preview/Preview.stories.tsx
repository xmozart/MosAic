import type { Meta, StoryObj } from "@storybook/react-vite";

import { EditFacts } from "@/components/edit/EditFacts";
import sample from "@/stories/assets/sample.mp4";

import { BEATS, EDIT, REPORT, renderRow } from "./fixtures";
import { factsRows } from "./model";
import { PreviewView, type PreviewViewProps } from "./PreviewView";
import { ReportPanel, type ReportPanelProps } from "./ReportPanel";

const meta: Meta = { title: "Screens/S17 Preview" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const base: PreviewViewProps = {
  title: "Costa Rica — 5 min cinematic",
  state: { kind: "ready", edit: EDIT },
  versions: [1, 2, 3].map((v) => ({ version: v, created_at: "2026-07-26T14:20:00" })),
  onVersion: noop,
  preview: renderRow(2),
  previewUrl: sample, // a stand-in clip; the product plays the version's preview file
  onRenderPreview: noop,
  onRenderFinal: noop,
  onRetryGenerate: noop,
  onBack: noop,
  onExports: noop,
  report: REPORT,
};
const page = (p: Partial<PreviewViewProps>) => (
  <div className="flex h-[900px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">
    <PreviewView {...base} {...p} />
  </div>
);

export const Ready: Story = { render: () => page({}) };
export const PreviewRendering: Story = { render: () => page({ preview: renderRow(2, { status: "rendering", pct: 45 }) }) };
export const PreviewQueued: Story = { render: () => page({ preview: renderRow(2, { status: "queued" }) }) };
export const PreviewFailed: Story = { render: () => page({ preview: renderRow(2, { status: "failed" }) }) };
export const FinalRendering: Story = { render: () => page({ final: renderRow(3, { kind: "final", status: "rendering", pct: 20 }) }) };
export const FinalDone: Story = { render: () => page({ final: renderRow(3, { kind: "final" }), finalDownloadUrl: "#download" }) };
export const ReportLoading: Story = { render: () => page({ report: undefined }) };
export const StillGenerating: Story = { render: () => page({ state: { kind: "generating", pct: 64 } }) };
export const CouldNotCreate: Story = { render: () => page({ state: { kind: "failed", error: "No usable clips: analyze the folder first." } }) };
export const Light: Story = { globals: { theme: "light" }, render: () => page({}) };
export const LightRendering: Story = { globals: { theme: "light" }, render: () => page({ preview: renderRow(2, { status: "rendering", pct: 70 }) }) };
export const NoPreviewYet: Story = { render: () => page({ preview: undefined }) };
export const PreviewFileMissing: Story = { render: () => page({ preview: renderRow(2, { status: "missing" }) }) };
export const Loading: Story = { render: () => page({ state: { kind: "loading" } }) };
export const NotMadeYet: Story = { render: () => page({ state: { kind: "new" } }) };
export const NotFound: Story = { render: () => page({ state: { kind: "missing" } }) };
export const LoadError: Story = { render: () => page({ state: { kind: "error" }, onRetryLoad: noop }) };
export const ReportError: Story = { render: () => page({ report: undefined, reportError: true, onRetryReport: noop }) };

const panel = (p: Partial<ReportPanelProps>) => (
  <div className="flex h-[700px] bg-bg p-4">
    <ReportPanel report={REPORT} beats={BEATS} onSeek={noop} onMoreRejected={noop} {...p} />
  </div>
);
export const ReportRejected: Story = { name: "Report · Rejected (AI vs you, Show more)", render: () => panel({ initialTab: "rejected" }) };
export const ReportNotUsed: Story = { name: "Report · Not used", render: () => panel({ initialTab: "not_used" }) };
export const ReportNothingRejected: Story = {
  name: "Report · Nothing rejected or unused",
  render: () => panel({ initialTab: "rejected", report: { ...REPORT, not_used: [], rejected: { total: 0, offset: 0, items: [] } } }),
};

export const Facts: Story = { name: "EditFacts", render: () => <div className="w-[880px] bg-bg p-4"><EditFacts rows={factsRows(EDIT.facts)} /></div> };
