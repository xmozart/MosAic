import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

import tokens from "../../../docs/ui/tokens.json";

// The token type styles (`text-caption`, `text-timecode-sm`, …) are font sizes. Without
// this, tailwind-merge takes them for colours and drops a real colour class such as
// `text-use` from the same element.
const twMerge = extendTailwindMerge({
  extend: {
    theme: { text: tokens.type.groups.flatMap((g) => g.styles.map((s) => s.name)) },
  },
});

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
