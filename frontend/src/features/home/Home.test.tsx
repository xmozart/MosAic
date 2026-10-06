import { fireEvent, render, screen } from "@testing-library/react";

import { CreateProjectDialog } from "@/features/open/CreateProjectDialog";
import { FolderBrowserView } from "@/features/open/FolderBrowserDialog";
import { formatDateRange, formatDuration, formatOpened } from "@/lib/format";

import { ProjectCard, type ProjectCardData } from "./ProjectCard";

const card: ProjectCardData = {
  name: "Trip",
  placement: "in_folder",
  cover: [],
  firstDate: "2026-07-14",
  lastDate: "2026-07-24",
  footageSeconds: 22320,
  clips: 412,
  photos: 1180,
  status: { state: "analyzing", pct: 42 },
  latestEdit: null,
  opened: "Today",
  missing: false,
};

describe("formats", () => {
  it("writes dates, durations and opened days like the reference", () => {
    expect(formatDateRange("2026-07-14", "2026-07-24")).toBe("Jul 14–24, 2026");
    expect(formatDateRange("2026-03-28", "2026-04-02")).toBe("Mar 28 – Apr 2, 2026");
    expect(formatDuration(22320)).toBe("6 h 12 m");
    expect(formatOpened("2026-10-06T10:00:00", new Date("2026-10-06T18:00:00"))).toBe("Today");
    expect(formatOpened("2026-10-05T10:00:00", new Date("2026-10-06T08:00:00"))).toBe("Yesterday");
  });
});

describe("ProjectCard", () => {
  it("shows facts, a progress ring while analysing, and a missing state", () => {
    const { rerender } = render(<ProjectCard data={card} onOpen={() => {}} onRemove={() => {}} />);
    expect(screen.getByText("Jul 14–24, 2026 · 6 h 12 m · 412 clips · 1,180 photos")).toBeInTheDocument();
    expect(screen.getAllByText("42%").length).toBeGreaterThan(0);
    const remove = vi.fn();
    const open = vi.fn();
    rerender(<ProjectCard data={{ ...card, missing: true }} onOpen={open} onReconnect={() => {}} onRemove={remove} />);
    expect(screen.getByText("Folder not found")).toBeInTheDocument();
    const cover = screen.getByLabelText("Trip: folder not found");
    expect(cover).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(cover); // stays focusable for the arrow-key grid, but does not open
    fireEvent.click(screen.getByRole("button", { name: "Remove from list" }));
    expect(remove).toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
  });
});

describe("FolderBrowserView", () => {
  it("moves with the arrows, enters with →, goes up with ← and opens with Enter", () => {
    const calls: string[] = [];
    const listing = {
      root: { id: 1, label: "root" },
      path: "a",
      crumbs: [
        { name: "root", path: "" },
        { name: "a", path: "a" },
      ],
      items: [
        { name: "x", path: "a/x", counts: null, has_project: false },
        { name: "y", path: "a/y", counts: { videos: 2, photos: 0, complete: true }, has_project: true },
      ],
    };
    let selected: string | null = null;
    const { rerender } = render(
      <FolderBrowserView
        roots={[{ id: 1, label: "root" }]}
        root={1}
        listing={listing}
        selected={selected}
        onRoot={() => {}}
        onEnter={(p) => calls.push(`enter:${p}`)}
        onSelect={(p) => (selected = p)}
        onOpen={() => calls.push("open")}
        onCancel={() => {}}
      />,
    );
    const list = screen.getByRole("listbox");
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(selected).toBe("a/x");
    rerender(
      <FolderBrowserView roots={[{ id: 1, label: "root" }]} root={1} listing={listing} selected="a/x" onRoot={() => {}} onEnter={(p) => calls.push(`enter:${p}`)} onSelect={(p) => (selected = p)} onOpen={() => calls.push("open")} onCancel={() => {}} />,
    );
    fireEvent.keyDown(list, { key: "ArrowDown" });
    expect(selected).toBe("a/y");
    fireEvent.keyDown(list, { key: "ArrowRight" });
    fireEvent.keyDown(list, { key: "ArrowLeft" });
    fireEvent.keyDown(list, { key: "Enter" });
    expect(calls).toEqual(["enter:a/x", "enter:", "open"]);
    expect(screen.getByText("MosAic project")).toBeInTheDocument();
    expect(list).toHaveAttribute("aria-activedescendant");
    fireEvent.keyDown(screen.getByRole("button", { name: "Cancel" }), { key: "Enter" });
    expect(calls).toEqual(["enter:a/x", "enter:", "open"]); // Enter on Cancel doesn't open
    expect(screen.getByText("2 videos")).toBeInTheDocument();
  });
});

describe("CreateProjectDialog", () => {
  const preview = { where: "/Movies/Trip", name: "Trip", placement: "split" as const, counts: { videos: 4, photos: 2, folders: 1, complete: true } };

  it("highlights the placement that applies and keeps the promise verbatim", () => {
    render(<CreateProjectDialog open preview={preview} onCreate={() => {}} onCancel={() => {}} />);
    const current = document.querySelector("[aria-current=true]");
    expect(current).toHaveTextContent("If on a network drive or iCloud");
    expect(screen.getByText("Original footage stays where it is and will not be modified.")).toBeInTheDocument();
    expect(screen.getByText("Found 4 videos and 2 photos in 2 folders")).toBeInTheDocument();
  });

  it("an empty folder offers to choose another", () => {
    render(
      <CreateProjectDialog open preview={{ ...preview, counts: { videos: 0, photos: 0, folders: 0, complete: true } }} onCreate={() => {}} onCancel={() => {}} />,
    );
    expect(screen.getByText("No videos or photos here.")).toBeInTheDocument();
    expect(screen.getByText("Choose another")).toBeInTheDocument();
    expect(screen.queryByText("Create project", { selector: "button" })).toBeNull();
  });
});
