// The Sync scope in the fake (issue 39 V2.5b): settings.json's `sync_scope`, as the engine words it (`HubApi.sync_scope`).
import type { SyncScope } from '../types';
import { playlistRef, type FakeState } from './data';

export const SCOPE_KIND_LABELS = { retry: 'Not found last time', weekly: 'Weekly checks' } as const;
export const SCOPE_KIND_ITEMS = ['kind:retry', 'kind:weekly'];
/** `playlist:<ref>` or `folder:<path>`, with something after the colon (what the engine's `is_scope_target` accepts). */
export const isScopeTarget = (i: string): boolean => /^(playlist|folder):./.test(i);

/** A target by its name: a playlist by its line's folder, a folder by the last part of its path; one nothing has any
 *  more by the target itself (a folder on a drive that is away comes back). */
function nameOf(s: FakeState, target: string): string {
  if (target.startsWith('playlist:')) {
    return s.playlists.find((p) => `playlist:${playlistRef(p.link)}` === target)?.folder ?? target;
  }
  return target.slice('folder:'.length).replace(/\/+$/, '').split('/').pop() || target;
}

export function scopeOf(s: FakeState): SyncScope {
  return {
    off: s.scope.off.map((target) => ({ target, name: nameOf(s, target) })),
    weekly_off: s.scope.weekly_off.map((kind) => ({ kind, label: SCOPE_KIND_LABELS[kind] })),
  };
}
