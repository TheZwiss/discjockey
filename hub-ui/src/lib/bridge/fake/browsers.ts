// Fake mode only: the browsers on the fake Mac (accounts.BROWSERS' names).
import type { Browser, LoginBrowser } from '../types';

export const BROWSER_NAMES: Record<Browser, string> = { safari: 'Safari', chrome: 'Chrome', firefox: 'Firefox',
  brave: 'Brave', edge: 'Microsoft Edge' };

/** The fake Mac's browsers when a scenario names none: Chrome (the default, no login) and Safari (no Full Disk Access). */
export function defaultBrowsers(): LoginBrowser[] {
  return [
    { id: 'chrome', name: 'Chrome', default: true, readable: true, problem: null,
      profiles: [{ id: 'Default', name: 'Person 1', signed_in: false }, { id: 'Profile 2', name: 'Work', signed_in: false }] },
    { id: 'safari', name: 'Safari', default: false, readable: false, problem: 'no_access', profiles: [{ id: null, name: 'Safari', signed_in: false }] },
  ];
}
