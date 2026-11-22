// The Sync plan's identity in the fake (issue 39 phase 2, V2.3a): the ids of its actions, its `plan_id`, and the "how many"
// presets, as `run.action_ids`, `HubApi._store_sync_plan` and `views.how_many` give them. A small helper of its own: the
// window's `planModel.presets` goes in V2.3b, so the fake must not lean on it.
import type { PreviewAction, SyncPreset, SyncPreview } from '../types';
import { actionId, hash } from './data';

type Scope = { off: string[]; weekly_off: string[] };
type Parts = Pick<SyncPreview, 'groups' | 'never' | 'folders' | 'estimate'>;
export type PlanIdentity = Pick<SyncPreview, 'plan_id' | 'presets' | 'default_how_many'>;

const DOWNLOADS = ['acquire', 'upgrade'];
const HOW_MANY_STEPS = [5, 10, 25, 50];

/** A stand-in for the engine's hash of the plan: 12 hex digits that change when the set of actions does. */
function planIdOf(ids: string[]): string {
  const text = JSON.stringify([...ids].sort());
  const hex = (n: number) => (n >>> 0).toString(16).padStart(8, '0');
  return `plan:${(hex(hash(text)) + hex(hash(`${text}|`))).slice(0, 12)}`;
}

/** `views.scope_kind`: the kind a row is switched by (`retry`, `weekly`, or its own kind word). */
const scopeKind = (a: PreviewAction): string =>
  a.kind === 'acquire' ? (a.reason === 'retry' ? 'retry' : 'new') : a.kind === 'upgrade' ? 'weekly' : a.kind;

/** `views.in_scope`: any playlist of the row on keeps it; else its innermost folder and those around it must be on. */
export function inScope(a: PreviewAction, scope: Scope): boolean {
  if (scope.weekly_off.includes(scopeKind(a))) return false;
  if (!a.in.length || a.in.some((t) => t.startsWith('playlist:') && !scope.off.includes(t))) return true;
  const folders = a.in.filter((t) => t.startsWith('folder:'));
  return folders.length > 0 && folders.every((f) => !scope.off.includes(f));
}

/** `views.how_many` over the rows (in `run` order), with `left` the daily allowance left (null: no limit). */
export function howMany(rows: PreviewAction[], left: number | null, scope: Scope):
  { presets: SyncPreset[]; default_how_many: string | null } {
  const scoped = rows.filter((a) => inScope(a, scope)).sort((a, b) => (a.run ?? 0) - (b.run ?? 0));
  if (!scoped.length) return { presets: [], default_how_many: null };
  const total = scoped.filter((a) => DOWNLOADS.includes(a.kind)).length;
  const fits = left !== null && left > 0 && left < total;
  const offered: { key: SyncPreset['key']; label: string; n: number }[] = HOW_MANY_STEPS
    .filter((n) => n < total && !(fits && n === left)).map((n) => ({ key: String(n) as SyncPreset['key'], label: String(n), n }));
  if (fits) offered.push({ key: 'fits', label: `${left} · fits today`, n: left });
  offered.push({ key: 'all', label: total ? `All ${total}` : 'All', n: total });
  const ticks = (n: number): string[] => {
    let done = 0;
    return scoped.filter((a) => !DOWNLOADS.includes(a.kind) || done++ < n).map((a) => a.id);
  };
  return { presets: offered.sort((a, b) => a.n - b.n).map((o) => ({ key: o.key, label: o.label, downloads: o.n, selected: ticks(o.n) })),
    default_how_many: fits ? 'fits' : 'all' };
}

/** Numbers the rows of a preview (grouped and never) and answers the plan's identity: its id, the presets and the default.
 *  Idempotent: a scenario that changes the rows runs it again on the final plan. */
export function numberPlan(p: Parts, scope: Scope): PlanIdentity {
  for (const a of [...p.groups.flatMap((g) => g.actions), ...p.never]) a.id = actionId(a, p.folders);
  const rows = p.groups.flatMap((g) => g.actions);
  return { plan_id: planIdOf(rows.map((a) => a.id)), ...howMany(rows, p.estimate?.left ?? null, scope) };
}
