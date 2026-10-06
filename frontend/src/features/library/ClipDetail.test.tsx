import { fireEvent, render, screen, within } from "@testing-library/react";
import { createRef } from "react";

import { Player, type PlayerHandle } from "@/components/media/Player";
import { frameIndex } from "@/lib/time";

import { ClipDetailView, type ClipDetailViewProps } from "./ClipDetailView";
import { DETAIL, PHOTO, THREE_SIXTY, TRANSCRIPT, UNSUPPORTED } from "./fixtures";

const noop = () => {};
const props: ClipDetailViewProps = {
  clip: DETAIL,
  proxyUrl: "/proxy/1",
  frameUrl: (i) => `/f/${i}`,
  filmstrip: ["/f/1", "/f/2"],
  peaks: new Uint8Array([10, 200, 40]),
  transcript: TRANSCRIPT,
  onDecide: noop,
  onBack: noop,
  onNext: noop,
  onShowClip: noop,
};

describe("frame index", () => {
  it.each([
    [{ ticks: 0, tb: "1/90000" }, "30000/1001", 0],
    [{ ticks: 3003 * 7, tb: "1/90000" }, "30000/1001", 7], // exactly on a frame boundary
    [{ ticks: 3003 * 7 - 1, tb: "1/90000" }, "30000/1001", 6], // one tick before it
    [{ ticks: 3003 * 4_000_000, tb: "1/90000" }, "30000/1001", 4_000_000], // ~37 h in
    [{ ticks: 1001 * 9, tb: "1/30000" }, "30000/1001", 9],
    [{ ticks: 600, tb: "1/600" }, "25/1", 25], // one second
    [{ ticks: 1500, tb: "1/1000" }, "60000/1001", 89], // 1.5 s at 59.94 fps
  ])("%o at %s is frame %i", (t, rate, want) => {
    expect(frameIndex(t, rate)).toBe(want);
  });
});

describe("Player.seekTo", () => {
  it("lands inside the frame that contains the time", () => {
    const ref = createRef<PlayerHandle>();
    const { container } = render(<Player ref={ref} src="/x.mp4" rate="30000/1001" />);
    const video = container.querySelector("video")!;
    ref.current!.seekTo({ ticks: 236250, tb: "1/90000" }); // 2.625 s
    const frame = 1001 / 30000;
    const target = 236250 / 90000;
    expect(Math.floor(video.currentTime / frame)).toBe(Math.floor(target / frame + 1e-6));
    expect(Math.abs(video.currentTime - target)).toBeLessThan(frame);
  });
});

describe("ClipDetailView", () => {
  it("a transcript word seeks the player within one frame", () => {
    const { container } = render(<ClipDetailView {...props} />);
    const video = container.querySelector("video")!;
    expect(screen.getByTestId("transcript-line").textContent).toBe("It's right there! Look!");
    fireEvent.click(screen.getByRole("button", { name: "Look!" }));
    expect(document.activeElement).toBe(screen.getByLabelText("Player")); // the keys stay with the player
    expect(Math.abs(video.currentTime - 236250 / 90000)).toBeLessThan(1001 / 30000);
    expect(screen.getByText("Day 2 · 1 of 8")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Previous clip" })).toBeDisabled();
    expect(within(screen.getByRole("complementary", { name: "Decisions" })).getByText("AI suggested USE")).toBeInTheDocument();
    expect(screen.getByText("Falls revealed through the trees")).toBeInTheDocument();
  });

  it("without speech the transcript card is hidden", () => {
    render(<ClipDetailView {...props} transcript={[]} />);
    expect(screen.queryByRole("region", { name: "Transcript" })).toBeNull();
  });

  it("photo: Live Photo motion and the burst strip with its best pick", () => {
    const decide = vi.fn();
    render(<ClipDetailView {...props} clip={PHOTO} transcript={[]} peaks={null} onDecide={decide} />);
    expect(screen.queryByLabelText("Player")).toBeNull();
    fireEvent.click(screen.getByRole("switch", { name: "Use 2 s of Live Photo motion" }));
    expect(decide).toHaveBeenCalledWith({ live_motion: true });
    expect(screen.getByText("Burst · 6 photos · best picked")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Best of the burst" })).toHaveLength(1);
  });

  it("unsupported: the reason and how to fix it instead of the player", () => {
    render(<ClipDetailView {...props} clip={UNSUPPORTED} transcript={[]} peaks={null} />);
    expect(screen.getByText(UNSUPPORTED.reason!)).toBeInTheDocument();
    expect(screen.getByText(UNSUPPORTED.fix!)).toBeInTheDocument();
    expect(screen.queryByLabelText("Player")).toBeNull();
  });

  it("360: the forward view with its info banner", () => {
    render(<ClipDetailView {...props} clip={THREE_SIXTY} />);
    expect(screen.getByText(/Analyzed from a forward view/)).toBeInTheDocument();
    expect(screen.getByText("360 · forward view")).toBeInTheDocument();
    expect(screen.getByLabelText("Player")).toBeInTheDocument();
  });
});
