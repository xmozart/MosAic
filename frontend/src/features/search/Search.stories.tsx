import type { Meta, StoryObj } from "@storybook/react-vite";

import { frame } from "@/stories/frames";

import { RESULTS, SUGGESTIONS } from "./fixtures";
import { SearchView, type SearchViewProps } from "./SearchView";

const meta: Meta = { title: "Screens/S12 Search" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const base: SearchViewProps = {
  query: "people laughing",
  mode: "all",
  items: RESULTS,
  visual: "ok",
  suggestions: SUGGESTIONS,
  frameUrl: (i) => frame(i),
  onSearch: noop,
  onMode: noop,
  onOpen: noop,
};
const page = (p: Partial<SearchViewProps>) => (
  <div className="flex h-[900px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">
    <SearchView {...base} {...p} />
  </div>
);

export const Results: Story = { render: () => page({}) };
export const NoResults: Story = { render: () => page({ query: "penguins", items: [] }) };
export const AnalysisIncomplete: Story = { render: () => page({ visual: "unavailable", items: RESULTS.slice(0, 4) }) };
export const Searching: Story = { render: () => page({ items: undefined }) };
export const Light: Story = { globals: { theme: "light" }, render: () => page({}) };
export const Idle: Story = { render: () => page({ query: "", items: undefined }) };
export const Failed: Story = { render: () => page({ items: undefined, error: true, onRetry: noop }) };
