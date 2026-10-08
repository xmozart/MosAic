import type { Meta, StoryObj } from "@storybook/react-vite";

import { renderRow } from "@/features/preview/fixtures";
import { frame } from "@/stories/frames";

import { ExportsView, type ExportsViewProps } from "./ExportsView";
import { ROWS } from "./fixtures";

const meta: Meta = { title: "Screens/S20 Exports" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const base: ExportsViewProps = {
  folder: "Costa_Rica_2026/MosAic/renders",
  items: ROWS,
  coverUrl: (i) => frame(i),
  fileUrl: () => "#file",
  onCancel: noop,
  onRerender: noop,
  onDeleteFile: noop,
  onEdits: noop,
};
const page = (p: Partial<ExportsViewProps>) => (
  <div className="flex h-[900px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">
    <ExportsView {...base} {...p} />
  </div>
);

export const Queue: Story = { name: "Queue and history", render: () => page({}) };
export const MorePages: Story = { render: () => page({ hasMore: true, onMore: noop }) };
export const AfterCancelAndDelete: Story = {
  name: "Cancelled, deleted and missing",
  render: () =>
    page({
      items: [
        renderRow(9, { kind: "final", status: "cancelled", size_bytes: null, seconds: null, file: null }),
        renderRow(8, { status: "deleted", size_bytes: null, file: null }),
        renderRow(7, { kind: "final", status: "missing", size_bytes: null, file: null }),
        renderRow(6, { kind: "final", status: "paused", pct: 40, size_bytes: null, seconds: null, file: null }),
      ],
    }),
};
export const Empty: Story = { render: () => page({ items: [] }) };
export const Loading: Story = { render: () => page({ items: undefined }) };
export const Failed: Story = { name: "Failed to load", render: () => page({ items: undefined, error: true, onRetry: noop }) };
export const Light: Story = { globals: { theme: "light" }, render: () => page({}) };
