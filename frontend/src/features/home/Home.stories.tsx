import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

import { CreateProjectDialog } from "@/features/open/CreateProjectDialog";
import { FolderBrowserView } from "@/features/open/FolderBrowserDialog";
import { PathDialog } from "@/features/open/PathDialog";
import { frame } from "@/stories/frames";

import { HomeEmpty } from "./HomeScreen";
import { ProjectCard, type ProjectCardData } from "./ProjectCard";

const meta: Meta = { title: "Screens/S3 Home and S4 Open folder" };
export default meta;
type Story = StoryObj;

const noop = () => {};
const base: ProjectCardData = {
  name: "Costa Rica 2026",
  placement: "in_folder",
  cover: [frame(0), frame(1), frame(2)],
  firstDate: "2026-07-14",
  lastDate: "2026-07-24",
  footageSeconds: 6 * 3600 + 12 * 60,
  clips: 412,
  photos: 1180,
  status: { state: "analyzed", mode: "balanced" },
  latestEdit: "5-min cinematic · v3",
  opened: "Today",
  missing: false,
};

export const Cards: Story = {
  render: () => (
    <div className="grid w-[1100px] grid-cols-3 gap-6">
      <ProjectCard data={base} onOpen={noop} onRemove={noop} />
      <ProjectCard
        data={{ ...base, name: "Iceland Ring Road", placement: "split_nas", cover: [frame(3), frame(4), frame(1)], firstDate: "2026-03-02", lastDate: "2026-03-12", footageSeconds: 13200, clips: 238, photos: 610, status: { state: "analyzing", pct: 42 }, latestEdit: null, opened: "Yesterday" }}
        onOpen={noop}
        onRemove={noop}
      />
      <ProjectCard
        data={{ ...base, name: "Lisbon weekend", placement: "split_icloud", status: { state: "analyzed", mode: "quick" }, latestEdit: "60 s reel · v1", opened: "Oct 2" }}
        onOpen={noop}
        onRemove={noop}
      />
      <ProjectCard
        data={{ ...base, name: "Banff 2025", placement: "external_drive", missing: true, photos: 0, opened: "Aug 7" }}
        onOpen={noop}
        onReconnect={noop}
        onRemove={noop}
      />
      <ProjectCard
        data={{ ...base, name: "New trip", cover: [], status: { state: "scanned" }, footageSeconds: 0, clips: 12, photos: 3, firstDate: null, lastDate: null, latestEdit: null }}
        onOpen={noop}
        onRemove={noop}
      />
    </div>
  ),
};

const LISTING = {
  root: { id: 1, label: "/media/travel" },
  path: "2026",
  crumbs: [
    { name: "/media/travel", path: "" },
    { name: "2026", path: "2026" },
  ],
  items: [
    { name: "Costa_Rica_2026", path: "2026/Costa_Rica_2026", counts: { videos: 412, photos: 1180, complete: true }, has_project: false },
    { name: "Iceland_2026", path: "2026/Iceland_2026", counts: { videos: 238, photos: 610, complete: true }, has_project: true },
    { name: "Family_2024", path: "2026/Family_2024", counts: { videos: 0, photos: 1020, complete: true }, has_project: false },
    { name: "Drone_raw", path: "2026/Drone_raw", counts: null, has_project: false },
  ],
};

export const FolderBrowser: Story = {
  render: function Render() {
    const [sel, setSel] = useState<string | null>("2026/Costa_Rica_2026");
    return (
      <div className="w-[720px] rounded-[16px] border border-border bg-surface-1 p-6">
        <FolderBrowserView
          roots={[{ id: 1, label: "/media/travel" }, { id: 2, label: "/media/archive" }]}
          root={1}
          listing={LISTING}
          selected={sel}
          onRoot={noop}
          onEnter={noop}
          onSelect={setSel}
          onOpen={noop}
          onCancel={noop}
        />
      </div>
    );
  },
};

const PREVIEW = {
  where: "/Users/michael/Movies/Costa_Rica_2026",
  name: "Costa_Rica_2026",
  placement: "in_folder" as const,
  counts: { videos: 412, photos: 1180, folders: 8, complete: true },
};

export const ConfirmLocal: Story = { render: () => <CreateProjectDialog open preview={PREVIEW} onCreate={noop} onCancel={noop} /> };
export const ConfirmNetwork: Story = {
  render: () => <CreateProjectDialog open preview={{ ...PREVIEW, placement: "split" }} onCreate={noop} onCancel={noop} />,
};
export const ConfirmReadOnly: Story = {
  render: () => <CreateProjectDialog open preview={{ ...PREVIEW, placement: "external" }} onCreate={noop} onCancel={noop} />,
};
export const ConfirmEmptyFolder: Story = {
  render: () => (
    <CreateProjectDialog open preview={{ ...PREVIEW, counts: { videos: 0, photos: 0, folders: 0, complete: true } }} onCreate={noop} onCancel={noop} />
  ),
};
export const DesktopPath: Story = { render: () => <PathDialog open onPick={noop} onCancel={noop} /> };
export const DesktopPathError: Story = {
  render: () => <PathDialog open error="That folder doesn't exist." onPick={noop} onCancel={noop} />,
};

export const Empty: Story = {
  render: () => (
    <div className="flex h-[700px] w-[1200px] bg-bg">
      <HomeEmpty onOpenFolder={noop} onOpenProject={noop} />
    </div>
  ),
};
