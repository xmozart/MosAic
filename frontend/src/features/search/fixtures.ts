import type { SearchItem } from "./SearchView";

const CAMS = [
  { label: "iPhone 16 Pro", kind: "phone" as const },
  { label: "GoPro HERO12 Black", kind: "actioncam" as const },
  { label: "DJI Mini 4 Pro", kind: "drone" as const },
];

export function result(i: number, patch: Partial<SearchItem> = {}): SearchItem {
  return {
    segment_id: 100 + i,
    asset_id: i + 1,
    start: { ticks: 0, tb: "1/90000" },
    end: { ticks: (7 + i * 3) * 90000, tb: "1/90000" },
    sample_id: i + 1,
    status: (["USE", "MAYBE", null] as const)[i % 3] ?? null,
    decided_by: i === 0 ? "user" : i % 3 === 2 ? null : "ai",
    ai_status: "USE",
    score: 0.03 - i * 0.001,
    matched: i % 2 ? ["looks like: kids laughing, splashing"] : ["said: “it's right there!”", "looks like: laughing"],
    name: `IMG_${4470 + i}.MOV`,
    kind: "video",
    camera: CAMS[i % CAMS.length]!,
    stars: i === 0 ? 5 : null,
    has_speech: i % 2 === 0,
    ...patch,
  };
}

export const RESULTS = Array.from({ length: 12 }, (_, i) => result(i));
export const SUGGESTIONS = ["toucan", "drone at sunset", "waterfalls", "zipline", "dolphins"];
