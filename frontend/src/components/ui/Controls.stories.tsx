import type { Meta, StoryObj } from "@storybook/react-vite";
import { MoreHorizontal, Plus, Search, Trash2 } from "lucide-react";
import { useState } from "react";

import { Button } from "./Button";
import { Kbd } from "./Kbd";
import { Segmented } from "./Segmented";
import { SwitchRow } from "./Switch";
import { TextField } from "./TextField";

const meta: Meta = { title: "Design system/Controls" };
export default meta;
type Story = StoryObj;

export const Buttons: Story = {
  render: () => (
    <div className="flex flex-wrap items-center gap-3">
      <Button variant="primary">
        <Plus /> Create edit
      </Button>
      <Button>Analyze</Button>
      <Button variant="ghost">Skip</Button>
      <Button variant="danger">
        <Trash2 /> Remove data
      </Button>
      <Button variant="primary" size="sm">
        Render
      </Button>
      <Button size="icon" aria-label="More">
        <MoreHorizontal />
      </Button>
      <Button variant="primary" disabled>
        Disabled
      </Button>
    </div>
  ),
};

export const Inputs: Story = {
  render: function Render() {
    const [c, setC] = useState<"strict" | "mostly" | "thematic" | "story">("mostly");
    return (
      <div className="flex items-end gap-5">
        <TextField className="w-80" label="Search" icon={<Search />} placeholder="Try “monkeys in trees”" />
        <TextField className="w-40" label="Cost limit" mono defaultValue="$10.00" />
        <TextField className="w-60" label="Media root" error="This folder isn't inside a media root." defaultValue="/etc" />
        <div className="flex flex-col gap-1.5">
          <span className="text-caption text-text-muted">Chronology</span>
          <Segmented
            label="Chronology"
            value={c}
            onChange={setC}
            options={[
              { value: "strict", label: "Strict" },
              { value: "mostly", label: "Mostly" },
              { value: "thematic", label: "Thematic" },
              { value: "story", label: "Story-driven" },
            ]}
          />
        </div>
      </div>
    );
  },
};

export const Switches: Story = {
  render: function Render() {
    const [a, setA] = useState(true);
    const [b, setB] = useState(false);
    return (
      <div className="flex w-80 flex-col gap-3.5">
        <SwitchRow label="Keep dialogue" description="Never cut mid-sentence" checked={a} onChange={setA} />
        <SwitchRow label="Reduce wind noise" checked={b} onChange={setB} />
        <SwitchRow label="Disabled" checked={false} onChange={() => {}} disabled />
      </div>
    );
  },
};

export const Keys: Story = {
  render: () => (
    <div className="flex gap-2">
      <Kbd>U</Kbd>
      <Kbd>M</Kbd>
      <Kbd>R</Kbd>
      <Kbd>1–5</Kbd>
      <Kbd>⌘K</Kbd>
      <Kbd>/</Kbd>
    </div>
  ),
};
