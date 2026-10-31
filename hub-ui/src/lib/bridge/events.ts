// Engine and hub events, exactly as tests/fixtures/hub_events.schema.json (spec §6.4, contract "Events").
import type { AppUpdate, Browser, PlannedAction, PlaylistService, ProblemKind, Result } from './types';

export type SourceTrack = { id: string; title: string; artists: string[]; album: string; image_url: string | null;
  duration_ms: number; isrc: string | null; service: string; link: string | null; streamable: boolean;
  /** SoundCloud: only the Go+ account plays the whole track (a free try would download a 30 s preview) */
  account_only: boolean };
export type Action = { kind: 'acquire' | 'adopt_bought' | 'upgrade' | string; track_id: string;
  folder: string; track: SourceTrack; order: [number, number]; src: string | null; dest_dir: string | null;
  aliases: string[]; reason: string; qobuz_id: string | null;
  /** the playlist's own SoundCloud / YouTube Music upload of the song, tried after Qobuz (null: none) */
  upload: SourceTrack | null };
export type Step = 'search' | 'download' | 'check' | 'convert' | 'analyse' | 'compare';
export type HubEvent =
  | { type: 'RunStarted'; total: number; actions: PlannedAction[] }
  | { type: 'ActionStarted'; index: number; total: number; action: Action }
  | { type: 'StepChanged'; track_id: string; step: Step }
  | { type: 'Progress'; track_id: string; step: Step; done: number; total: number | null; unit: 'bytes' | 'seconds' }
  | { type: 'Waiting'; kind: 'search' | 'between' | 'break' | 'fallback'; label: string; remaining: number;
      total: number; service: string }
  | { type: 'SourceChosen'; track_id: string; source: string; query_kind: 'exact' | 'isrc' | 'name' | 'fallback' | 'chosen' | 'upload';
      title: string; duration_s: number | null }
  | { type: 'Checked'; track_id: string; file_duration_s: number; track_duration_s: number; codec: string;
      ok: boolean }
  | { type: 'AccountUsage'; service: string; used: number; allowance: number }
  | { type: 'ActionFinished'; action: Action; result: Result }
  | { type: 'RunFinished'; exit_code: number; report_path: string }
  | { type: 'Message'; level: 'info' | 'warning' | 'debug'; text: string }
  | { type: 'ReadingPlaylist'; index: number; total: number; folder: string }
  | { type: 'MovesProgress'; batch_id: number; done: number; total: number }
  | { type: 'ImportProgress'; phase: 'scan' | 'tags' | 'sound' | 'link'; done: number; total: number; unreadable: number }
  | { type: 'JobStarted'; job_id: number; kind: string; track_id: string | null }
  | { type: 'JobFinished'; job_id: number; kind: string; ok: boolean; problem: ProblemKind | null; message: string;
      result: any | null; service?: PlaylistService | null }
  | { type: 'ConsoleBusy'; running: boolean }
  | { type: 'FileDropped'; track_id: string | null; name: string; readable: boolean; message: string }
  | { type: 'SignInPhase'; service: 'youtube' | 'soundcloud'; phase: 'waiting' | 'checking'; browser: Browser;
      browser_name: string }
  | { type: 'AppUpdate'; state: AppUpdate['state']; current: string; latest: string | null; url: string | null }
  /** a watched folder came or went while the window is open (a drive plugged in or ejected): `away` folders now */
  | { type: 'DrivesChanged'; away: number };
export type EventOf<T extends HubEvent['type']> = Extract<HubEvent, { type: T }>;

/** The 21 names, same order as the schema's oneOf. */
export const EVENT_TYPES = ['RunStarted', 'ActionStarted', 'StepChanged', 'Progress', 'Waiting', 'SourceChosen',
  'Checked', 'AccountUsage', 'ActionFinished', 'RunFinished', 'Message', 'ReadingPlaylist', 'MovesProgress', 'ImportProgress', 'JobStarted', 'JobFinished', 'ConsoleBusy',
  'FileDropped', 'SignInPhase', 'AppUpdate', 'DrivesChanged'] as const satisfies readonly HubEvent['type'][];

/** Runtime copy of the field names above, so a renamed field breaks a test (spec §9). */
export const EVENT_FIELDS: { [T in HubEvent['type']]: readonly (keyof EventOf<T>)[] } = {
  RunStarted: ['type', 'total', 'actions'],
  ActionStarted: ['type', 'index', 'total', 'action'],
  StepChanged: ['type', 'track_id', 'step'],
  Progress: ['type', 'track_id', 'step', 'done', 'total', 'unit'],
  Waiting: ['type', 'kind', 'label', 'remaining', 'total', 'service'],
  SourceChosen: ['type', 'track_id', 'source', 'query_kind', 'title', 'duration_s'],
  Checked: ['type', 'track_id', 'file_duration_s', 'track_duration_s', 'codec', 'ok'],
  AccountUsage: ['type', 'service', 'used', 'allowance'],
  ActionFinished: ['type', 'action', 'result'],
  RunFinished: ['type', 'exit_code', 'report_path'],
  Message: ['type', 'level', 'text'],
  ReadingPlaylist: ['type', 'index', 'total', 'folder'],
  MovesProgress: ['type', 'batch_id', 'done', 'total'],
  ImportProgress: ['type', 'phase', 'done', 'total', 'unreadable'],
  JobStarted: ['type', 'job_id', 'kind', 'track_id'],
  JobFinished: ['type', 'job_id', 'kind', 'ok', 'problem', 'message', 'result', 'service'],
  ConsoleBusy: ['type', 'running'],
  FileDropped: ['type', 'track_id', 'name', 'readable', 'message'],
  SignInPhase: ['type', 'service', 'phase', 'browser', 'browser_name'],
  AppUpdate: ['type', 'state', 'current', 'latest', 'url'],
  DrivesChanged: ['type', 'away'],
};
export const ACTION_FIELDS: readonly (keyof Action)[] = ['kind', 'track_id', 'folder', 'track', 'order', 'src',
  'dest_dir', 'aliases', 'reason', 'qobuz_id', 'upload'];
export const TRACK_FIELDS: readonly (keyof SourceTrack)[] = ['id', 'title', 'artists', 'album', 'image_url',
  'duration_ms', 'isrc', 'service', 'link', 'streamable', 'account_only'];
export const RESULT_FIELDS: readonly (keyof Result)[] = ['section', 'folder', 'artist', 'title', 'track_id', 'note',
  'status', 'source', 'cutoff_hz', 'path', 'error_kind', 'found_status'];

type Listener = (e: HubEvent) => void;
const listeners = new Set<Listener>();

type Sink = { queue?: HubEvent[]; onEvent(e: HubEvent): void };
declare global {
  interface Window { dj?: Sink }
}

/** Sends one event to every subscriber; a failing subscriber never stops the others. */
export function dispatch(e: HubEvent): void {
  if (!e || typeof e !== 'object' || typeof (e as { type?: unknown }).type !== 'string') return;
  for (const fn of [...listeners]) {
    try {
      fn(e);
    } catch (err) {
      if (import.meta.env.DEV) console.warn('event listener failed', err);
    }
  }
}

/** Drains the inline script's window.dj.queue, then routes window.dj.onEvent to dispatch. */
export function installEventSink(): void {
  const old = window.dj;
  const queued = old?.queue ?? [];
  window.dj = { onEvent: dispatch };
  for (const e of queued) dispatch(e);
}

/** Subscribe; returns unsubscribe. */
export function onEvent(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}
