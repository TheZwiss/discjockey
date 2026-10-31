// ChoiceGroup's and OutcomeList's types (design language "each kind of choice has exactly one form": one of a few,
// each with a consequence). An outcome is one short line of what a choice does, with a glyph and a colour that say
// which kind of consequence it is: kept (green ✓: stays as it was, or fits), step (yellow ⓘ: needs a step from you),
// lost (red ✕: something is lost), file (grey folder: where a file goes). Decision log 2026-10-31.
export type OutcomeTone = 'kept' | 'step' | 'lost' | 'file';
export type Outcome = { tone: OutcomeTone; text: string };

/** One row of a ChoiceGroup. `name`: the choice; `recommended`: the app's pick (accent caps after the name); `summary`:
 *  its one line while another row is picked; `outcomes`: what it does, shown while it is picked (else the summary);
 *  `disabled` + `reason`: a row that can't be picked, dimmed, the reason as its line; `ruled`: set off from the rows
 *  above by a full rule (a "neither" answer such as Keep both). */
export type ChoiceOption<K extends string | number = string> = {
  key: K; name?: string; recommended?: boolean; summary?: string; outcomes?: Outcome[]; disabled?: boolean;
  reason?: string; ruled?: boolean; test?: string;
};

/** The key arrow keys move to from `from` (`step` ±1), skipping rows that can't be picked, wrapping round. */
export function stepChoice<K extends string | number>(options: ChoiceOption<K>[], from: K | null, step: 1 | -1): K | null {
  const open = options.filter((o) => !o.disabled);
  if (!open.length) return null;
  const i = open.findIndex((o) => o.key === from);
  if (i < 0) return open[step > 0 ? 0 : open.length - 1].key;
  return open[(i + step + open.length) % open.length].key;
}
