import { Toast as Radix } from "radix-ui";
import { cn } from "@/lib/cn";
import { useToasts } from "@/lib/toasts";

/** Bottom-right toasts (COMPONENTS.md Toast), e.g. "Version 3 created · Undo". */
export function Toaster() {
  const { items, dismiss } = useToasts();
  return (
    <Radix.Provider swipeDirection="right" duration={6000}>
      {items.map((t) => (
        <Radix.Root
          key={t.id}
          onOpenChange={(open) => !open && dismiss(t.id)}
          className={cn(
            "flex items-center gap-3 rounded-md border border-border bg-surface-2 px-4 py-3 shadow-[0_12px_32px_rgba(0,0,0,0.4)]",
            t.kind === "error" && "shadow-[inset_3px_0_0_var(--reject),0_12px_32px_rgba(0,0,0,0.4)]",
          )}
        >
          <Radix.Description className="flex-1 text-small text-text">{t.message}</Radix.Description>
          {t.action && (
            <Radix.Action altText={t.action.label} asChild>
              <button
                type="button"
                onClick={t.action.run}
                className="text-small font-semibold text-accent focus-visible:outline-2 focus-visible:outline-accent"
              >
                {t.action.label}
              </button>
            </Radix.Action>
          )}
        </Radix.Root>
      ))}
      <Radix.Viewport className="fixed right-6 bottom-6 z-50 flex w-[360px] flex-col gap-2 outline-none" />
    </Radix.Provider>
  );
}
