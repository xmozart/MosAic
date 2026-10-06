import { cn } from "@/lib/cn";

export interface FilmstripProps {
  frames: string[]; // sample frame URLs (GET /media/.../filmstrip → /frame/{id})
  /** Highlighted frames (the selection), as an index range [from, to). */
  selection?: [number, number];
  className?: string;
}

/** A row of sample frames (COMPONENTS.md Filmstrip). */
export function Filmstrip({ frames, selection, className }: FilmstripProps) {
  return (
    <div className={cn("flex gap-0.5 overflow-hidden rounded-sm", className)} role="img" aria-label="Filmstrip">
      {frames.map((src, i) => {
        const on = selection ? i >= selection[0] && i < selection[1] : true;
        return (
          <img
            key={`${i}-${src}`}
            src={src}
            alt=""
            className={cn("aspect-video min-w-0 flex-1 object-cover", !on && "opacity-40")}
          />
        );
      })}
    </div>
  );
}
