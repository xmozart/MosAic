// Stand-in frames for stories only: the product always shows real sample frames from
// /api/media (docs/ui/README.md rule 2).
const PALETTES = [
  ["#1f3a2c", "#2e5a40", "#a9c2bc"],
  ["#2f5a2f", "#6a9656", "#ffb13b"],
  ["#1d2b4a", "#3d5a8a", "#e6efec"],
  ["#3a2a12", "#8a5a22", "#f2d3a1"],
  ["#2b1f3a", "#5a3d7a", "#d6c3f0"],
];

export function frame(seed: number, step = 0): string {
  const p = PALETTES[seed % PALETTES.length] ?? PALETTES[0]!;
  const x = 20 + ((step * 13) % 60);
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90"><defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${p[0]}"/><stop offset="1" stop-color="${p[1]}"/></linearGradient></defs><rect width="160" height="90" fill="url(#g)"/><circle cx="${x}" cy="40" r="14" fill="${p[2]}" opacity="0.8"/></svg>`;
  return `data:image/svg+xml,${encodeURIComponent(svg)}`;
}

export function frames(seed: number, n = 8): string[] {
  return Array.from({ length: n }, (_, i) => frame(seed, i));
}
