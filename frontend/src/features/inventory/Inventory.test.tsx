import { fireEvent, render, screen, within } from "@testing-library/react";

import { mergeProposal, forSave, EMPTY } from "@/features/context/model";
import { TripContextView, type TripContextViewProps } from "@/features/context/TripContextView";
import { formatOffset, shortStamp, shortVerdict, verdict } from "@/lib/clock";
import { formatBytes, formatShortRange, tripDay } from "@/lib/format";

import { ClockCheckBody, type ClockChange } from "./ClockCheckDialog";
import { COSTA_RICA, DEVICES } from "./fixtures";
import { InventoryView, type InventoryViewProps } from "./InventoryView";

const noop = () => {};

describe("clock and format helpers", () => {
  it("write offsets and verdicts like the reference", () => {
    expect(formatOffset(-18_000_000)).toBe("−5 h 00 m");
    expect(formatOffset(86_400_000)).toBe("+1 d 00 h");
    expect(formatOffset(0)).toBe("0 h 00 m");
    expect(formatOffset(7_170_000)).toBe("+2 h 00 m"); // 1 h 59 m 30 s rounds to a whole minute
    expect(formatOffset(86_370_000)).toBe("+1 d 00 h"); // 23 h 59 m 30 s
    expect(formatOffset(86_460_000)).toBe("+1 d 00 h 01 m"); // a fine step stays visible
    expect(verdict(-7_170_000)).toBe("2 h 00 m ahead");
    expect(shortVerdict(-18_000_000)).toBe("5 h ahead");
    expect(shortVerdict(86_400_000)).toBe("1 day behind");
    expect(shortVerdict(-720_000)).toBe("12 min ahead");
    expect(shortStamp("2026-07-15T10:42:00-06:00")).toBe("Jul 15 10:42");
    expect(formatShortRange("2026-07-14", "2026-07-24")).toBe("Jul 14–24");
    expect(tripDay("2026-07-14", "2026-07-15")).toBe(2);
    expect(formatBytes(48_000_000_000)).toBe("48 GB");
  });
});

describe("InventoryView", () => {
  const props: InventoryViewProps = {
    inv: COSTA_RICA,
    scanning: false,
    frameUrl: (i) => `/f/${i}`,
    hidden: new Set(),
    downloadPct: null,
    onShowFiles: noop,
    onHide: noop,
    onDownload: noop,
    onReviewClocks: noop,
    onContinue: noop,
  };

  it("shows cameras, the day timeline, clocks and what needs attention", () => {
    const hide = vi.fn();
    const files = vi.fn();
    render(<InventoryView {...props} onHide={hide} onShowFiles={files} />);
    expect(screen.getByText("Here's what we found")).toBeInTheDocument();
    expect(screen.getByText("6 h 12 m")).toBeInTheDocument();
    expect(screen.getByText("Jul 14–24")).toBeInTheDocument();
    expect(screen.getByText("96 recordings (131 files) · 2 h 21 m")).toBeInTheDocument();
    expect(screen.getByText("41 clips (14 are 360°) · 38 m")).toBeInTheDocument();
    expect(screen.getByText("Clock 5 h ahead?")).toBeInTheDocument();
    expect(screen.getByText("2 cameras may have the wrong time")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Day 2, Jul 15: iPhone 16 Pro 1 h 40 m/)).toBeInTheDocument();
    const attention = screen.getByRole("region", { name: "Needs attention" });
    expect(within(attention).getByText("4")).toBeInTheDocument();
    expect(within(attention).getByText("22 files (48 GB) are only in the cloud")).toBeInTheDocument();
    expect(within(attention).getByText("GX050233.MP4: It looks damaged.")).toBeInTheDocument();
    fireEvent.click(within(attention).getAllByRole("button", { name: "Ignore" })[0]!);
    expect(hide).toHaveBeenCalledWith(COSTA_RICA.attention[0]);
    fireEvent.click(within(attention).getAllByRole("button", { name: "Show files" })[0]!);
    expect(files).toHaveBeenCalledWith(COSTA_RICA.attention[0]);
    expect(screen.getByText(/Chapters joined into 38 recordings · 96 Live Photos paired · 42 photo bursts grouped/)).toBeInTheDocument();
  });

  it("collapses to one green line when nothing needs attention, and shows download progress", () => {
    const { rerender } = render(<InventoryView {...props} hidden={new Set(["unreadable:7", "limited", "cloud", "unreadable:9"])} />);
    expect(screen.getByText("Nothing needs attention.")).toBeInTheDocument();
    rerender(<InventoryView {...props} downloadPct={42} />);
    expect(screen.getByRole("progressbar", { name: "Downloading" })).toHaveAttribute("aria-valuenow", "42");
    expect(screen.queryByRole("button", { name: "Download now" })).toBeNull();
  });

  it("shows skeleton cards while scanning", () => {
    render(<InventoryView {...props} inv={undefined} scanning />);
    expect(document.querySelector("[aria-busy=true]")?.children.length).toBe(5);
  });
});

describe("ClockCheckBody", () => {
  it("accepts suggestions, adjusts by hand with + and −, and lists consistent cameras", () => {
    const apply = vi.fn<(c: ClockChange[]) => void>();
    render(<ClockCheckBody devices={DEVICES} frameUrl={(i) => `/f/${i}`} onApply={apply} onSkip={noop} />);
    expect(screen.getByText("Appears 5 h 00 m ahead")).toBeInTheDocument();
    expect(screen.getByText("Appears 1 day behind")).toBeInTheDocument();
    expect(screen.getByText("iPhone · Jul 15 10:42")).toBeInTheDocument();
    expect(screen.getByText("GoPro · Jul 15 15:43")).toBeInTheDocument();
    expect(screen.getByText("−5 h 00 m")).toBeInTheDocument();
    expect(screen.getByText(/Nikon Z6III and DJI Mini 4 Pro look consistent/)).toBeInTheDocument();
    const insta = screen.getByRole("group", { name: "Clock correction for Insta360 X4" });
    fireEvent.keyDown(insta, { key: "-" });
    fireEvent.keyDown(insta, { key: "+", shiftKey: true });
    expect(within(insta).getByText("+23 h 01 m")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(apply).toHaveBeenCalledWith([
      { id: 2, accept_suggestion: true },
      { id: 3, clock_offset_ms: 86_400_000 - 3_600_000 + 60_000 },
    ]);
  });

  it("without suggestions offers the manual stepper only", () => {
    render(<ClockCheckBody devices={DEVICES.map((d) => ({ ...d, suggestion: null }))} frameUrl={String} onApply={noop} onSkip={noop} />);
    expect(screen.queryByText("Accept suggestion")).toBeNull();
    expect(screen.getAllByText(/No suggestion yet/).length).toBe(5);
  });

  it("all consistent: one confirmation and Continue", () => {
    const skip = vi.fn();
    render(<ClockCheckBody devices={[DEVICES[0]!, DEVICES[3]!]} frameUrl={String} onApply={noop} onSkip={skip} />);
    expect(screen.getByText("All cameras look consistent.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(skip).toHaveBeenCalled();
  });
});

describe("trip context", () => {
  it("merges a parsed proposal without dropping what the user typed", () => {
    const mine = { ...EMPTY, trip_name: "CR", days: [{ date: "2026-07-14", place: "San José", notes: "Rain" }], must_include: ["toucan"] };
    const { value, changed } = mergeProposal(mine, {
      ...EMPTY,
      trip_name: "Costa Rica 2026",
      days: [
        { date: "2026-07-14", place: "Alajuela", notes: "long drive" },
        { date: "2026-07-15", place: "Arenal", notes: "" },
      ],
      must_include: ["Toucan", "zipline"],
      people: [{ label: "Anna", description: "straw hat" }],
    });
    expect(value.trip_name).toBe("CR"); // the user's name stays
    expect(value.days).toEqual([
      { date: "2026-07-14", place: "San José", notes: "Rain; long drive" }, // typed place kept
      { date: "2026-07-15", place: "Arenal", notes: "" },
    ]);
    expect(value.must_include).toEqual(["toucan", "zipline"]);
    expect([...changed].sort()).toEqual(["day:2026-07-14", "day:2026-07-15", "must_include:zipline", "person:Anna"]);
    expect(forSave({ ...value, days: [...value.days, { date: "2026-07-16", place: " ", notes: "" }] }).days).toHaveLength(2);
  });

  const base: TripContextViewProps = {
    value: { ...EMPTY },
    onChange: noop,
    footageDays: ["2026-07-14", "2026-07-15"],
    highlights: new Set(),
    tab: "details",
    onTab: noop,
    paste: "Day 1 …",
    onPaste: noop,
    parsing: false,
    parseError: null,
    onParse: noop,
    saving: false,
    onSave: noop,
    onSkip: noop,
  };

  it("lists a row per footage day and edits it; chips add and remove", () => {
    const change = vi.fn();
    render(<TripContextView {...base} value={{ ...EMPTY, avoid: ["car interiors"] }} onChange={change} />);
    fireEvent.change(screen.getByLabelText("Place for day 2"), { target: { value: "Arenal" } });
    expect(change).toHaveBeenLastCalledWith(expect.objectContaining({ days: [{ date: "2026-07-15", place: "Arenal", notes: "" }] }));
    fireEvent.click(screen.getByRole("button", { name: "Remove car interiors" }));
    expect(change).toHaveBeenLastCalledWith(expect.objectContaining({ avoid: [] }));
    fireEvent.click(within(screen.getByRole("list", { name: "Must include" })).getByRole("button", { name: "Add" }));
    const input = screen.getByLabelText("Add to Must include");
    fireEvent.change(input, { target: { value: "the toucan" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(change).toHaveBeenLastCalledWith(expect.objectContaining({ must_include: ["the toucan"] }));
    expect(screen.getByText("Optional")).toBeInTheDocument();
  });

  it("⌘Enter in the paste box runs Parse; parsed rows are tinted", () => {
    const parse = vi.fn();
    const { rerender } = render(<TripContextView {...base} tab="paste" onParse={parse} />);
    fireEvent.keyDown(screen.getByLabelText("Trip notes"), { key: "Enter", metaKey: true });
    expect(parse).toHaveBeenCalledTimes(1);
    rerender(<TripContextView {...base} highlights={new Set(["day:2026-07-15"])} />);
    expect(screen.getByText(/New values are highlighted/)).toBeInTheDocument();
    expect(document.querySelectorAll("[data-parsed]")).toHaveLength(1);
  });
});
