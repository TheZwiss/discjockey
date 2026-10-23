// The day bar's segments (design system §7, DayBar): what a run does today against what waits for later days under
// the daily download limit. Pure: the page passes the numbers, DayBar draws the segments.
import { plural } from '../format';

/** `today` tracks download in this run, `later` wait for the next days (only with a daily limit, `limited`),
 *  `laterDays` is how many more days they take (0 or 1 reads "Tomorrow"), `moves` are file moves that need no
 *  download and so still happen when the limit is reached. `day` (day mode, Dashboard) draws the whole daily limit:
 *  what earlier runs `used` today ahead of this sync, and what is still left of the `allowance` after it. */
export type DayBarInput = { today: number; later: number; limited: boolean; laterDays: number; moves: number;
  day?: { used: number; allowance: number } };
/** One segment: `grow` is its flex-grow share of the bar, `n` the tracks it stands for (`used`, `free`: day mode). A `fit` segment ("Today:
 *  3 moves" once the limit is reached) takes no share and is exactly as wide as its label, so it always reads. */
export type DaySeg = { kind: 'used' | 'today' | 'later' | 'free'; n: number; label: string; grow: number; fit: boolean };

/** The moves-only segment's label (DayBar measures it ahead, so the segment can slide to its width). */
export const movesLabel = (moves: number, day = false) => `${day ? 'This sync' : 'Today'}: ${plural(moves, 'move')}`;

export function dayBar(i: DayBarInput): { segs: DaySeg[]; caption: string | null } {
  const segs: DaySeg[] = [];
  // "Today" beside "Used" would read as "used today", so day mode names this sync's share by the sync
  const day = i.limited ? i.day : undefined;
  if (day && day.used > 0) segs.push({ kind: 'used', n: day.used, label: `Used ${day.used}`, grow: day.used, fit: false });
  if (i.today > 0) segs.push({ kind: 'today', n: i.today, label: `${day ? 'This sync' : 'Today'} ${i.today}`, grow: i.today,
    fit: false });
  else if (i.moves > 0) segs.push({ kind: 'today', n: 0, label: movesLabel(i.moves, !!day), grow: 0, fit: true });
  if (i.limited && i.later > 0) segs.push({ kind: 'later', n: i.later, grow: i.later, fit: false,
    label: i.laterDays <= 1 ? `Tomorrow ${i.later}` : `Later ${i.later} · ~${i.laterDays} days` });
  const free = day && !i.later ? Math.max(0, day.allowance - day.used - i.today) : 0;
  if (free > 0) segs.push({ kind: 'free', n: free, label: `${free} left`, grow: free, fit: false });
  return { segs, caption: i.limited ? null : 'No daily limit' };
}
