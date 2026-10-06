import { create } from "zustand";

export type ThemeChoice = "system" | "dark" | "light";
const KEY = "mosaic.theme";

function read(): ThemeChoice {
  try {
    const v = localStorage.getItem(KEY);
    return v === "dark" || v === "light" ? v : "system";
  } catch {
    return "system";
  }
}

/** Applies the choice: "system" follows the OS (no attribute), else pins the theme. */
export function applyTheme(choice: ThemeChoice, root: HTMLElement = document.documentElement) {
  if (choice === "system") delete root.dataset.theme;
  else root.dataset.theme = choice;
}

interface ThemeState {
  choice: ThemeChoice;
  set: (choice: ThemeChoice) => void;
}

/** Theme follows the OS until the user chooses (docs/ui/README.md rule 7). The choice is a
 * per-viewer convenience, kept in browser storage. */
export const useTheme = create<ThemeState>((set) => ({
  choice: read(),
  set: (choice) => {
    try {
      if (choice === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, choice);
    } catch {
      // storage unavailable: the choice lasts for this page only
    }
    applyTheme(choice);
    set({ choice });
  },
}));
