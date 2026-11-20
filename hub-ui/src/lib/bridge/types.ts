// The hand-written part of the bridge's types. Every other shape is generated into types.gen.ts from
// discjockey/hub/shapes/ (`uv run python -m discjockey.hub.shapes --export`); edit the Python shapes, never the
// generated file. This file re-exports it, so the window imports every type from here, and keeps only what is
// generic: Res, JobStart, NOT_IN_PLAYLIST and the guards. A shape of a job's result is in schemas.gen.json (`results`).
export * from './types.gen';
import type { Fail, TodoItem, BatchCheckItem, QuestionItem, DuplicateItem } from './types.gen';

export type Res<T> = ({ ok: true } & T) | Fail;
export type JobStart = Res<{ job_id: string }>;
export const NOT_IN_PLAYLIST = '__not_in_playlist__';

export const isBatch = (i: TodoItem): i is BatchCheckItem => i.group === 'rekordbox_check' && !!i.batch;
export const isQuestion = (i: TodoItem): i is QuestionItem => i.group === 'same_song' && !!i.pair;
export const isDuplicate = (i: TodoItem): i is DuplicateItem => i.group === 'duplicate' && !!i.pair;
