import type { Meta, StoryObj } from "@storybook/react-vite";

import { FirstRunView, type FirstRunViewProps } from "./FirstRunView";
import type { ModelRow } from "./model";

const meta: Meta = { title: "Screens/S1 First run", parameters: { layout: "fullscreen" } };
export default meta;
type Story = StoryObj;

const noop = () => {};
const speech: ModelRow = {
  name: "whisper-medium",
  label: "Speech",
  capability: "transcriber",
  provider: "faster-whisper",
  model: "medium",
  bytes: 1_530_571_735,
  downloaded_bytes: 979_565_910,
  installed: false,
  needed: true,
  job: { job_id: 4, state: "running", pct: 64 },
};
const image: ModelRow = {
  name: "siglip-base",
  label: "Image understanding",
  capability: "embedder",
  provider: "siglip-onnx",
  model: "base",
  bytes: 815_550_726,
  downloaded_bytes: 815_550_726,
  installed: true,
  needed: true,
  job: null,
};
const base: FirstRunViewProps = {
  step: 1,
  onStep: noop,
  mode: "hybrid",
  onMode: noop,
  providers: [
    { id: "anthropic", label: "Anthropic" },
    { id: "openai", label: "OpenAI" },
  ],
  provider: "anthropic",
  onProvider: noop,
  onSaveKey: async () => {},
  onValidateKey: noop,
  models: [speech, image],
  onRetry: noop,
  onFinish: noop,
};
const view = (p: Partial<FirstRunViewProps>) => <FirstRunView {...base} {...p} />;

export const Welcome: Story = { render: () => view({}) };
export const AiMode: Story = { render: () => view({ step: 2 }) };
export const AiModeKeyConnected: Story = { render: () => view({ step: 2, keyLast4: "7F3A", keyStatus: "ok" }) };
export const AiModeKeyInvalid: Story = { render: () => view({ step: 2, keyLast4: "7F3A", keyStatus: "invalid" }) };
export const AiModeLocalOnly: Story = { render: () => view({ step: 2, mode: "local" }) };
export const ModelsDownloading: Story = { render: () => view({ step: 3 }) };
export const ModelsPausedOffline: Story = {
  render: () => view({ step: 3, models: [{ ...speech, job: { job_id: 4, state: "failed", pct: 64 } }, image] }),
};
export const ModelsReady: Story = {
  render: () => view({ step: 3, models: [{ ...speech, installed: true, downloaded_bytes: speech.bytes, job: null }, image] }),
};
