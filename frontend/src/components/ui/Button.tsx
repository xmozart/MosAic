import { cva, type VariantProps } from "class-variance-authority";
import { Slot } from "radix-ui";
import type { ButtonHTMLAttributes } from "react";

import { cn } from "@/lib/cn";

// DS-Components "Buttons": primary (accent; one per view), secondary, ghost, danger.
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md border font-semibold transition-colors duration-150 ease-out focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-50 [&_svg]:size-4 [&_svg]:shrink-0",
  {
    variants: {
      variant: {
        primary: "border-accent bg-accent text-accent-fg hover:brightness-110",
        secondary: "border-border bg-surface-2 text-text hover:bg-surface-3",
        ghost: "border-transparent bg-transparent text-text-muted hover:bg-surface-2 hover:text-text",
        danger: "border-reject bg-transparent text-reject hover:bg-reject/10",
      },
      size: {
        lg: "min-h-[46px] px-5 py-3 text-subhead",
        md: "min-h-[38px] px-3.5 py-[9px] text-small",
        sm: "min-h-[30px] px-2.5 py-1.5 text-caption",
        icon: "size-[38px] p-0",
      },
    },
    defaultVariants: { variant: "secondary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export function Button({ className, variant, size, asChild, type, ...props }: ButtonProps) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      type={asChild ? undefined : (type ?? "button")}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}
