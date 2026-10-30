// What SummaryStrip says (plan library stage 5 A3.4, notes N5, words I7). Pure, so every case is pinned.
import type { Library } from '../bridge/types';
import { count } from '../format';

export type StripRow = { count: string; link: boolean };
export type StripView = {
  /** the lossless share as a whole number ("63"); null: "—" (waiting, no tracks, none checked yet) */
  share: string | null;
  /** under the share: "290 of 460 checked tracks"; '' while waiting (the line keeps its height) */
  line: string;
  upgrades: StripRow;
  notLossless: StripRow & {
    /** after "Not lossless yet ·", muted: "all in To-do" / "41 in To-do" / "none in To-do"; null with none at all */
    todo: string | null;
    /** the row's tooltip when fewer of them are in To-do than not lossless */
    tip: string | null;
  };
};

const WAIT = '—';

export function stripView(s: Library['summary'] | null): StripView {
  if (!s) {
    return { share: null, line: '', upgrades: { count: WAIT, link: false },
      notLossless: { count: WAIT, link: false, todo: null, tip: null } };
  }
  const checked = Object.values(s.by_quality).reduce((n, c) => n + c, 0);
  const share = s.tracks && s.lossless_share !== null ? String(Math.round(s.lossless_share * 100)) : null;
  const line = !s.tracks ? 'no tracks yet' : s.lossless_share === null ? 'none checked yet'
    : `${count(s.by_quality.lossless)} of ${count(checked)} checked tracks`;
  const n = s.not_lossless;
  const m = Math.min(s.to_do, n);
  // with nothing that isn't lossless there is nothing to say about To-do ("· none in To-do" beside a 0 says nothing)
  const todo = n === 0 ? null : m === n ? 'all in To-do' : m === 0 ? 'none in To-do' : `${count(m)} in To-do`;
  const tip = n > 0 && m < n ? `${m === 0 ? 'None' : count(m)} of them in To-do: files of your own in no playlist aren't` : null;
  return {
    share, line,
    upgrades: { count: count(s.upgrades_ready), link: s.upgrades_ready > 0 },
    notLossless: { count: count(n), link: m > 0, todo, tip },
  };
}
