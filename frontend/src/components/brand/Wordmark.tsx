import mark from "@/assets/brand/mosaic-mark.svg";

/** The mark and "Mos·Ai·c" wordmark (docs/ui/brand; DS-Logo). */
export function Wordmark({ size = 22 }: { size?: number }) {
  return (
    <span className="inline-flex items-center gap-2.5">
      <img src={mark} alt="" width={size + 6} height={size + 6} className="rounded-[7px]" />
      <span className="font-semibold tracking-[-0.02em] text-text" style={{ fontSize: size }}>
        Mos<span className="text-accent">Ai</span>c
      </span>
    </span>
  );
}
