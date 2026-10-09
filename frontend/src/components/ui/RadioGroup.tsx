import { useLayoutEffect, useRef, type KeyboardEvent, type ReactNode } from "react";

const RADIOS = '[role="radio"]:not(:disabled)';

/** Arrow keys move the choice within a radio group (the ARIA radio pattern). */
function radioArrows(e: KeyboardEvent<HTMLElement>) {
  const keys: Record<string, number> = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 };
  const step = keys[e.key];
  if (step === undefined || e.metaKey || e.ctrlKey) return;
  const radios = Array.from(e.currentTarget.querySelectorAll<HTMLElement>(RADIOS));
  const at = radios.indexOf(document.activeElement as HTMLElement);
  if (at < 0) return;
  e.preventDefault();
  const next = radios[(at + step + radios.length) % radios.length]!;
  next.focus();
  next.click();
}

/** A radio group that is one Tab stop: the checked option (else the first enabled one) is
 * tabbable, the others are reached with the arrow keys (roving tabindex). Children render
 * their own `role="radio"` buttons. */
export function RadioGroup({ label, className, children, as: Tag = "div" }: { label: string; className?: string; children: ReactNode; as?: "div" | "span" }) {
  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const radios = Array.from(ref.current?.querySelectorAll<HTMLElement>('[role="radio"]') ?? []);
    const enabled = radios.filter((r) => !(r as HTMLButtonElement).disabled);
    const stop = enabled.find((r) => r.getAttribute("aria-checked") === "true") ?? enabled[0];
    for (const r of radios) r.tabIndex = r === stop ? 0 : -1;
  });
  return (
    <Tag ref={ref as never} role="radiogroup" aria-label={label} onKeyDown={radioArrows} className={className}>
      {children}
    </Tag>
  );
}
