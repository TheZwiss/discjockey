// Another process's job holds the library, in the fake backend: what the banner names (the engine's `Jobs._holder_of`,
// its words `words.job_title` / `words.holder_text`, ported here for the two kinds the fake runs). Scenarios (open with
// ?scenario=<name>):
//   console          a Terminal sync at "4 of 60" (the state fields below stay unset: the pages' own fakes set only
//                    `console_running` and mean this)
//   console:tidy     a Terminal tidy-up at "12 of 80 · Techno"
//   console:unknown  a holder the registry knows nothing of (an older Discjockey): the sentence for one nobody can name
//   console:sync-live, -reading, -running, -ended   a Terminal sync the window can follow (`terminalJob.ts`)
import type { FakeState } from './data';
import type { HubEvent } from '../events';
import type { ConsoleHolder } from '../types';

const TITLES: Record<string, string> = { sync: 'Sync', tidy: 'Tidy-up' };
/** The progress line each kind runs at in the fake (the engine's `words.job_line`) */
const LINES: Record<string, string> = { sync: '4 of 60', tidy: '12 of 80 · Techno' };
const UNNAMED = 'A Discjockey command is running in the Terminal';
export const JOB = 'job:00000c0d';
/** How a followable Terminal sync of the fake runs (`terminalJob.ts`), by scenario */
export type TerminalMode = 'live' | 'reading' | 'running' | 'ended';
export const TERMINAL_SCENARIOS: Record<string, TerminalMode> = {
  'console:sync-live': 'live', 'console:sync-reading': 'reading', 'console:sync-running': 'running', 'console:sync-ended': 'ended',
};

/** `words.holder_text` for a Terminal job */
const holderText = (kind: string, line: string | null) =>
  `${TITLES[kind] ?? kind.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())} running in the Terminal${line ? ` · ${line}` : ''}`;

/** Who holds the library besides the window, as `{job, via, kind, line, text, where}`; null while none does. A state with only
 *  `console_running` set is a Terminal sync at "4 of 60". */
export function consoleHolder(s: FakeState): ConsoleHolder | null {
  if (!s.console_running) return null;
  if (s.console_unnamed) return { job: null, via: null, kind: null, line: null, text: UNNAMED, where: null };
  const kind = s.console_kind ?? 'sync';
  const line = s.console_line === '' ? null : s.console_line ?? LINES[kind] ?? null;
  return { job: JOB, via: 'terminal', kind, line, text: holderText(kind, line), where: 'In the Terminal' };
}

/** Puts the Terminal's `kind` job in (running) or takes it out; a running `kind` of null is a holder nobody can name */
export function setConsole(s: FakeState, running: boolean, kind: string | null = 'sync'): void {
  s.console_running = running;
  s.console_unnamed = running && kind === null;
  s.console_kind = running ? kind : null;
  s.console_line = running && kind ? LINES[kind] ?? null : null;
}

/** The `ConsoleBusy` event for the state as it stands */
export function consoleEvent(s: FakeState): HubEvent {
  const h = consoleHolder(s);
  return { type: 'ConsoleBusy', running: h !== null, job: h?.job ?? null, kind: h?.kind ?? null, line: h?.line ?? null,
    text: h?.text ?? null, where: h?.where ?? null };
}

export const consoleScenarios: Record<string, (s: FakeState) => void> = {
  'console:tidy': (s) => setConsole(s, true, 'tidy'),
  'console:unknown': (s) => setConsole(s, true, null),
  ...Object.fromEntries(Object.keys(TERMINAL_SCENARIOS).map((name) => [name, (s: FakeState) => setConsole(s, true, 'sync')])),
};
