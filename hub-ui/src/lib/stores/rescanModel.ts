// When the window asks Discjockey to look at Library/ again (spec library §6.4): when it opens, and when it comes
// back to the front after more than a minute in the background. Pure; rescan.ts wires it to the window.

/** The window must have been in the background for longer than this. */
export const RESCAN_AFTER_MS = 60_000;

/** `hiddenSince`: when the window went to the background (ms), null when it did not. */
export function shouldRescan(hiddenSince: number | null, now: number): boolean {
  return hiddenSince !== null && now - hiddenSince > RESCAN_AFTER_MS;
}
