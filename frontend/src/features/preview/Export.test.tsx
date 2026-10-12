import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { ExportDialog, type ExportDialogProps } from "./ExportDialog";
import { EXPORT_OPTIONS } from "./fixtures";

const noop = () => {};

function Dialog(p: Partial<ExportDialogProps>) {
  return <ExportDialog open onOpenChange={noop} title="Costa Rica — 5 min cinematic" options={EXPORT_OPTIONS} onRender={noop} {...p} />;
}

describe("S19 ExportDialog", () => {
  it("shows each preset's size and time at the chosen resolution, and renders the choice", () => {
    const onRender = vi.fn();
    render(<Dialog onRender={onRender} />);
    const dialog = screen.getByRole("dialog", { name: "Render final" });
    expect(within(dialog).getByText("Costa Rica — 5 min cinematic · v3 · 5:02")).toBeInTheDocument();
    expect(within(dialog).getByRole("radio", { name: /^WebH/ })).toHaveTextContent("≈ 1.1 GB · 12 min");
    expect(within(dialog).getByRole("radio", { name: /Master/ })).toHaveTextContent("≈ 18 GB · 9 min");
    fireEvent.change(within(dialog).getByLabelText("Resolution"), { target: { value: "1080p" } });
    expect(within(dialog).getByRole("radio", { name: /^WebH/ })).toHaveTextContent("≈ 536 MB · 6 min");
    expect(within(dialog).getByLabelText("Frame rate")).toHaveValue("29.97");
    fireEvent.click(within(dialog).getByRole("radio", { name: /High quality/ }));
    fireEvent.click(within(dialog).getByRole("radio", { name: "TV (−23 LUFS)" }));
    fireEvent.click(within(dialog).getByRole("checkbox", { name: /Captions file/ }));
    expect(within(dialog).getByRole("checkbox", { name: /Final Cut Pro/ })).toBeDisabled();
    expect(within(dialog).getByText("Renders from your original footage · VideoToolbox")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Render" }));
    expect(onRender).toHaveBeenCalledWith({ codec: "hevc", resolution: "1080p", loudness: "tv", sidecars: ["report"], save_to: null });
  });

  it("a preset with no encoder can't be chosen, and says why", () => {
    const options = { ...EXPORT_OPTIONS, presets: { ...EXPORT_OPTIONS.presets, h264: { ...EXPORT_OPTIONS.presets.h264, available: false, encoder: null, reason: "No H264 encoder works on this computer." } } };
    render(<Dialog options={options} />);
    const web = screen.getByRole("radio", { name: /^WebH/ });
    expect(web).toBeDisabled();
    expect(web).toHaveTextContent("No H264 encoder works on this computer.");
    expect(screen.getByRole("radio", { name: /High quality/ })).toHaveAttribute("aria-checked", "true");
  });

  it("Save to: a chosen folder goes with the render; the server mode downloads instead", async () => {
    const onRender = vi.fn();
    const { unmount } = render(<Dialog onRender={onRender} onChooseFolder={() => Promise.resolve("/Users/me/Movies")} />);
    fireEvent.click(screen.getByRole("button", { name: "Choose…" }));
    await waitFor(() => expect(screen.getByLabelText("Save to")).toHaveValue("/Users/me/Movies"));
    fireEvent.click(screen.getByRole("button", { name: "Render" }));
    expect(onRender.mock.calls[0]![0].save_to).toBe("/Users/me/Movies");
    unmount();
    render(<Dialog options={{ ...EXPORT_OPTIONS, save_to: { default: "/srv/mosaic/renders", can_choose: false } }} />);
    expect(screen.queryByRole("button", { name: "Choose…" })).toBeNull();
    expect(screen.getByText("Download the files from Exports when they're ready.")).toBeInTheDocument();
  });

  it("shows why a render couldn't start (a folder that can't be written to)", () => {
    render(<Dialog error="That folder can't be written to. Choose another one." />);
    expect(screen.getByRole("alert")).toHaveTextContent("That folder can't be written to.");
  });
});
