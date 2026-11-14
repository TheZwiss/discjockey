// The Library details' AIFF card in each U1 state of plan §6.4 S1, from the fake scenarios' own data (the same answers
// the page gets): whether the card shows, the button's look and words, why it may be off, the notes and rows, and that
// the finished Convert gives way to the check card.
import { describe, expect, it } from 'vitest';
import { createFakeBridge } from '$lib/bridge/fake/bridge';
import type { Todo, TodoItem, TrackAiff, TrackDetail } from '$lib/bridge/types';
import { aiffBlocked, aiffLabel, aiffNotes, aiffOutcomes, aiffRows, aiffShown, aiffVariant } from '$lib/decisions/aiffModel';
import { decisionFor } from '$lib/decisions';

const bridge = (n: string) => createFakeBridge(`library:${n}`, { speed: 1000 });
type F = ReturnType<typeof bridge>;
const detail = async (f: F, id: string) => ((await f.track(id)) as { ok: true; track: TrackDetail }).track;
const rbOf = async (f: F) => {
  const r = (await f.rekordbox_status()) as { ok: true; state: 'ready' | 'none' | 'unreadable'; running: boolean };
  return { state: r.state, running: r.running };
};
/** what the page derives for a track: the card (null: none), its button and why it is off */
async function card(scenario: string, id: string) {
  const f = bridge(scenario);
  const t = await detail(f, id);
  const todo = ((await f.todo('all', false)) as Todo & { ok: true }).groups.flatMap((g) => g.items as TodoItem[]);
  const decision = decisionFor(todo, t);
  const aiff = aiffShown(t.aiff, decision, false) ? t.aiff : null;
  const rb = await rbOf(f);
  return { t, decision, aiff, rb, label: aiff && aiffLabel(aiff), variant: aiff && aiffVariant(aiff), blocked: aiff && aiffBlocked(aiff, rb) };
}
const need = (a: TrackAiff | null): TrackAiff => { if (!a) throw new Error('no card'); return a; };

describe('the AIFF card in each state of the Library details', () => {
  it('aiff-flac: a lossless FLAC, Convert to AIFF filled, NOW BECOMES NAME SPACE, rekordbox ready: its three outcome rows less the step', async () => {
    const c = await card('aiff-flac', 'own:1');
    expect([c.label, c.variant, c.blocked]).toEqual(['Convert to AIFF', 'filled', null]);
    expect(aiffRows(need(c.aiff)).map((r) => r.key)).toEqual(['now', 'becomes', 'name', 'space']);
    expect(aiffOutcomes(need(c.aiff), c.rb).map((o) => o.tone)).toEqual(['kept', 'file']);
    expect(aiffNotes(need(c.aiff))).toEqual({ above: [], below: [] });
  });
  it('aiff-lossy: the lossy note under the card and an outlined button', async () => {
    const c = await card('aiff-lossy', 'own:10');
    expect([c.label, c.variant]).toEqual(['Convert to AIFF', 'outline']);
    expect(aiffNotes(need(c.aiff)).below.map((n) => n.key)).toEqual(['lossy']);
  });
  it('aiff-cdj: the warn note with the CDJs\' words above the card, the button filled', async () => {
    const c = await card('aiff-cdj', 'own:13');
    expect(c.variant).toBe('filled');
    const above = aiffNotes(need(c.aiff)).above;
    expect(above).toHaveLength(1);
    expect(above[0]).toMatchObject({ tone: 'warn', text: c.aiff!.cdj!.words });
  });
  it('aiff-rename: Give it its clean name, filled, the NAME row alone, no outcome rows', async () => {
    const c = await card('aiff-rename', 'own:7');
    expect([c.label, c.variant, c.blocked]).toEqual(['Give it its clean name', 'filled', null]);
    expect(aiffRows(need(c.aiff)).map((r) => r.key)).toEqual(['name']);
    expect(aiffOutcomes(need(c.aiff), c.rb)).toEqual([]);
  });
  it('aiff-blocked: rekordbox\'s library can\'t be opened: the card says what the file is, the button is off with the reason', async () => {
    for (const id of ['own:1', 'own:7']) {
      const c = await card('aiff-blocked', id);
      expect(c.aiff, id).not.toBeNull();
      expect(c.blocked, id).toMatch(/^Discjockey can't open rekordbox's library yet/);
      expect(aiffOutcomes(need(c.aiff), c.rb), id).toEqual([]);
    }
  });
  it('aiff-rename-blocked: rekordbox is open, the Rename is off with design §8\'s words; the Convert only adds its step', async () => {
    const rename = await card('aiff-rename-blocked', 'own:7');
    expect(rename.rb).toEqual({ state: 'ready', running: true });
    expect(rename.blocked).toMatch(/^rekordbox is open, so Discjockey can't point your track at the new name\.$/);
    const conv = await card('aiff-rename-blocked', 'own:1');
    expect(conv.blocked).toBeNull();
    expect(aiffOutcomes(need(conv.aiff), conv.rb).map((o) => o.tone)).toEqual(['kept', 'file', 'step']);
  });
  it('aiff-check-converted: the finished Convert has no card, the check card stands (a decision)', async () => {
    const c = await card('aiff-check-converted', 'own:1');
    expect(c.aiff).toBeNull();
    expect(c.decision).toMatchObject({ kind: 'check', item: { check: { reason: 'converted' } } });
  });
  it('no card for a clean AIFF with its name, or beside a parked upgrade', async () => {
    expect((await card('aiff-flac', 'own:8')).aiff).toBeNull();
    const normal = createFakeBridge('normal', { speed: 1000 });
    const up = ((await normal.track('t2')) as { ok: true; track: TrackDetail }).track;
    expect(up.upgrade).not.toBeNull();
    expect(aiffShown(up.aiff, { kind: 'upgrade' }, false)).toBe(false);
  });
});
