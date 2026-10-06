import { act, fireEvent, render, screen } from "@testing-library/react";

import { SecretField } from "./SecretField";
import { SettingRow } from "./SettingRow";
import { StageList } from "./StageList";

describe("SecretField", () => {
  it("is write-only: clears the typed key on save and shows only the last four", async () => {
    const saved: string[] = [];
    const { rerender, container } = render(
      <SecretField label="Anthropic API key" onSave={(v) => void saved.push(v)} onValidate={() => {}} />,
    );
    const input = screen.getByLabelText("Anthropic API key") as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(input.autocomplete).toBe("off");
    fireEvent.change(input, { target: { value: "sk-ant-secret-7F3A" } });
    await act(async () => {
      fireEvent.click(screen.getByText("Save key"));
    });
    expect(saved).toEqual(["sk-ant-secret-7F3A"]);
    rerender(<SecretField label="Anthropic API key" last4="7F3A" onSave={() => {}} onValidate={() => {}} />);
    expect(container).toHaveTextContent("••••7F3A");
    expect(container.innerHTML).not.toContain("sk-ant-secret");
    expect(localStorage.length + sessionStorage.length).toBe(0);
  });
});

describe("SettingRow", () => {
  it("shows the source and offers Reset only when not the default", () => {
    const { rerender } = render(<SettingRow label="Mode" source="default" control={<span />} onReset={() => {}} />);
    expect(screen.getByText("From: default")).toBeInTheDocument();
    expect(screen.queryByText("Reset")).toBeNull();
    rerender(<SettingRow label="Mode" source="project" control={<span />} onReset={() => {}} />);
    expect(screen.getByText("From: this project")).toBeInTheDocument();
    expect(screen.getByText("Reset")).toBeInTheDocument();
  });
});

describe("StageList", () => {
  it("renders every state with its note", () => {
    const states = ["pending", "running", "done", "failed", "paused"] as const;
    const { container } = render(
      <StageList stages={states.map((s) => ({ key: s, label: s, state: s, note: `${s} note` }))} />,
    );
    for (const s of states) {
      expect(container.querySelector(`[data-state=${s}]`)).toHaveTextContent(`${s} note`);
    }
  });
});
