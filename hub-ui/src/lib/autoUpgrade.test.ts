import { describe, expect, it } from 'vitest';
import { AUTO_UPGRADE_LABEL, AUTO_UPGRADE_SETUP_SUB, AUTO_UPGRADE_SUB, AUTO_UPGRADE_TIP, autoUpgradeLine, autoUpgradeOn,
  shownAutoUpgrade } from './autoUpgrade';

describe('the Auto-upgrade switch', () => {
  it('reads as on unless the status says false', () => {
    expect(autoUpgradeOn(true)).toBe(true);
    expect(autoUpgradeOn(false)).toBe(false);
    expect(autoUpgradeOn(undefined)).toBe(true);
    expect(autoUpgradeOn(null)).toBe(true);
  });
  it('shows the value being saved until the job ends', () => {
    expect(shownAutoUpgrade(true, null)).toBe(true);
    expect(shownAutoUpgrade(true, false)).toBe(false);
    expect(shownAutoUpgrade(false, true)).toBe(true);
  });
  it('keeps the words of plan §3 and design §8, rekordbox lowercase', () => {
    expect(AUTO_UPGRADE_LABEL).toBe('Upgrade automatically when I sync');
    expect(autoUpgradeLine(true)).toBe('Automatic at the end of each sync');
    expect(autoUpgradeLine(false)).toBe('Off: upgrades wait for you in To-do');
    for (const w of [AUTO_UPGRADE_SUB, AUTO_UPGRADE_SETUP_SUB, AUTO_UPGRADE_TIP]) expect(w).not.toMatch(/Rekordbox/);
    expect(AUTO_UPGRADE_SETUP_SUB).toContain('Superseded/');
  });
});
