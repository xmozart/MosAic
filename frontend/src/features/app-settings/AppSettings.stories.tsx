import type { Meta, StoryObj } from "@storybook/react-vite";

import { AppSettingsView, type AppSettingsViewProps } from "./AppSettingsView";
import { NO_KEY, OPTIONS, PROVIDERS, ROOTS, SETTINGS, SYSTEM } from "./fixtures";

const meta: Meta = { title: "Screens/S22 App settings" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const base: AppSettingsViewProps = {
  theme: "system",
  onTheme: noop,
  settings: SETTINGS,
  onSetting: noop,
  providers: PROVIDERS,
  options: OPTIONS,
  onProvider: noop,
  keyChecks: {},
  onSaveKey: async () => {},
  onValidateKey: noop,
  onRemoveKey: noop,
  system: SYSTEM,
  trip: { name: "Costa Rica 2026", onOpen: noop },
};
const page = (p: Partial<AppSettingsViewProps>) => (
  <div className="flex h-[1400px] w-[1368px] overflow-hidden rounded-lg border border-border bg-bg">
    <AppSettingsView {...base} {...p} />
  </div>
);

export const Settings: Story = { render: () => page({}) };
export const KeyMissing: Story = { render: () => page({ providers: NO_KEY }) };
export const KeyInvalid: Story = { render: () => page({ keyChecks: { anthropic: "invalid" } }) };
export const KeyFromDeployment: Story = {
  render: () =>
    page({
      providers: Object.fromEntries(
        Object.entries(PROVIDERS).map(([k, v]) => [k, v.key ? { ...v, key: { configured: true, last4: "WXYZ", store: "docker" as const, from_deployment: true } } : v]),
      ),
    }),
};
export const LocalOnly: Story = { render: () => page({ settings: { ...SETTINGS, "ai.local_only": { value: true, source: "user" } } }) };
export const ServerWithMediaRoots: Story = { render: () => page({ roots: ROOTS, onAddRoot: noop, onRemoveRoot: noop }) };
export const Loading: Story = { render: () => page({ settings: undefined, providers: undefined, options: undefined, system: undefined }) };
export const Light: Story = { globals: { theme: "light" }, render: () => page({}) };
export const LocalOnlyLight: Story = { globals: { theme: "light" }, render: () => page({ settings: { ...SETTINGS, "ai.local_only": { value: true, source: "user" } } }) };
export const KeyMissingLight: Story = { globals: { theme: "light" }, render: () => page({ providers: NO_KEY }) };
export const KeyInvalidLight: Story = { globals: { theme: "light" }, render: () => page({ keyChecks: { anthropic: "invalid" } }) };
