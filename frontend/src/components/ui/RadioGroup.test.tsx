import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";

import { RadioGroup } from "./RadioGroup";

function Group({ initial }: { initial: string | null }) {
  const [v, setV] = useState(initial);
  return (
    <>
      <button type="button">before</button>
      <RadioGroup label="Length">
        {["15 s", "30 s", "1 min"].map((x) => (
          <button key={x} type="button" role="radio" aria-checked={v === x} disabled={x === "1 min" && initial === "disabled"} onClick={() => setV(x)}>
            {x}
          </button>
        ))}
      </RadioGroup>
    </>
  );
}

const tabbable = () => screen.getAllByRole("radio").filter((r) => r.tabIndex === 0).map((r) => r.textContent);

describe("RadioGroup", () => {
  it("is one Tab stop: the checked option, moved by the arrow keys", () => {
    render(<Group initial="30 s" />);
    expect(tabbable()).toEqual(["30 s"]);
    screen.getByRole("radio", { name: "30 s" }).focus();
    fireEvent.keyDown(screen.getByRole("radio", { name: "30 s" }), { key: "ArrowRight" });
    expect(screen.getByRole("radio", { name: "1 min" })).toHaveFocus();
    expect(screen.getByRole("radio", { name: "1 min" })).toHaveAttribute("aria-checked", "true");
    expect(tabbable()).toEqual(["1 min"]);
    fireEvent.keyDown(screen.getByRole("radio", { name: "1 min" }), { key: "ArrowRight" });
    expect(tabbable()).toEqual(["15 s"]); // wraps
  });

  it("without a choice, the first option is the Tab stop", () => {
    render(<Group initial={null} />);
    expect(tabbable()).toEqual(["15 s"]);
  });
});
