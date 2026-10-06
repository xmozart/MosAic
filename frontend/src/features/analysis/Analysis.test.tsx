import { fireEvent, render, screen, within } from "@testing-library/react";

import { estimateLine, formatCost, formatWall } from "@/lib/estimate";

import { AnalysisProgressView, type AnalysisProgressViewProps } from "./AnalysisProgressView";
import { AnalysisSetupView, type AnalysisSetupViewProps } from "./AnalysisSetupView";
import { DeepenBody, type DeepenBodyProps } from "./DeepenDialog";
import { ESTIMATES, JOB, PROGRESS, SETTINGS } from "./fixtures";
import { timeLeft } from "./model";

const noop = () => {};

describe("estimate formats", () => {
  it("match the mode cards", () => {
    expect(estimateLine(ESTIMATES.quick)).toBe("About 35 min · $0.80–1.50 · 6 GB");
    expect(estimateLine(ESTIMATES.balanced)).toBe("About 1 h 40 m · $2–4 · 18 GB");
    expect(formatCost(null)).toBe("AI cost unknown");
    expect(formatCost([0, 0])).toBe("No AI cost");
    expect(formatWall([3000, 3600])).toBe("About 55 min");
    expect(timeLeft(58 * 60_000)).toBe("About 58 min left");
  });
});

describe("AnalysisSetupView", () => {
  const props: AnalysisSetupViewProps = {
    selected: "balanced",
    onSelect: noop,
    estimates: ESTIMATES,
    settings: SETTINGS,
    edited: new Set(),
    onEdit: noop,
    sceneModel: "anthropic · claude-haiku-4-5",
    storyModel: "anthropic · claude-sonnet-5-5",
    device: "Auto · Apple M4",
    localOnly: false,
    starting: false,
    onBack: noop,
    onAnalyze: noop,
  };

  it("offers three modes with estimates, Balanced recommended, and a footer summary", () => {
    const select = vi.fn();
    render(<AnalysisSetupView {...props} onSelect={select} />);
    const modes = screen.getAllByRole("radio");
    expect(modes).toHaveLength(3);
    expect(within(modes[1]!).getByText("Recommended")).toBeInTheDocument();
    expect(modes[1]).toHaveAttribute("aria-checked", "true");
    fireEvent.click(modes[2]!);
    expect(select).toHaveBeenCalledWith("thorough");
    expect(screen.getByText("Estimates are for this trip: 6 h 12 m of video and 1,180 photos.")).toBeInTheDocument();
    expect(screen.getByText("Balanced · about 1 h 40 m · $2–4")).toBeInTheDocument();
  });

  it("Advanced edits report their source and map sensitivity to the longest shot", () => {
    const edit = vi.fn();
    render(<AnalysisSetupView {...props} onEdit={edit} />);
    fireEvent.click(screen.getByRole("button", { name: /Advanced/ }));
    expect(screen.getAllByText("From the mode").length).toBeGreaterThan(0);
    expect(screen.getByText("This project")).toBeInTheDocument(); // the saved cost limit
    fireEvent.click(screen.getByRole("radio", { name: "High" }));
    expect(edit).toHaveBeenCalledWith("analysis.forced_max_shot", "30");
    fireEvent.change(screen.getByLabelText("Frames per contact sheet"), { target: { value: "6x4" } });
    expect(edit).toHaveBeenCalledWith("analysis.tiles", [6, 4]);
    fireEvent.click(screen.getByRole("button", { name: "Reset Cost limit for this project" }));
    expect(edit).toHaveBeenCalledWith("analysis.cost_limit_usd", null);
  });

  it("estimates loading show skeletons; local only greys out the cloud models", () => {
    render(<AnalysisSetupView {...props} estimates={{}} localOnly />);
    expect(screen.getAllByText("Estimating")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Analyze" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: /Advanced/ }));
    expect(screen.getByLabelText("Scene understanding")).toHaveValue("Not available in Local only");
    expect(screen.getByLabelText("Story & editing")).toHaveValue("Not available in Local only");
  });
});

describe("AnalysisProgressView", () => {
  const props: AnalysisProgressViewProps = {
    progress: PROGRESS,
    job: JOB,
    sheetUrl: (id) => `/sheet/${id}`,
    onPause: noop,
    onResume: noop,
    onCancel: noop,
    onRaiseLimit: noop,
    onRetry: noop,
    onRestart: noop,
    onDetails: noop,
    onOpenLibrary: noop,
    onCreateEdit: noop,
  };

  it("running: overall card, stages, live sheet, ready banner and failures", () => {
    const pause = vi.fn();
    render(<AnalysisProgressView {...props} onPause={pause} />);
    expect(screen.getByText("42%")).toBeInTheDocument();
    expect(screen.getByText("About 58 min left")).toBeInTheDocument();
    expect(screen.getByText("$1.34")).toBeInTheDocument();
    expect(screen.getByText("/ $10.00 limit")).toBeInTheDocument();
    expect(screen.getByText("173 of 412 clips fully analyzed")).toBeInTheDocument();
    expect(screen.getByText("Your footage is ready to browse and edit")).toBeInTheDocument();
    expect(screen.getByText("7,440 frames → 4,120 kept")).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Contact sheet of 16 frames/ })).toHaveAttribute("src", "/sheet/3");
    expect(screen.getByText(/Helmet cam zipline/)).toBeInTheDocument();
    expect(screen.getByText("GX030211.MP4 · Day 4")).toBeInTheDocument();
    expect(screen.getByText("2 clips couldn't be processed.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(pause).toHaveBeenCalled();
  });

  it("hides the time left until there is an ETA", () => {
    render(<AnalysisProgressView {...props} job={{ ...JOB, progress: { pct: 4, eta: null } }} />);
    expect(screen.queryByText(/min left/)).toBeNull();
  });

  it("paused, paused at the cost limit, cancelled and completed states", () => {
    const { rerender } = render(<AnalysisProgressView {...props} job={{ ...JOB, state: "paused" }} />);
    expect(screen.getByRole("button", { name: "Resume" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Cancel analysis" })).toBeInTheDocument();
    const raise = vi.fn();
    rerender(<AnalysisProgressView {...props} onRaiseLimit={raise} job={{ ...JOB, state: "paused_cost_limit" }} />);
    expect(screen.getByText(/Analysis paused at your \$10.00 limit/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Raise limit" }));
    expect(raise).toHaveBeenCalled();
    const restart = vi.fn();
    rerender(<AnalysisProgressView {...props} onRestart={restart} job={{ ...JOB, state: "cancelled" }} />);
    expect(screen.getByText("Everything finished so far is kept.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Resume analysis" }));
    expect(restart).toHaveBeenCalled();
    rerender(<AnalysisProgressView {...props} job={{ ...JOB, state: "done", cost_usd: 3.2 }} />);
    expect(screen.getByText("Done, with 2 clips skipped")).toBeInTheDocument();
    expect(screen.getByText("GX050233.MP4 couldn't be read · IMG_4488.MOV timed out")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry failed" })).toBeInTheDocument();
    expect(screen.queryByText("Your footage is ready to browse and edit")).toBeNull();
    rerender(<AnalysisProgressView {...props} progress={{ ...PROGRESS, failures: { count: 0, items: [] } }} job={{ ...JOB, state: "done", cost_usd: 3.2 }} />);
    expect(screen.getByText("Analysis complete")).toBeInTheDocument();
    expect(screen.getByText("$3.20 · 412 clips · 1,180 photos")).toBeInTheDocument();
  });
});

describe("DeepenBody", () => {
  const props: DeepenBodyProps = {
    days: [
      { n: 2, place: "Arenal", clips: 38 },
      { n: 3, place: null, clips: 44 },
    ],
    selectionSize: 0,
    scope: "days",
    onScope: noop,
    picked: new Set([2]),
    onToggleDay: noop,
    target: "thorough",
    onTarget: noop,
    estimate: { ...ESTIMATES.thorough, scope: "deepen", videos: 38, days: 1, wall_seconds: [3000, 3600], cost_usd: [1.8, 2.6] },
    estimating: false,
    starting: false,
    onStart: noop,
    onCancel: noop,
  };

  it("lists days with clip counts and estimates the choice", () => {
    const toggle = vi.fn();
    render(<DeepenBody {...props} onToggleDay={toggle} />);
    expect(screen.getByText("Day 2 · Arenal")).toBeInTheDocument();
    expect(screen.getByText("38 clips")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /Day 3/ }));
    expect(toggle).toHaveBeenCalledWith(3);
    expect(screen.getByText("About 55 min · $1.80–2.60")).toBeInTheDocument();
    expect(screen.getByText("38 clips · 1 day")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeEnabled();
  });

  it("nothing selected disables Start", () => {
    const { rerender } = render(<DeepenBody {...props} picked={new Set()} estimate={undefined} />);
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
    rerender(<DeepenBody {...props} scope="selection" estimate={undefined} />);
    expect(screen.getByText(/Select clips in the Library first/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });
});
