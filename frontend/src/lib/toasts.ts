import { create } from "zustand";

export interface ToastItem {
  id: number;
  kind: "info" | "success" | "error";
  message: string;
  action?: { label: string; run: () => void };
}

interface ToastState {
  items: ToastItem[];
  push: (t: Omit<ToastItem, "id">) => void;
  dismiss: (id: number) => void;
}

let next = 1;
export const useToasts = create<ToastState>((set) => ({
  items: [],
  push: (t) => set((s) => ({ items: [...s.items, { ...t, id: next++ }] })),
  dismiss: (id) => set((s) => ({ items: s.items.filter((t) => t.id !== id) })),
}));

