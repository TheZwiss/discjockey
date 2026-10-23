// Fake mode only: the engine's views.minutes_by_downloads (≈ 70 s per download, rounded to 5 minutes, at least 5).
// The real page never computes this; it looks the count up in `estimate.minutes_by_downloads`.
const SECONDS_PER_DOWNLOAD = 70;

/** Python's round(): halves go to the even neighbour (round(10.5) == 10). */
function roundHalfEven(x: number): number {
  const f = Math.floor(x);
  const d = x - f;
  return d > 0.5 + 1e-9 ? f + 1 : d < 0.5 - 1e-9 ? f : f % 2 === 0 ? f : f + 1;
}

const runMinutes = (downloads: number) =>
  downloads <= 0 ? 0 : Math.max(5, 5 * roundHalfEven((downloads * SECONDS_PER_DOWNLOAD) / 300));

/** views.minutes_by_downloads: the minutes for 0 … `most` downloads. */
export const minutesByDownloads = (most: number): number[] =>
  Array.from({ length: Math.max(most, 0) + 1 }, (_, n) => runMinutes(n));
