/** The days `rest` downloads take, today counted only when something is left today: 1 if they fit today's
 * `remaining`, else 1 + ceil((rest − remaining) ÷ limit); with nothing left today they start tomorrow:
 * ceil(rest ÷ limit). 0 when nothing is left. The twin of views.days_to_load, so every page says the same. */
export function daysToLoad(rest: number, remaining: number, limit: number): number {
  if (rest <= 0) return 0;
  const today = Math.max(0, remaining);
  if (rest <= today) return 1;
  return (today ? 1 : 0) + Math.ceil((rest - today) / limit);
}
