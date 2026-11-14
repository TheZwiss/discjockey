// What the AIFF card says for one track (issue 33 stage D, plan §6.1, §3), shared by the Library's details and, in U3,
// To-do's CDJ item: when the card shows, its rows, the notes above and under it, the outcome rows, the button (its
// words and whether it is the screen's filled one) and why it may be off. Pure: the card and its foot only draw this.
import type { AiffBatchResult, RekordboxStatus, TrackAiff } from '$lib/bridge/types';
import type { JobOutcome } from '$lib/bridge/client';
import type { Outcome } from '$lib/components/choiceModel';
import { sizeWords } from '$lib/format';
import { BECOMES_AIFF, QUIT_REKORDBOX, type Decision } from './decisionModel';

/** What a Convert makes, as `track().aiff.to` says it. */
export const AIFF_LINE = 'AIFF · 16-bit · 44.1 kHz';
/** The reasons that show the card without an action: it says why the button is off. */
export const BLOCKING = ['rekordbox_unreadable', 'cloud', 'rename_blocked'] as const;

export const CONVERT_LABEL = 'Convert to AIFF';
export const RENAME_LABEL = 'Give it its clean name';
/** Design §8's one-track outcome rows of a Convert (the "Same track" ones: its rekordbox track stays). */
export const KEPT_TRACK: Outcome = { tone: 'kept', text: 'Your track keeps its cues, playlists and history' };
const QUIT_STEP: Outcome = { tone: 'step', text: QUIT_REKORDBOX };
/** Plan §3: the lossy note (info). */
export const LOSSY_NOTE = 'An AIFF made from this sounds the same and takes 5–10 times the space.';
/** `rename.BLOCKED_WHY`: the `{reason}` of design §8's "Refused, rename blocked". */
const RENAME_WHY = { open: 'rekordbox is open', unreadable: "rekordbox's library can't be opened",
  names: 'No free file name is left for it' } as const;
/** Design §8's refusals as the reason under a button that is off. The button never tried, so "Nothing was changed." is
 *  left out, and each sentence is cut to what fits a Hint (the rule checker allows 90 characters outside a card):
 *  the reason, then that Discjockey can't point the rekordbox track at the new file or name. */
const UNREADABLE_WHY = "Discjockey can't open rekordbox's library yet, so it can't point your track at the file.";
const CLOUD_WHY = "This track is in rekordbox's Cloud Library Sync, which Discjockey doesn't change yet.";
const renameWhy = (why: string): string => `${why}, so Discjockey can't point your track at the new name.`;

/** Whether the AIFF card shows: the engine has an answer for a file that is there (`aiff` null: no file, a download, a
 *  parked upgrade), it can run or says why it can't for one of the reasons the card explains, and no decision stands
 *  (an upgrade, the check a step left and a duplicate group win: their foot holds the screen's one filled button). */
export function aiffShown(aiff: TrackAiff | null | undefined, decision: Decision, away: boolean): aiff is TrackAiff {
  if (!aiff || decision || away) return false;
  return aiff.action !== null || (BLOCKING as readonly (string | null)[]).includes(aiff.why_not);
}

/** Whether the card's file is a clean AIFF whose name is left: what the button of a blocked card (no `action`) names. */
const isRename = (a: TrackAiff): boolean => a.action === 'rename' || (a.action === null && a.from === AIFF_LINE);
/** What the button starts: a Rename for a clean AIFF whose name is left, else a Convert. */
export const aiffAction = (a: TrackAiff): 'convert' | 'rename' => (isRename(a) ? 'rename' : 'convert');
export const aiffLabel = (a: TrackAiff): string => (isRename(a) ? RENAME_LABEL : CONVERT_LABEL);

/** `filled`: a lossless file, a file the CDJs refuse or a Rename; `outline`: any other lossy file (a choice that costs
 *  space, not a recommendation). */
export const aiffVariant = (a: TrackAiff): 'filled' | 'outline' => (a.lossy && !a.cdj && !isRename(a) ? 'outline' : 'filled');

/** Why the button is off, in design §8's words, shortened (null: it can run). The Rename also waits while rekordbox is open: it
 *  repoints rekordbox's track, which only works while rekordbox is closed (a Convert says it as an outcome row, and the
 *  engine's own `rekordbox_open` answer if pressed anyway). */
export function aiffBlocked(a: TrackAiff, rb: RekordboxStatus | null): string | null {
  switch (a.why_not) {
    case 'rekordbox_unreadable': return UNREADABLE_WHY;
    case 'cloud': return CLOUD_WHY;
    case 'rename_blocked': return renameWhy(RENAME_WHY.names);
    default: break;
  }
  if (a.action === 'rename' && rb && rb.state !== 'none') {  // no rekordbox library on this Mac: nothing to point
    if (rb.state === 'unreadable') return renameWhy(RENAME_WHY.unreadable);
    if (rb.running) return renameWhy(RENAME_WHY.open);
  }
  return null;
}

export type AiffRow = { key: 'now' | 'becomes' | 'name' | 'space'; k: string; v: string | null;
  /** NAME: the name now, then the name it gets; they stand on two lines */
  from?: string; to?: string };
/** The card's rows (plan §3): NOW, BECOMES, NAME and SPACE for a Convert, NAME alone for a Rename, NOW alone while it
 *  can't run (the file's format; nothing else is known). A name that doesn't change (an AIFF that stays where it was)
 *  is the name once. */
export function aiffRows(a: TrackAiff): AiffRow[] {
  if (a.action === null) return a.from ? [{ key: 'now', k: 'Now', v: a.from }] : [];
  const name: AiffRow = { key: 'name', k: 'Name', v: null, from: a.name_now, to: a.new_name && a.new_name !== a.name_now ? a.new_name : undefined };
  if (a.action === 'rename') return [name];
  return [{ key: 'now', k: 'Now', v: a.from }, { key: 'becomes', k: 'Becomes', v: a.to ?? AIFF_LINE }, name,
    { key: 'space', k: 'Space', v: `+${sizeWords(a.bytes)}; your original goes to Superseded/` }];
}

/** The one-track outcome rows of a Convert, only with a rekordbox Discjockey can open (design §8): the track keeps its
 *  cues, the file becomes an AIFF, and, only while rekordbox runs, the step to quit it. None for a Rename (its NAME row
 *  says it), for no rekordbox on this Mac, for one it can't open, and while its state isn't known. */
export function aiffOutcomes(a: TrackAiff, rb: RekordboxStatus | null): Outcome[] {
  if (a.action !== 'convert' || rb?.state !== 'ready') return [];
  return [KEPT_TRACK, BECOMES_AIFF, ...(rb.running ? [QUIT_STEP] : [])];
}

export type AiffNote = { key: 'cdj' | 'lossy'; tone: 'warn' | 'info'; text: string };
/** The notes of the card: what the CDJs refuse in the file (warn, its own words, above the card) and, for a Convert of a
 *  lossy file, what the AIFF costs (info, under it). */
export function aiffNotes(a: TrackAiff): { above: AiffNote[]; below: AiffNote[] } {
  return {
    above: a.cdj ? [{ key: 'cdj', tone: 'warn', text: a.cdj.words }] : [],
    below: a.action === 'convert' && a.lossy ? [{ key: 'lossy', tone: 'info', text: LOSSY_NOTE }] : [],
  };
}

/** `rekordbox_open` as a job's problem: design §8's words, when the engine's own are empty. */
export const REKORDBOX_OPEN_WORDS = 'rekordbox is open. Quit rekordbox, then try again. Discjockey changes your rekordbox tracks only while rekordbox is closed.';
/** What a finished job says when the track didn't go: a refusal or a problem with its own words (rekordbox open, the one
 *  song's reason), or the track's skipped / failed item. Null: it went (the check card follows). */
export function aiffProblem(out: JobOutcome<AiffBatchResult>): string | null {
  if (!out.ok) return out.message || (out.kind === 'rekordbox_open' ? REKORDBOX_OPEN_WORDS : "That didn't work.");
  const item = out.result?.results?.find((r) => r.state === 'skipped' || r.state === 'failed');
  if (!item) return null;
  return item.message || (item.reason === 'rekordbox_open' ? REKORDBOX_OPEN_WORDS : "That didn't work.");
}
