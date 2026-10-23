// Replies that may come back out of order (two quick refreshes: a JobFinished, then a data bump): `next()` numbers a
// request, and only the newest one's reply may be applied (`isLatest`). The older reply is dropped, so it can't put
// an older state back over a newer one (final review M12).
export function latestOnly() {
  let n = 0;
  return {
    next: (): number => ++n,
    isLatest: (ticket: number): boolean => ticket === n,
  };
}
