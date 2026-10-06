import { act, fireEvent, render, screen } from "@testing-library/react";

import { api, csrfToken } from "@/api/client";

import { SignIn } from "./SignIn";

describe("SignIn", () => {
  it("first-time setup checks the confirmation before sending", async () => {
    const submit = vi.fn(async () => ({ ok: true as const }));
    render(<SignIn setup host="h" submit={submit} />);
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "long enough pass" } });
    fireEvent.change(screen.getByLabelText("Confirm password"), { target: { value: "different pass!!" } });
    await act(async () => fireEvent.click(screen.getByText("Create account")));
    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("The passwords don't match.");
  });

  it("Enter submits", async () => {
    const submit = vi.fn(async () => ({ ok: true as const }));
    render(<SignIn setup={false} host="h" submit={submit} />);
    const pw = screen.getByLabelText("Password");
    fireEvent.change(pw, { target: { value: "my password" } });
    await act(async () => fireEvent.submit(pw.closest("form")!));
    expect(submit).toHaveBeenCalledWith("my password");
  });

  it("shows the server's message and clears the field", async () => {
    render(
      <SignIn setup={false} host="h" submit={async () => ({ ok: false, message: "That password didn't match. Try again." })} />,
    );
    const pw = screen.getByLabelText("Password") as HTMLInputElement;
    fireEvent.change(pw, { target: { value: "nope" } });
    await act(async () => fireEvent.click(screen.getByText("Sign in")));
    expect(screen.getByRole("alert")).toHaveTextContent("didn't match");
    expect(pw.value).toBe("");
  });

  it("counts down when rate-limited and keeps the button disabled", async () => {
    vi.useFakeTimers();
    render(
      <SignIn setup={false} host="h" submit={async () => ({ ok: false, message: "Too many", retryAfter: 3 })} />,
    );
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "x" } });
    await act(async () => fireEvent.click(screen.getByText("Sign in")));
    expect(screen.getByRole("alert")).toHaveTextContent("3 s");
    await act(async () => vi.advanceTimersByTime(1000));
    expect(screen.getByRole("alert")).toHaveTextContent("2 s");
    expect(screen.getByText("Sign in").closest("button")).toBeDisabled();
    vi.useRealTimers();
  });
});

describe("CSRF", () => {
  it("reads the token cookie", () => {
    expect(csrfToken("a=1; mosaic_csrf=abc%2Dd; b=2")).toBe("abc-d");
    expect(csrfToken("a=1")).toBeUndefined();
  });

  it("echoes the token on writes only", async () => {
    document.cookie = "mosaic_csrf=tok123";
    const seen: Request[] = [];
    const fetchMock = vi.fn(async (req: Request) => {
      seen.push(req);
      return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
    });
    // openapi-fetch keeps the fetch it was created with; pass the mock per request.
    await api.GET("/api/auth/status", { fetch: fetchMock });
    await api.POST("/api/auth/logout", { fetch: fetchMock });
    expect(seen[0]?.headers.get("X-CSRF-Token")).toBeNull();
    expect(seen[1]?.headers.get("X-CSRF-Token")).toBe("tok123");
  });
});
