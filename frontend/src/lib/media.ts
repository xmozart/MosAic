/** URLs of the media endpoints (ADR 0037). */
export const media = {
  proxy: (pid: string, aid: number) => `/api/media/${pid}/proxy/${aid}`,
  frame: (pid: string, sampleId: number) => `/api/media/${pid}/frame/${sampleId}`,
  filmstrip: (pid: string, aid: number, n = 8, range?: { startTicks?: number; endTicks?: number }) => {
    const q = new URLSearchParams({ n: String(n) });
    if (range?.startTicks !== undefined) q.set("start_ticks", String(range.startTicks));
    if (range?.endTicks !== undefined) q.set("end_ticks", String(range.endTicks));
    return `/api/media/${pid}/filmstrip/${aid}?${q.toString()}`;
  },
  waveform: (pid: string, aid: number) => `/api/media/${pid}/waveform/${aid}`,
};

export function decodePeaks(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
