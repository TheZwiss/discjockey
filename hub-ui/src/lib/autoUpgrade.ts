// "Upgrade automatically when I sync" (issue 33 stage C, plan §3 and §6): the words Settings' Upgrades panel and
// Setup's Downloads card share, and the two small rules both need. The switch is on unless setup_status says false
// (a missing key reads as on); it saves at once (set_auto_upgrade, run by the caller) and shows the value being saved
// until the job ends. Pure: no bridge here.

export const AUTO_UPGRADE_LABEL = 'Upgrade automatically when I sync';
/** Settings' switch row, second line (design §8). */
export const AUTO_UPGRADE_SUB = 'Same-edit upgrades replace your files at the end of a sync while rekordbox is closed; '
  + 'cues stay, and you can undo each one. Also the ones waiting now.';
/** Setup's switch row, second line (design §8). */
export const AUTO_UPGRADE_SETUP_SUB = 'When a lossless version is the same recording, the sync puts it in place of your '
  + 'file; your cues stay. Only while rekordbox is closed; your old file goes to Superseded/.';
/** The ⓘ behind Settings' switch (plan §3). */
export const AUTO_UPGRADE_TIP = 'Only upgrades that are the same recording as your file, measured to the sample; a '
  + 'different edit always waits for your choice. Each sync\'s upgrades are one batch, with a backup of rekordbox\'s '
  + 'library first. Undo one track or all of them in To-do.';

/** The switch as saved: on unless the status says false (no status yet reads as the default, on). */
export const autoUpgradeOn = (auto_upgrade: boolean | undefined | null): boolean => auto_upgrade !== false;

/** What the switch shows: the value being saved while a save runs, else the saved one. */
export const shownAutoUpgrade = (saved: boolean | undefined | null, pending: boolean | null): boolean =>
  pending ?? autoUpgradeOn(saved);

/** Settings' row line (plan §3). */
export const autoUpgradeLine = (on: boolean): string =>
  (on ? 'Automatic at the end of each sync' : 'Off: upgrades wait for you in To-do');
