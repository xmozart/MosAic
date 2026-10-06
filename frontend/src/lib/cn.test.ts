import { cn } from "./cn";

describe("cn", () => {
  it("keeps a colour next to a token type size", () => {
    expect(cn("text-use", "text-caption")).toBe("text-use text-caption");
    expect(cn("text-bg text-timecode-sm")).toBe("text-bg text-timecode-sm");
  });

  it("still resolves real conflicts", () => {
    expect(cn("text-caption", "text-body")).toBe("text-body");
    expect(cn("text-use", "text-reject")).toBe("text-reject");
  });
});
