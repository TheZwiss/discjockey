// Auto-upgrade in the fake backend (issue 33 stage C): Settings' and Setup's switch, rekordbox's state, the marks on a
// parked upgrade and the words To-do and the Sync page read them with. The real engine: discjockey/auto_upgrade.py,
// hub/api.py (set_auto_upgrade, rekordbox_status, _auto_upgrade_ready), hub/views.py (upgrade_detail, auto_refused_view).
// The switch lives in `s.setup.auto_upgrade` (setup_status answers it as it is); rekordbox's state in
// `s.rekordbox_state` / `s.rekordbox_running` (the dev toolbar's "rekordbox open" sets the latter).
import type { AutoRefused, RekordboxStatus, SyncPreview, Upgrade } from '../types';
import type { FakeState, FakeTrack } from './data';

/** The switch (on unless the state says off). */
export const autoOn = (s: FakeState): boolean => s.setup.auto_upgrade !== false;

/** `rekordbox_status()`: the library's state and whether rekordbox runs. */
export const rekordboxStatus = (s: FakeState): RekordboxStatus =>
  ({ state: s.rekordbox_state ?? 'ready', running: !!s.rekordbox_running });

/** views.AUTO_REFUSED_SHORT: the short word of a refusal in To-do's row. */
export const AUTO_REFUSED_SHORT: Record<AutoRefused['reason'], string> = {
  timing: "couldn't line it up", not_analysed: 'not analysed in rekordbox', cloud: 'in Cloud Library Sync',
  space: 'not enough free space', needs_choice: "couldn't compare it",
};
export const AUTO_WAITING_DETAIL = 'Waits for rekordbox to be closed';
/** views.AUTO_BATCH_DETAIL */
export const AUTO_BATCH_DETAIL = 'Upgraded during your sync';
/** The engine's words for a refusal (preview.REASON_WORDS), recorded on the parked upgrade by the sync. */
export const AUTO_REFUSED_WORDS: Record<AutoRefused['reason'], string> = {
  timing: "Discjockey couldn't line the new file up with your rekordbox track exactly; analyse the track again in rekordbox and try again",
  not_analysed: "rekordbox hasn't analysed this track yet, so Discjockey can't tell exactly where your cues sit; analyse it in rekordbox, quit rekordbox, and try again",
  cloud: 'This track is in rekordbox\'s Cloud Library Sync, which Discjockey does not change; upgrade it by hand',
  space: 'There is not enough free space on the drive for the new AIFF; free some space and try again',
  needs_choice: "Discjockey couldn't compare the two files to the sample; open the track and choose how to replace it",
};

/** views.auto_waits_mark: the sync met rekordbox open for this upgrade; only while the switch is on and Same track could run. */
export const autoWaits = (s: FakeState, up: Upgrade & { cutoff_hz?: null }, sameTrackOk: boolean): boolean =>
  autoOn(s) && !!up.auto_waits && sameTrackOk;

/** views.upgrade_detail: an Upgrade ready row's short line. `same` is the row's quick `same_track` answer. */
export function autoDetail(s: FakeState, t: FakeTrack, same: string | null, plain: string): string {
  const up = t.upgrade!;
  if (autoWaits(s, up, same === null)) return AUTO_WAITING_DETAIL;
  const r = up.auto_refused;
  if (r && AUTO_REFUSED_SHORT[r.reason]) {
    const different = up.alignment?.result === 'different';
    if (same === null || (same === r.reason && !different)) return `Not upgraded at your sync · ${AUTO_REFUSED_SHORT[r.reason]}`;
  }
  return plain;
}

/** `sync_preview().auto_upgrade`: the upgrades the sync's last phase would put in place (waiting ones included), the
 *  recorded refusals left out; null while the switch is off. */
export function autoPreview(s: FakeState, ready: number): SyncPreview['auto_upgrade'] {
  return autoOn(s) ? { on: true, ready } : null;
}
