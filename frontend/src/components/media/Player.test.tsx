import { fireEvent, render, screen } from "@testing-library/react";

import { formatClock, seconds } from "@/lib/time";

import { Player } from "./Player";
import { Waveform } from "./Waveform";

function setup() {
  render(<Player src="/v.mp4" rate="30/1" usableRange={{ start: { ticks: 90000, tb: "1/90000" }, end: { ticks: 270000, tb: "1/90000" } }} />);
  const video = document.querySelector("video")!;
  Object.defineProperty(video, "duration", { value: 10, configurable: true });
  let paused = true;
  Object.defineProperty(video, "paused", { get: () => paused, configurable: true });
  video.play = vi.fn(async () => {
    paused = false;
  });
  video.pause = vi.fn(() => {
    paused = true;
  });
  fireEvent.loadedMetadata(video);
  return { video, player: screen.getByLabelText("Player") };
}

describe("Player", () => {
  it("steps one frame with the arrows and one second with Shift", () => {
    const { video, player } = setup();
    video.currentTime = 2;
    fireEvent.keyDown(player, { key: "ArrowRight" });
    expect(video.currentTime).toBeCloseTo(2 + 1 / 30, 5);
    fireEvent.keyDown(player, { key: "ArrowLeft", shiftKey: true });
    expect(video.currentTime).toBeCloseTo(1 + 1 / 30, 5);
  });

  it("Space toggles, K pauses, L plays and speeds up, J goes back", () => {
    const { video, player } = setup();
    fireEvent.keyDown(player, { key: " " });
    expect(video.play).toHaveBeenCalled();
    fireEvent.keyDown(player, { key: "k" });
    expect(video.pause).toHaveBeenCalled();
    fireEvent.keyDown(player, { key: "l" });
    expect(video.playbackRate).toBe(1);
    fireEvent.keyDown(player, { key: "l" });
    expect(video.playbackRate).toBe(1.5);
    video.currentTime = 7;
    fireEvent.keyDown(player, { key: "j" });
    expect(video.currentTime).toBe(2);
  });

  it("shows the usable range from exact times", () => {
    setup();
    const band = screen.getByTestId("usable-range");
    expect(band.style.left).toBe("10%");
  });

  it("does not jump back when the parent re-renders with an equal range", () => {
    const r = () => ({ start: { ticks: 90000, tb: "1/90000" }, end: { ticks: 450000, tb: "1/90000" } });
    const { rerender } = render(<Player src="/v.mp4" rate="30/1" range={r()} />);
    const video = document.querySelector("video")!;
    Object.defineProperty(video, "duration", { value: 10, configurable: true });
    fireEvent.loadedMetadata(video);
    video.currentTime = 3;
    rerender(<Player src="/v.mp4" rate="30/1" range={r()} />);
    expect(video.currentTime).toBe(3);
    rerender(<Player src="/v.mp4" rate="30/1" range={{ ...r(), start: { ticks: 180000, tb: "1/90000" } }} />);
    expect(video.currentTime).toBe(2);
  });

  it("has a state with no preview", () => {
    render(<Player rate="30/1" />);
    expect(screen.getByText("No preview yet")).toBeInTheDocument();
  });
});

describe("time", () => {
  it("formats display clocks from exact times", () => {
    expect(seconds({ ticks: 4026240, tb: "1/90000" })).toBeCloseTo(44.736, 3);
    expect(formatClock(48)).toBe("0:48");
    expect(formatClock(3723)).toBe("1:02:03");
  });
});

describe("Waveform", () => {
  it("reduces peaks to bars and says when there is no sound", () => {
    const { container, rerender } = render(<Waveform peaks={Uint8Array.from([0, 255, 128])} />);
    expect(container.querySelectorAll("rect")).toHaveLength(3);
    rerender(<Waveform peaks={new Uint8Array()} />);
    expect(screen.getByText("No sound")).toBeInTheDocument();
  });
});
