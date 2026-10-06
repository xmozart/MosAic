import { Dialog } from "radix-ui";
import type { ReactNode } from "react";

import { Button, type ButtonProps } from "./Button";

export interface DialogAction {
  label: string;
  variant?: ButtonProps["variant"];
  onClick: () => void;
  disabled?: boolean;
}

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange?: (open: boolean) => void;
  title: string;
  body: ReactNode;
  actions: DialogAction[]; // left to right; the primary action last
  /** Cannot be dismissed with Esc or a click outside (e.g. a lost lease). */
  blocking?: boolean;
}

/** The base of the global dialogs (COMPONENTS.md ConfirmDialog; S0). */
export function ConfirmDialog({ open, onOpenChange, title, body, actions, blocking }: ConfirmDialogProps) {
  return (
    <Dialog.Root open={open} onOpenChange={blocking ? undefined : onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-scrim" />
        <Dialog.Content
          onEscapeKeyDown={blocking ? (e) => e.preventDefault() : undefined}
          onPointerDownOutside={blocking ? (e) => e.preventDefault() : undefined}
          className="fixed top-1/2 left-1/2 z-50 flex w-[480px] -translate-x-1/2 -translate-y-1/2 flex-col gap-4 rounded-[16px] border border-border bg-surface-1 p-6 shadow-[0_24px_64px_rgba(0,0,0,0.5)]"
        >
          <Dialog.Title className="text-heading text-text">{title}</Dialog.Title>
          <Dialog.Description asChild>
            <div className="text-small text-text-muted">{body}</div>
          </Dialog.Description>
          <div className="flex justify-end gap-2">
            {actions.map((a) => (
              <Button key={a.label} variant={a.variant ?? "secondary"} onClick={a.onClick} disabled={a.disabled}>
                {a.label}
              </Button>
            ))}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
