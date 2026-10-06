import { fireEvent, render, screen } from "@testing-library/react";

import { ClipTile } from "./ClipTile";
import { StarRating } from "./StarRating";

const asset = {
  name: "GX010001.MP4",
  duration: "0:12",
  camera: { kind: "actioncam" as const, label: "GoPro" },
  thumbnail: "t.jpg",
  frames: ["f0.jpg", "f1.jpg", "f2.jpg", "f3.jpg"],
};

function rect(el: Element) {
  el.getBoundingClientRect = () => ({ left: 0, width: 400, top: 0, height: 225, right: 400, bottom: 225, x: 0, y: 0, toJSON: () => ({}) });
}

describe("ClipTile", () => {
  it("hover-scrubs through sample frames, never video", () => {
    const { container } = render(<ClipTile asset={asset} />);
    const media = screen.getByRole("button", { name: asset.name });
    rect(media);
    expect(container.querySelector("img")?.getAttribute("src")).toBe("t.jpg");
    fireEvent.mouseMove(media, { clientX: 310 });
    expect(container.querySelector("img")?.getAttribute("src")).toBe("f3.jpg");
    fireEvent.mouseMove(media, { clientX: 10 });
    expect(container.querySelector("img")?.getAttribute("src")).toBe("f0.jpg");
    fireEvent.mouseLeave(media);
    expect(container.querySelector("img")?.getAttribute("src")).toBe("t.jpg");
    expect(container.querySelector("video")).toBeNull();
  });

  it("shows empty stars on hover so an unrated clip can be rated", () => {
    const { rerender } = render(<ClipTile asset={asset} />);
    expect(screen.queryByRole("img", { name: "Not rated" })).toBeNull();
    rerender(<ClipTile asset={asset} scrubIndex={1} />);
    expect(screen.getByRole("img", { name: "Not rated" })).toBeInTheDocument();
    rerender(<ClipTile asset={asset} stars={4} />);
    expect(screen.getByRole("img", { name: "4 of 5 stars" })).toBeInTheDocument();
  });

  it("draws over footage in dark token values but keeps the selection in the page theme", () => {
    render(<ClipTile asset={asset} disposition="USE" decidedBy="ai" selected />);
    const chip = screen.getByRole("img", { name: "USE, suggested by AI" });
    expect(chip.closest("[data-theme=dark]")).not.toBeNull();
    const media = screen.getByRole("button", { name: asset.name });
    expect(media.className).toMatch(/outline-accent/);
    expect(media.closest("[data-theme=dark]")).toBeNull();
  });

  it("dims rejected clips and explains unsupported ones", () => {
    const { rerender } = render(<ClipTile asset={asset} disposition="REJECT" />);
    expect(screen.getByTestId("clip-tile").className).toMatch(/opacity-55/);
    rerender(<ClipTile asset={{ ...asset, unsupported: { reason: "N-RAW can't be read.", fix: "Export as MP4." } }} />);
    expect(screen.getByText("N-RAW can't be read.")).toBeInTheDocument();
    expect(screen.getByTestId("clip-tile").querySelector("img")).toBeNull();
  });

  it("shows no disposition while analysis is preliminary", () => {
    render(<ClipTile asset={asset} disposition="USE" preliminary />);
    expect(screen.queryByLabelText(/USE/)).toBeNull();
    expect(screen.getByRole("img", { name: "Analysis in progress" })).toBeInTheDocument();
  });
});

describe("StarRating", () => {
  it("sets a rating and clears it when the same star is clicked", () => {
    let value = 0;
    const { rerender } = render(<StarRating value={value} onChange={(v) => (value = v)} />);
    fireEvent.click(screen.getByLabelText("3 stars"));
    expect(value).toBe(3);
    rerender(<StarRating value={3} onChange={(v) => (value = v)} />);
    fireEvent.click(screen.getByLabelText("3 stars"));
    expect(value).toBe(0);
  });
});
