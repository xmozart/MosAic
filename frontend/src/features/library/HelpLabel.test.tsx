import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";

import { QUESTIONS } from "./fixtures";
import { HelpLabelDialog, type HelpLabelDialogProps, type LabelAnswer } from "./HelpLabelDialog";

const noop = () => {};

function Dialog(p: Partial<HelpLabelDialogProps>) {
  return <HelpLabelDialog open onOpenChange={noop} questions={QUESTIONS} frame={(sid) => `/f/${sid}`} onAnswer={() => Promise.resolve()} {...p} />;
}

describe("S24 HelpLabelDialog", () => {
  it("asks each question in turn and records the answers; Back shows what was given", async () => {
    const answers: [string, LabelAnswer][] = [];
    render(<Dialog onAnswer={(q, a) => (answers.push([q, a]), Promise.resolve())} />);
    const dialog = screen.getByRole("dialog", { name: "Help me label" });
    expect(within(dialog).getByText("Question 1 of 3")).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Next" })).toBeDisabled();
    expect(document.activeElement).toBe(within(dialog).getByLabelText("Place")); // the question has the focus
    fireEvent.change(within(dialog).getByLabelText("Place"), { target: { value: "La Fortuna" } });
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    expect(await within(dialog).findByText("Question 2 of 3")).toBeInTheDocument();
    expect(answers).toEqual([["q1", { text: "La Fortuna" }]]);
    // The next question takes the focus, so its keys work straight away.
    expect(document.activeElement).toBe(within(dialog).getByRole("radio", { name: "Yes, same person" }));

    // Same person: 1/2/3 choose; Yes needs a name; a known name matches the trip details.
    expect(within(dialog).getByText(/Faces are not stored or recognized/)).toBeInTheDocument();
    fireEvent.keyDown(document.activeElement!, { key: "2" });
    expect(within(dialog).getByRole("radio", { name: "No" })).toHaveAttribute("aria-checked", "true");
    fireEvent.keyDown(document.activeElement!, { key: "1" });
    expect(within(dialog).getByRole("radio", { name: "Yes, same person" })).toHaveAttribute("aria-checked", "true");
    expect(within(dialog).getByRole("button", { name: "Next" })).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(/Who is it/), { target: { value: "maya" } });
    expect(within(dialog).getByText("Matches your trip details: “Maya — younger daughter, yellow raincoat”")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Next" }));
    expect(await within(dialog).findByText("Question 3 of 3")).toBeInTheDocument();
    expect(answers[1]).toEqual(["q2", { choice: "yes", name: "maya" }]);

    fireEvent.click(within(dialog).getByRole("button", { name: "Back" }));
    expect(within(dialog).getByText("Answered — these clips are linked to maya.")).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Next" }));
    expect(answers).toHaveLength(2); // never sent twice

    fireEvent.click(within(dialog).getByRole("button", { name: "Skip" }));
    expect(await within(dialog).findByText("Thanks — that helps.")).toBeInTheDocument();
    expect(within(dialog).getByText(/2 answered, 1 skipped\. Places and notes are in your trip details, and the clips you confirmed are linked/)).toBeInTheDocument();
    expect(document.activeElement).toHaveTextContent("Close"); // the summary's Close, not the icon
    expect(answers[2]).toEqual(["q3", { skip: true }]);
  });

  it("No and Not sure need no name; 3 chooses Not sure", async () => {
    const answers: [string, LabelAnswer][] = [];
    render(<Dialog questions={[QUESTIONS[1]!]} onAnswer={(q, a) => (answers.push([q, a]), Promise.resolve())} />);
    fireEvent.keyDown(document.activeElement!, { key: "3" });
    expect(screen.getByLabelText(/Who is it\? \(optional\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => expect(answers).toEqual([["q2", { choice: "not_sure" }]]));
    expect(await screen.findByText(/1 answered\. Places and notes are in your trip details\.$/)).toBeInTheDocument(); // nobody linked
  });

  it("shows why an answer wasn't taken, and stays on the question", async () => {
    render(<Dialog questions={[QUESTIONS[0]!]} onAnswer={() => Promise.reject(new Error("The trip details can hold 366 days at most."))} />);
    fireEvent.change(screen.getByLabelText("Place"), { target: { value: "Somewhere" } });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The trip details can hold 366 days at most.");
    expect(screen.getByText("Question 1 of 1")).toBeInTheDocument();
  });

  it("a question answered elsewhere is passed over", async () => {
    render(<Dialog questions={[QUESTIONS[0]!]} onAnswer={() => Promise.reject(new Error("This question was answered already."))} />);
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    expect(await screen.findByText(/1 answered/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("nothing to ask", () => {
    render(<Dialog questions={[]} />);
    expect(screen.getByText(/Nothing to ask right now/)).toBeInTheDocument();
  });
});
