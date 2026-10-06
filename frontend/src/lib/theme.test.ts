import { applyTheme, useTheme } from "./theme";

describe("theme", () => {
  beforeEach(() => {
    localStorage.clear();
    delete document.documentElement.dataset.theme;
  });

  it("follows the OS until the user chooses", () => {
    applyTheme("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it("pins and remembers a choice, and can return to the OS", () => {
    useTheme.getState().set("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("mosaic.theme")).toBe("light");
    useTheme.getState().set("system");
    expect(document.documentElement.dataset.theme).toBeUndefined();
    expect(localStorage.getItem("mosaic.theme")).toBeNull();
  });
});
