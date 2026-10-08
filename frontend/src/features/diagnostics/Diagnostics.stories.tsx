import type { Meta, StoryObj } from "@storybook/react-vite";

import { DiagnosticsView, type DiagnosticsViewProps } from "./DiagnosticsView";
import { DONE_AI, FAILED, ROWS, RUNNING } from "./fixtures";

const meta: Meta = { title: "Screens/S23 Diagnostics" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const base: DiagnosticsViewProps = {
  filter: "all",
  onFilter: noop,
  projects: [{ id: "P1", name: "Costa Rica 2026" }],
  project: null,
  onProject: noop,
  rows: ROWS,
  selected: 3,
  onSelect: noop,
  detail: FAILED,
  onRetryTask: noop,
  onSkipTask: noop,
  onExport: noop,
};
const page = (p: Partial<DiagnosticsViewProps>) => (
  <div className="flex h-[900px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">
    <DiagnosticsView {...base} {...p} />
  </div>
);

export const FailedTask: Story = { name: "Failure detail", render: () => page({}) };
export const SuccessTask: Story = { name: "Success detail (AI call)", render: () => page({ selected: 6, detail: DONE_AI }) };
export const RunningTask: Story = { name: "Running detail", render: () => page({ selected: 2, detail: RUNNING }) };
export const FilteredByStatus: Story = { name: "Filtered: failed", render: () => page({ filter: "failed", rows: ROWS.filter((r) => r.status === "failed") }) };
export const NothingSelected: Story = { render: () => page({ selected: null, detail: undefined }) };
export const NoTasks: Story = { render: () => page({ rows: [], selected: null, detail: undefined }) };
export const Loading: Story = { render: () => page({ rows: undefined, selected: null, detail: undefined }) };
export const Exporting: Story = { render: () => page({ exporting: true }) };
export const Light: Story = { globals: { theme: "light" }, render: () => page({}) };
export const ListFailedToLoad: Story = { render: () => page({ rows: undefined, error: true, onRetryLoad: noop, selected: null, detail: undefined }) };
export const DetailLoading: Story = { render: () => page({ detail: undefined }) };
export const DetailFailedToLoad: Story = { render: () => page({ detail: undefined, detailError: true }) };
export const SuccessLight: Story = { globals: { theme: "light" }, render: () => page({ selected: 6, detail: DONE_AI }) };
