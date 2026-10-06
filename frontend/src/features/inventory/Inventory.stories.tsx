import type { Meta, StoryObj } from "@storybook/react-vite";

import { TripContextView, type TripContextViewProps } from "@/features/context/TripContextView";
import { frame } from "@/stories/frames";

import { ClockCheckBody } from "./ClockCheckDialog";
import { COSTA_RICA, DEVICES } from "./fixtures";
import { InventoryView, type InventoryViewProps } from "./InventoryView";

const meta: Meta = { title: "Screens/S5 Inventory, S6 Clock check, S7 Trip context" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const inventory: InventoryViewProps = {
  inv: COSTA_RICA,
  scanning: false,
  frameUrl: (i) => frame(i),
  hidden: new Set(),
  downloadPct: null,
  onShowFiles: noop,
  onHide: noop,
  onDownload: noop,
  onReviewClocks: noop,
  onContinue: noop,
};
const page = (children: React.ReactNode) => <div className="flex h-[900px] w-[1368px] bg-bg">{children}</div>;

export const Inventory: Story = { render: () => page(<InventoryView {...inventory} />) };
export const InventoryScanning: Story = {
  render: () => page(<InventoryView {...inventory} scanning inv={{ ...COSTA_RICA, cameras: COSTA_RICA.cameras.slice(0, 2), attention: [] }} />),
};
export const InventoryAllClear: Story = {
  render: () => page(<InventoryView {...inventory} inv={{ ...COSTA_RICA, attention: [], cameras: COSTA_RICA.cameras.map((c) => ({ ...c, clock: null })) }} />),
};
export const InventoryDownloading: Story = { render: () => page(<InventoryView {...inventory} downloadPct={42} />) };

const dialog = (children: React.ReactNode) => (
  <div className="w-[880px] rounded-[16px] border border-border bg-surface-1 p-6">
    <h2 className="mb-4 text-title text-text">Clock check</h2>
    {children}
  </div>
);
export const ClockCheck: Story = { render: () => dialog(<ClockCheckBody devices={DEVICES} frameUrl={(i) => frame(i)} onApply={noop} onSkip={noop} />) };
export const ClockCheckNoSuggestions: Story = {
  render: () => dialog(<ClockCheckBody devices={DEVICES.map((d) => ({ ...d, suggestion: null }))} frameUrl={(i) => frame(i)} onApply={noop} onSkip={noop} />),
};
export const ClockCheckAllConsistent: Story = {
  render: () => dialog(<ClockCheckBody devices={[DEVICES[0]!, DEVICES[3]!, DEVICES[4]!]} frameUrl={(i) => frame(i)} onApply={noop} onSkip={noop} />),
};

const context: TripContextViewProps = {
  value: { trip_name: "", days: [], people: [], must_include: [], avoid: [], free_notes: "" },
  onChange: noop,
  footageDays: COSTA_RICA.days.map((d) => d.date),
  highlights: new Set(),
  tab: "details",
  onTab: noop,
  paste: "",
  onPaste: noop,
  parsing: false,
  parseError: null,
  onParse: noop,
  saving: false,
  onSave: noop,
  onSkip: noop,
};
const parsed = {
  trip_name: "Costa Rica 2026",
  days: [
    { date: "2026-07-14", place: "San José → La Fortuna", notes: "Arrival, long drive" },
    { date: "2026-07-15", place: "Arenal / La Fortuna waterfall", notes: "Hike to waterfall" },
    { date: "2026-07-16", place: "Arenal hanging bridges", notes: "Toucan at breakfast" },
    { date: "2026-07-17", place: "Sky Adventures zipline", notes: "Kids' first zipline" },
    { date: "2026-07-18", place: "Río Celeste", notes: "Blue river hike" },
    { date: "2026-07-19", place: "Drive to Monteverde", notes: "Rainy" },
    { date: "2026-07-20", place: "Monteverde cloud forest", notes: "Night tour" },
  ],
  people: [
    { label: "Anna", description: "wife, wide straw hat" },
    { label: "Leo", description: "older son, 12, blue cap" },
    { label: "Maya", description: "younger daughter, 8, yellow raincoat" },
  ],
  must_include: ["the toucan at breakfast", "Maya's first zipline"],
  avoid: ["car interiors"],
  free_notes: "Celebrating our 20th anniversary.",
};
export const TripContextEmpty: Story = { render: () => page(<TripContextView {...context} />) };
export const TripContextPaste: Story = {
  render: () => page(<TripContextView {...context} tab="paste" paste={"Day 1 San José → La Fortuna\nDay 2 waterfall hike"} />),
};
export const TripContextParsing: Story = {
  render: () => page(<TripContextView {...context} tab="paste" paste={"Day 1 San José → La Fortuna\nDay 2 waterfall hike"} parsing />),
};
export const TripContextParsed: Story = {
  render: () =>
    page(
      <TripContextView
        {...context}
        value={parsed}
        highlights={new Set(["day:2026-07-15", "day:2026-07-16", "day:2026-07-17", "day:2026-07-18"])}
      />,
    ),
};
export const TripContextPartial: Story = {
  render: () => page(<TripContextView {...context} value={{ ...context.value, trip_name: "Costa Rica 2026", days: parsed.days.slice(0, 2) }} />),
};
