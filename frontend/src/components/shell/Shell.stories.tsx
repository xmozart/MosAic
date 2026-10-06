import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect, useState, type ReactNode } from "react";

import { Toaster } from "@/components/ui/Toast";
import {
  CostCeilingDialog,
  FilesMovedDialog,
  LeaseLostDialog,
  OpenElsewhereDialog,
  ReadOnlyBanner,
  UnsavedDraftDialog,
} from "@/features/shell/dialogs";
import type { JobSummary } from "@/lib/activity";
import { useToasts } from "@/lib/toasts";

import { ActivityPopover } from "./ActivityPopover";
import { AppRail } from "./AppRail";
import { CommandPalette } from "./CommandPalette";
import { ProjectHeader } from "./ProjectHeader";

const meta: Meta = { title: "Shell", parameters: { layout: "fullscreen" } };
export default meta;
type Story = StoryObj;

const link = (href: string, children: ReactNode, className: string, label: string) => (
  <a href={href} className={className} aria-label={label} onClick={(e) => e.preventDefault()}>
    {children}
  </a>
);
const links = { home: "/", library: "/p/1/library", edits: "/p/1/edits", exports: "/exports", settings: "/settings" };
const noop = () => {};

const JOBS: JobSummary[] = [
  { jobId: 1, projectId: "p1", kind: "analysis", state: "running", pct: 42, stage: "vision", item: "GX030211.MP4 · sheet 96 of 214", cost: 1.34 },
  { jobId: 2, projectId: "p2", kind: "render", state: "paused", pct: 10, stage: "render", item: null, cost: 0 },
];

export const RailIdleAndRunning: Story = {
  render: () => (
    <div className="flex h-[640px] gap-8">
      <AppRail active="home" activityPct={null} links={links} renderLink={link} theme="dark" onToggleTheme={noop} />
      <AppRail active="library" activityPct={42} links={links} renderLink={link} theme="dark" onToggleTheme={noop} />
      <AppRail active="home" activityPct={null} links={{ home: "/", exports: "/exports", settings: "/settings" }} renderLink={link} theme="light" onToggleTheme={noop} />
    </div>
  ),
};

export const Activity: Story = {
  render: () => (
    <div className="flex h-[640px] items-end p-8">
      <ActivityPopover jobs={JOBS} projectNames={{ p1: "Costa Rica 2026", p2: "Iceland" }} onPause={noop} onResume={noop} onCancel={noop} defaultOpen>
        <button type="button" className="size-11 rounded-full bg-surface-2">42</button>
      </ActivityPopover>
    </div>
  ),
};

export const HeaderStatuses: Story = {
  render: () => (
    <div className="flex flex-col">
      <ProjectHeader name="Costa Rica 2026" placement="in_folder" status={{ state: "analyzing", pct: 42 }} aiCost="AI $1.34" onSearch={noop} onRename={noop} />
      <ProjectHeader name="Costa Rica 2026" placement="split_nas" status={{ state: "analyzed", mode: "balanced" }} aiCost="AI $3.10" onSearch={noop} onRename={noop} />
      <ProjectHeader name="Iceland" placement="split_icloud" status={{ state: "preliminary" }} onSearch={noop} />
      <ProjectHeader name="Lisbon" placement="separate" status={{ state: "scanned" }} onSearch={noop} />
      <ProjectHeader name="Rome" placement="external_drive" status={{ state: "not_analyzed" }} onSearch={noop} />
      <ProjectHeader name="Read-only trip" placement="in_folder" status={{ state: "analyzed" }} readOnly onSearch={noop} />
      <ReadOnlyBanner reason="This project is open on another computer. You can look, but changes are off." />
    </div>
  ),
};

export const Palette: Story = {
  render: () => (
    <CommandPalette
      open
      onOpenChange={noop}
      onSearch={noop}
      commands={[
        { id: "1", label: "DSC_1044.MOV — three-toed sloth", kind: "Clip", run: noop },
        { id: "2", label: "Create edit", kind: "Action", run: noop },
        { id: "3", label: "Deepen analysis…", kind: "Action", run: noop },
        { id: "4", label: "Render final", kind: "Action", run: noop },
      ]}
    />
  ),
};

export const DialogOpenElsewhere: Story = {
  render: () => <OpenElsewhereDialog open project="Costa Rica 2026" host="Michael's MacBook Pro" since="13:40" onReadOnly={noop} onTakeOver={noop} onCancel={noop} />,
};
export const DialogCostCeiling: Story = {
  render: () => <CostCeilingDialog open limit={10} remaining="About $2.40 more to finish." onRaise={noop} onKeepPaused={noop} />,
};
export const DialogFilesMoved: Story = {
  render: () => <FilesMovedDialog open missing={18} found={17} where="/Volumes/Travel/Costa_Rica_2026" onRelink={noop} onChoose={noop} onSkip={noop} />,
};
export const DialogUnsavedDraft: Story = {
  render: () => <UnsavedDraftDialog open summary="You trimmed 3 shots and reordered the Wildlife beat." nextVersion={4} onSave={noop} onDiscard={noop} onCancel={noop} />,
};
export const DialogLeaseLost: Story = {
  render: () => <LeaseLostDialog open project="Costa Rica 2026" onReadOnly={noop} onClose={noop} />,
};

export const Toasts: Story = {
  render: function Render() {
    const push = useToasts((s) => s.push);
    const [done, setDone] = useState(false);
    useEffect(() => {
      if (done) return;
      setDone(true);
      push({ kind: "success", message: "Version 3 created", action: { label: "Undo", run: noop } });
      push({ kind: "error", message: "Couldn't read GX020201.MP4. It looks damaged." });
    }, [done, push]);
    return <Toaster />;
  },
};
