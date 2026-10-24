// The day bar's segments (design system §7, DayBar): what a run does today against what waits for later days under
// the daily download limit. Pure: the page passes the numbers, DayBar draws the segments.
/** `today` tracks download in this run, `later` wait for the next days (only with a daily limit, `limited`),
 *  `laterDays` is how many more days they take (0 or 1 reads "Tomorrow"). `day` (day mode, Dashboard) draws the whole daily limit:
 *  what earlier runs `used` today ahead of this sync, and what is still left of the `allowance` after it. */
export type DayBarInput = { today: number; later: number; limited: boolean; laterDays: number;
  day?: { used: number; allowance: number } };
/** One segment: `grow` is its flex-grow share of the bar, `n` the tracks it stands for (`used`, `free`: day mode). */
export type DaySeg = { kind: 'used' | 'today' | 'later' | 'free'; n: number; label: string; grow: number };

export function dayBar(i: DayBarInput): { segs: DaySeg[]; caption: string | null } {
  const segs: DaySeg[] = [];
  // "Today" beside "Used" would read as "used today", so day mode names this sync's share by the sync
  const day = i.limited ? i.day : undefined;
  if (day && day.used > 0) segs.push({ kind: 'used', n: day.used, label: `Used ${day.used}`, grow: day.used });
  if (i.today > 0) segs.push({ kind: 'today', n: i.today, label: `${day ? 'This sync' : 'Today'} ${i.today}`, grow: i.today });
  if (i.limited && i.later > 0) segs.push({ kind: 'later', n: i.later, grow: i.later,
    label: i.laterDays <= 1 ? `Tomorrow ${i.later}` : `Later ${i.later} · ~${i.laterDays} days` });
  const free = day && !i.later ? Math.max(0, day.allowance - day.used - i.today) : 0;
  if (free > 0) segs.push({ kind: 'free', n: free, label: `${free} left`, grow: free });
  return { segs, caption: i.limited ? null : 'No daily limit' };
}
