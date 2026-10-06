import { Segmented } from "@/components/ui/Segmented";
import type { Disposition } from "@/lib/domain";

const OPTIONS = [
  { value: "USE", label: "USE", hint: "U" },
  { value: "MAYBE", label: "MAYBE", hint: "M" },
  { value: "REJECT", label: "REJECT", hint: "R" },
] as const;

export interface DispositionControlProps {
  value: Disposition | undefined;
  onChange: (value: Disposition) => void;
}

/** Segmented USE / MAYBE / REJECT with U/M/R hints (COMPONENTS.md). */
export function DispositionControl({ value, onChange }: DispositionControlProps) {
  return <Segmented label="Your decision" value={value} options={OPTIONS} onChange={onChange} />;
}
