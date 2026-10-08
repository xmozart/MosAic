import type { KeyboardEvent } from "react";

/** Arrow keys move the choice within a radio group (the ARIA radio pattern). */
export function radioArrows(e: KeyboardEvent<HTMLElement>) {
  const keys: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  const step = keys[e.key];
  if (step === undefined || e.metaKey || e.ctrlKey) return;
  const radios = Array.from(e.currentTarget.querySelectorAll<HTMLButtonElement>('[role="radio"]:not(:disabled)'));
  const at = radios.indexOf(document.activeElement as HTMLButtonElement);
  if (at < 0) return;
  e.preventDefault();
  const next = radios[(at + step + radios.length) % radios.length]!;
  next.focus();
  next.click();
}
