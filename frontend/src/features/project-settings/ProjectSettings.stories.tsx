import type { Meta, StoryObj } from "@storybook/react-vite";

import { CONTEXT, DEVICES, SETTINGS, STORAGE } from "./fixtures";
import { ProjectSettingsView, type ProjectSettingsViewProps } from "./ProjectSettingsView";

const meta: Meta = { title: "Screens/S21 Project settings" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const base: ProjectSettingsViewProps = {
  name: "Costa Rica 2026",
  folder: "/Volumes/Travel/Costa_Rica_2026",
  placement: "in_folder",
  onRename: noop,
  settings: SETTINGS,
  onSetting: noop,
  onAnalysisSetup: noop,
  devices: DEVICES,
  onCheckClocks: noop,
  context: CONTEXT,
  onEditContext: noop,
  storage: STORAGE,
  onClear: noop,
  onRemove: noop,
};
const page = (p: Partial<ProjectSettingsViewProps>) => (
  <div className="flex h-[900px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">
    <ProjectSettingsView {...base} {...p} />
  </div>
);

export const Settings: Story = { render: () => page({}) };
export const Clearing: Story = { render: () => page({ clearing: true }) };
export const NothingToClear: Story = {
  render: () => page({ storage: { ...STORAGE, regenerable_bytes: 0, groups: STORAGE.groups.map((g) => (g.regenerable ? { ...g, bytes: 0 } : g)) } }),
};
export const Loading: Story = { render: () => page({ settings: undefined, devices: undefined, context: undefined, storage: undefined }) };
export const ReadOnly: Story = { render: () => page({ readOnly: true }) };
export const NoContextNoCameras: Story = { render: () => page({ devices: [], context: { ...CONTEXT, trip_name: "", days: [], people: [], must_include: [] } }) };
export const Light: Story = { globals: { theme: "light" }, render: () => page({}) };
export const ClearConfirmation: Story = { name: "Clear confirmation (space freed, what is kept)", render: () => page({ initialDialog: "clear" }) };
export const RemoveConfirmation: Story = { name: "Remove confirmation (type the name)", render: () => page({ initialDialog: "remove" }) };
export const ClearConfirmationLight: Story = { globals: { theme: "light" }, render: () => page({ initialDialog: "clear" }) };
export const RemoveConfirmationLight: Story = { globals: { theme: "light" }, render: () => page({ initialDialog: "remove" }) };
export const ReadOnlyLight: Story = { globals: { theme: "light" }, render: () => page({ readOnly: true }) };
