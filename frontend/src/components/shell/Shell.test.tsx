import { act, fireEvent, render, screen } from "@testing-library/react";

import { CostCeilingDialog, LeaseLostDialog } from "@/features/shell/dialogs";
import { overall, useActivity } from "@/lib/activity";

import { AppRail } from "./AppRail";
import { CommandPalette } from "./CommandPalette";
import { ProjectHeader } from "./ProjectHeader";

const job = (jobId: number, pct: number, state = "running") => ({
  jobId,
  projectId: "p",
  kind: "analysis",
  state,
  pct,
  stage: null,
  item: null,
  cost: 0,
});

describe("activity", () => {
  beforeEach(() => useActivity.setState({ jobs: {}, lost: [] }));

  it("tracks running jobs and drops finished ones", () => {
    const s = useActivity.getState();
    s.upsert(job(1, 40));
    s.upsert(job(2, 60));
    expect(overall(Object.values(useActivity.getState().jobs))).toBe(50);
    useActivity.getState().setState(1, "done");
    expect(Object.keys(useActivity.getState().jobs)).toEqual(["2"]);
    expect(overall([])).toBeNull();
  });

  it("remembers projects taken over elsewhere", () => {
    useActivity.getState().markLost("p1");
    useActivity.getState().markLost("p1");
    expect(useActivity.getState().lost).toEqual(["p1"]);
  });
});

describe("AppRail", () => {
  it("names the activity ring and disables places without a project", () => {
    render(
      <AppRail
        active="home"
        activityPct={42}
        links={{ home: "/" }}
        renderLink={(href, children, className, label) => (
          <a href={href} className={className} aria-label={label}>
            {children}
          </a>
        )}
        theme="dark"
        onToggleTheme={() => {}}
      />,
    );
    expect(screen.getByLabelText("Background activity: 42%")).toBeInTheDocument();
    expect(screen.getByText("Library").parentElement).toHaveAttribute("aria-disabled");
  });
});

describe("CommandPalette", () => {
  it("filters, moves with the arrows and runs with Enter", () => {
    const ran: string[] = [];
    render(
      <CommandPalette
        open
        onOpenChange={() => {}}
        onSearch={(q) => ran.push(`search:${q}`)}
        commands={[
          { id: "a", label: "Create edit", kind: "Action", run: () => ran.push("edit") },
          { id: "b", label: "Deepen analysis…", kind: "Action", run: () => ran.push("deepen") },
        ]}
      />,
    );
    const input = screen.getByRole("combobox");
    fireEvent.change(input, { target: { value: "e" } });
    fireEvent.keyDown(input, { key: "ArrowDown" });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(ran).toEqual(["edit"]);
  });
});

describe("dialogs", () => {
  it("raises the cost limit only above the current one", () => {
    const raised: number[] = [];
    render(<CostCeilingDialog open limit={10} onRaise={(n) => raised.push(n)} onKeepPaused={() => {}} />);
    const field = screen.getByLabelText("New limit");
    fireEvent.change(field, { target: { value: "8" } });
    expect(screen.getByText("Raise limit").closest("button")).toBeDisabled();
    fireEvent.change(field, { target: { value: "$25" } });
    fireEvent.click(screen.getByText("Raise limit"));
    expect(raised).toEqual([25]);
  });

  it("a lost lease cannot be dismissed with Esc", () => {
    const readOnly = vi.fn();
    render(<LeaseLostDialog open project="Trip" onReadOnly={readOnly} onClose={() => {}} />);
    fireEvent.keyDown(document.activeElement ?? document.body, { key: "Escape" });
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Continue read-only"));
    expect(readOnly).toHaveBeenCalled();
  });
});

describe("ProjectHeader", () => {
  it("renames inline and shows the status", async () => {
    const names: string[] = [];
    render(
      <ProjectHeader
        name="Trip"
        placement="in_folder"
        status={{ state: "analyzing", pct: 42 }}
        onRename={(n) => names.push(n)}
        onSearch={() => {}}
      />,
    );
    expect(screen.getByText("Analyzing 42%")).toBeInTheDocument();
    fireEvent.click(screen.getByText("Trip"));
    const input = screen.getByLabelText("Project name");
    fireEvent.change(input, { target: { value: "Costa Rica" } });
    await act(async () => fireEvent.keyDown(input, { key: "Enter" }));
    expect(names).toEqual(["Costa Rica"]);
  });
});
