import { Tooltip } from "radix-ui";

export type QualityWord = "Excellent" | "Good" | "Fair" | "Poor" | "None";

export interface QualityRowProps {
  sharpness: QualityWord;
  steadiness: QualityWord;
  exposure: QualityWord;
  audio: QualityWord;
}

const HELP: Record<keyof QualityRowProps, string> = {
  sharpness: "How crisp the frames are, from edge detail in the sampled frames.",
  steadiness: "How steady the camera is, from the camera's motion sensor or the picture itself.",
  exposure: "Whether the picture is too dark or too bright.",
  audio: "Wind, clipping and loudness of the sound.",
};

/** Ordinal words, never numbers (COMPONENTS.md); each explains itself in a tooltip. */
export function QualityRow(props: QualityRowProps) {
  const keys = ["sharpness", "steadiness", "exposure", "audio"] as const;
  return (
    <Tooltip.Provider delayDuration={300}>
      <dl className="grid grid-cols-4 gap-3">
        {keys.map((k) => (
          <Tooltip.Root key={k}>
            <Tooltip.Trigger asChild>
              <div tabIndex={0} className="flex flex-col gap-0.5 rounded-sm focus-visible:outline-2 focus-visible:outline-accent">
                <dt className="text-caption text-text-faint capitalize">{k}</dt>
                <dd className="text-small text-text">{props[k]}</dd>
              </div>
            </Tooltip.Trigger>
            <Tooltip.Portal>
              <Tooltip.Content
                sideOffset={6}
                className="max-w-60 rounded-md border border-border bg-surface-2 px-3 py-2 text-caption font-normal text-text shadow-[0_12px_32px_rgba(0,0,0,0.4)]"
              >
                {HELP[k]}
              </Tooltip.Content>
            </Tooltip.Portal>
          </Tooltip.Root>
        ))}
      </dl>
    </Tooltip.Provider>
  );
}
