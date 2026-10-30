// The shell's chrome (plan library stage 5, I6 and D17; notes N1, N7, N8): the sidebar's two forms, full (168 px) and
// rail (50 px), remembered for two places (Library, rail by default; every other page, full by default), the browser
// column beside it in Library (200–360 px, 240 by default), and the step-back: below 1240 px an open inspector puts
// the browser behind the rail. The shell derives `--sidebar-w` from it (the form, plus 1 + the browser's width while
// it stands) and sets it on the app root, so the page's edge, the foot's line and the rule checker read one value.
// The layout and the move between two layouts are pure (`chromeLayout`, `chromeMove`); the stores keep the prefs.
import { derived, get, readable, writable, type Readable } from 'svelte/store';
import { persisted } from '../prefs';
import { route, type Route } from '../router';

export type Form = 'full' | 'rail';
export type Place = 'library' | 'other';

export const FULL_W = 168;
export const RAIL_W = 50;
export const BROWSER_MIN = 200;
export const BROWSER_DEFAULT = 240;
export const BROWSER_MAX = 360;
/** `--panel-narrow-below`: below this window width the browser and the inspector take turns (N7). */
export const NARROW_BELOW = 1240;

export const placeOf = (routeName: string): Place => (routeName === 'library' ? 'library' : 'other');

/** A stored or dragged width, whole pixels within 200–360; anything that isn't a number is the default. */
export function clampBrowserWidth(w: unknown): number {
  if (typeof w !== 'number' || !Number.isFinite(w)) return BROWSER_DEFAULT;
  return Math.round(Math.min(BROWSER_MAX, Math.max(BROWSER_MIN, w)));
}

export type ChromeInput = {
  place: Place; formLibrary: Form; formOther: Form; browserWidth: number; inspectorOpen: boolean; windowWidth: number;
};
export type ChromeLayout = {
  place: Place; form: Form;
  /** the browser column stands beside the sidebar: Library, unless stepped back */
  browserShown: boolean;
  /** Library below 1240 px with the inspector open: the browser waits behind the rail (⌘K or ♫ bring it back) */
  steppedBack: boolean;
  browserWidth: number;
  /** the chrome's whole width in px, the value of `--sidebar-w` */
  sidebarW: number;
};

export function chromeLayout(i: ChromeInput): ChromeLayout {
  // a stored value that isn't one of the two forms falls back to the place's default
  const form: Form = i.place === 'library' ? (i.formLibrary === 'full' ? 'full' : 'rail')
    : (i.formOther === 'rail' ? 'rail' : 'full');
  const steppedBack = i.place === 'library' && i.inspectorOpen && i.windowWidth < NARROW_BELOW;
  const browserShown = i.place === 'library' && !steppedBack;
  const browserWidth = clampBrowserWidth(i.browserWidth);
  const sidebarW = (form === 'rail' ? RAIL_W : FULL_W) + (browserShown ? 1 + browserWidth : 0);
  return { place: i.place, form, browserShown, steppedBack, browserWidth, sidebarW };
}

/**
 * How the chrome moves from one layout to the next (the notes' motion table): `fold` (⌃⌘S, 220 ms), `into` / `out`
 * of Library (220 ms in; out quicker, the browser's rows first), `step-back` / `step-in` (the browser behind the rail
 * and back, 200 / 240 ms), `reset` (a double-click on the column's edge, 220 ms). `none`: at once (the first layout,
 * a page switch between two other pages, and the column dragged 1:1).
 */
export type ChromeMove = 'none' | 'fold' | 'into' | 'out' | 'step-back' | 'step-in' | 'reset';
export function chromeMove(prev: ChromeLayout | null, next: ChromeLayout, widthGlide = false): ChromeMove {
  if (!prev) return 'none';
  if (prev.place !== next.place) return next.place === 'library' ? 'into' : 'out';
  if (prev.browserShown !== next.browserShown) return next.browserShown ? 'step-in' : 'step-back';
  if (prev.form !== next.form) return 'fold';
  if (prev.browserWidth !== next.browserWidth && widthGlide) return 'reset';
  return 'none';
}

// ---------- the stores (UI prefs in localStorage, D17) ----------
export const formLibrary = persisted<Form>('shell.form.library', 'rail');
export const formOther = persisted<Form>('shell.form.other', 'full');
export const browserWidth = persisted<number>('shell.browser.width', BROWSER_DEFAULT);
/** the browser's folded sections and watched folders (their keys; A5) */
export const browserClosed = persisted<string[]>('shell.browser.closed', []);
/** Playlists in A–Z order instead of download priority (A5) */
export const playlistsAz = persisted<boolean>('shell.playlists.az', false);
/** Library's details inspector is open (the page sets it, ⌘I toggles it); it starts closed */
export const inspectorOpen = persisted<boolean>('library.inspector', false);

const hasWindow = () => typeof window !== 'undefined';
export const windowWidth: Readable<number> = readable(hasWindow() ? window.innerWidth : 1280, (set) => {
  if (!hasWindow()) return;
  const fn = () => set(window.innerWidth);
  fn();
  window.addEventListener('resize', fn);
  return () => window.removeEventListener('resize', fn);
});

export const chrome: Readable<ChromeLayout> = derived(
  [route, formLibrary, formOther, browserWidth, inspectorOpen, windowWidth],
  ([r, fl, fo, bw, insp, ww]) => chromeLayout({ place: placeOf(r.name), formLibrary: fl, formOther: fo,
    browserWidth: bw, inspectorOpen: insp, windowWidth: ww }));

let glideNext = false;
/** The layout with the move that led to it (Sidebar picks its transitions by it). A new subscriber (the chrome
 *  shown again after Setup) starts with `none`: nothing glides into a first look. */
export const chromeMotion: Readable<{ layout: ChromeLayout; move: ChromeMove }> = readable(
  { layout: get(chrome), move: 'none' as ChromeMove }, (set) => {
    let prev: ChromeLayout | null = null;
    return chrome.subscribe((l) => {
      const move = chromeMove(prev, l, glideNext);
      prev = l;
      glideNext = false;
      set({ layout: l, move });
    });
  });

/** ⌃⌘S and the fold button: the current place's form turns over (the other place keeps its own). */
export function fold(): void {
  const store = get(chrome).place === 'library' ? formLibrary : formOther;
  store.update((f) => (f === 'rail' ? 'full' : 'rail'));
}

/** The column's edge: dragged (1:1, at once) or double-clicked back to 240 (`glide`). */
export function setBrowserWidth(w: number, glide = false): void {
  const next = clampBrowserWidth(w);
  if (next === get(browserWidth)) return;
  glideNext = glide;
  browserWidth.set(next);
}

/** ⌘I: only Library has the inspector. */
export function toggleInspector(): void {
  if (get(chrome).place === 'library') inspectorOpen.update((o) => !o);
}

/** ⌘K, or ♫ while the browser waits behind the rail: below 1240 px the inspector closes so the browser comes back. */
export function bringBrowserBack(): void {
  if (get(chrome).steppedBack) inspectorOpen.set(false);
}

/** A request for the browser's filter field to take focus (⌘K); the column answers each new number. */
export const filterFocus = writable(0);
export function requestFilterFocus(): void {
  filterFocus.update((n) => n + 1);
}

/** Library's own place, without the selected track: where ♫ and ⌘6 go back to (the collection last open). */
export function libraryReturn(r: Route): string | null {
  return r.name === 'library' ? `#${r.path}` : null;
}
export const lastLibrary = writable('#/library');
