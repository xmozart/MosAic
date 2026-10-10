import { startDesktopSession } from "./desktop";

describe("startDesktopSession", () => {
  afterEach(() => {
    delete window.__MOSAIC_DESKTOP__;
    vi.restoreAllMocks();
  });

  it("sends the shell's token once as a bearer header, then forgets it", async () => {
    window.__MOSAIC_DESKTOP__ = { token: "tok" };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 200 }));
    expect(await startDesktopSession()).toBe(true);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/auth/desktop-session");
    expect((init!.headers as Record<string, string>).Authorization).toBe("Bearer tok");
    expect(window.__MOSAIC_DESKTOP__?.token).toBeUndefined();
    expect(JSON.stringify(localStorage) + JSON.stringify(sessionStorage)).not.toContain("tok");
    expect(await startDesktopSession()).toBe(false); // nothing left to send
  });

  it("without a shell (a plain browser tab) there is nothing to send", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    expect(await startDesktopSession()).toBe(false);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
