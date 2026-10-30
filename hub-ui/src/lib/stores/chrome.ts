// The shell's chrome (plan library stage 5, I6 and D17; notes N1, N7, N8): the sidebar's two forms, full (168 px) and
// rail (50 px), remembered for two places (Library, rail by default; every other page, full by default), the browser
// column beside it in Library (200–360 px, 240 by default), and the step-back: below 1240 px an open inspector puts
// the browser behind the rail. The shell derives `--sidebar-w` from it (the form, plus 1 + the browser's width while
// it stands) and sets it on the app root, so the page's edge, the foot's line and the rule checker read one value.
// The layout and the move between two layouts are pure (`chromeLayout`, `chromeMove`); the stores keep the prefs.
// It also keeps when Library's details show (`detailsAfter`): picking a track opens them, unless the user hid them by
// hand, which sticks (also across restarts) until they open them again by hand.
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
  /** Library has an inspector to show (not while its library is empty: no toggle, no details) */
  inspectorAvailable: boolean;
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
  const steppedBack = i.place === 'library' && i.inspectorOpen && i.inspectorAvailable && i.windowWidth < NARROW_BELOW;
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
/** Library's details inspector is open (picking a track opens it, ⌘I and the toggle turn it over); it starts closed */
export const inspectorOpen = persisted<boolean>('library.inspector', false);
/** The user hid the details by hand (the toggle or ⌘I while they showed): picking a track no longer opens them, and
 *  the toggle says so, until the user opens them by hand again. Remembered, like the other layout choices. */
export const detailsHidden = persisted<boolean>('library.details.hidden', false);
/** Library sets it false while it has nothing to show details of (an empty library: the toggle is hidden), so ⌘I does
 *  nothing and a remembered open inspector neither shows nor steps the browser back; true again when the page goes. */
export const inspectorAvailable = writable(true);

const hasWindow = () => typeof window !== 'undefined';
export const windowWidth: Readable<number> = readable(hasWindow() ? window.innerWidth : 1280, (set) => {
  if (!hasWindow()) return;
  const fn = () => set(window.innerWidth);
  fn();
  window.addEventListener('resize', fn);
  return () => window.removeEventListener('resize', fn);
});

/** Whether Library's details show: open, and not hidden by hand (two stored values that a hand edit or an older
 *  version could leave both true; hidden wins). */
export const detailsShown: Readable<boolean> = derived([inspectorOpen, detailsHidden], ([o, h]) => o && !h);

export const chrome: Readable<ChromeLayout> = derived(
  [route, formLibrary, formOther, browserWidth, detailsShown, windowWidth, inspectorAvailable],
  ([r, fl, fo, bw, insp, ww, avail]) => chromeLayout({ place: placeOf(r.name), formLibrary: fl, formOther: fo,
    browserWidth: bw, inspectorOpen: insp, windowWidth: ww, inspectorAvailable: avail }));

let glideNext = false;
/** The layout with the move that led to it (Sidebar picks its transitions by it). A new subscriber (the chrome
 *  shown again after Setup) starts with `none`: nothing glides into a first look. */
export const chromeMotion: Readable<{ layout: ChromeLayout; move: ChromeMove }> = readable(
  { layout: get(chrome), move: 'none' as ChromeMove }, (set) => {
    let prev: ChromeLayout | null = null;
    return chrome.subscribe((l) => {
      // a route change or a resize that leaves the chrome as it is says nothing: a `none` mid-glide would cut the
      // glide and its fades short
      if (prev && sameLayout(prev, l)) return;
      const move = chromeMove(prev, l, glideNext);
      prev = l;
      glideNext = false;
      set({ layout: l, move });
    });
  });

export function sameLayout(a: ChromeLayout, b: ChromeLayout): boolean {
  return a.place === b.place && a.form === b.form && a.browserShown === b.browserShown
    && a.steppedBack === b.steppedBack && a.browserWidth === b.browserWidth && a.sidebarW === b.sidebarW;
}

/** ⌃⌘S and the fold button: the current place's form turns over (the other place keeps its own). */
export function fold(): void {
  const store = get(chrome).place === 'library' ? formLibrary : formOther;
  // from the form the layout shows: a corrupt stored value shows the default, and the first press must turn that over
  const next: Form = get(chrome).form === 'rail' ? 'full' : 'rail';
  store.set(next);
}

/** The column's edge: dragged (1:1, at once) or double-clicked back to 240 (`glide`). */
export function setBrowserWidth(w: number, glide = false): void {
  const next = clampBrowserWidth(w);
  if (next === get(browserWidth)) return;
  glideNext = glide;
  browserWidth.set(next);
}

/** The column's edge from the keyboard (it is a focusable separator): ← → by 10 px (⇧ 40), Home / End to the
 *  narrowest and widest. Null: not a key the edge takes. */
export function edgeKeyWidth(key: string, w: number, shift = false): number | null {
  const step = shift ? 40 : 10;
  if (key === 'ArrowLeft') return clampBrowserWidth(w - step);
  if (key === 'ArrowRight') return clampBrowserWidth(w + step);
  if (key === 'Home') return BROWSER_MIN;
  if (key === 'End') return BROWSER_MAX;
  return null;
}

/** The edge's cursor: both ways, or the one way left at a limit (macOS's resize cursors). */
export function edgeCursor(w: number): 'col-resize' | 'e-resize' | 'w-resize' {
  return w <= BROWSER_MIN ? 'e-resize' : w >= BROWSER_MAX ? 'w-resize' : 'col-resize';
}

/**
 * When Library's details show (the user's wish after the step A live check): `pick` (a click on a track or ↑ ↓) opens
 * them, unless the user hid them by hand; `toggle` (the details toggle, ⌘I) hides them by hand while they show and
 * opens them otherwise, which ends a hide by hand; `show` (a quality badge, the menu's Show details) opens them by
 * hand; `yield` (⌘K or ♫ below 1240 px: the browser column wants the room) closes them without counting as a hide by
 * hand, so the next pick opens them again. Arriving with a track in the route is no pick: ♫ and ⌘K go back to
 * Library and must not undo the yield that brought the browser back.
 */
export type DetailsState = { open: boolean; hidden: boolean };
export type DetailsAct = 'pick' | 'toggle' | 'show' | 'yield';
export function detailsAfter(s: DetailsState, act: DetailsAct): DetailsState {
  const shown = s.open && !s.hidden;
  if (act === 'pick') return s.hidden ? { open: false, hidden: true } : { open: true, hidden: false };
  if (act === 'toggle') return shown ? { open: false, hidden: true } : { open: true, hidden: false };
  if (act === 'show') return { open: true, hidden: false };
  return { open: false, hidden: s.hidden };
}
function actOnDetails(act: DetailsAct): void {
  const next = detailsAfter({ open: get(inspectorOpen), hidden: get(detailsHidden) }, act);
  inspectorOpen.set(next.open);
  detailsHidden.set(next.hidden);
}
/** A track picked in Library's table (a click, ↑ ↓): the details open, unless hidden by hand. */
export function pickTrack(): void {
  actOnDetails('pick');
}
/** A quality badge or the menu's Show details: open by hand. */
export function showDetails(): void {
  actOnDetails('show');
}

/** Whether ⌘I turns the inspector over: only in Library, and only while it has one to show. */
export function inspectorToggles(place: Place, available: boolean): boolean {
  return place === 'library' && available;
}
/** ⌘I and the details toggle: only Library has the inspector. */
export function toggleInspector(): void {
  if (inspectorToggles(get(chrome).place, get(inspectorAvailable))) actOnDetails('toggle');
}

/** ⌘K from any page, or ♫ on Library: below 1240 px the inspector closes, so the browser stands (again) when Library
 *  shows (no hide by hand: the next pick opens the details again). At 1240 and up both fit and nothing changes.
 *  `width`: the window's (the live one by default). */
export function bringBrowserBack(width: number = get(windowWidth)): void {
  if (width < NARROW_BELOW && get(inspectorOpen)) actOnDetails('yield');
}

/** A request for the browser's filter field to take focus (⌘K); the column answers each new number. */
export const filterFocus = writable(0);
export function requestFilterFocus(): void {
  filterFocus.update((n) => n + 1);
}

/** Where ♫, ⌘6 and ⌘K go back to: the collection last open in Library, with its selected track. */
export function libraryReturn(r: Route): string | null {
  if (r.name !== 'library') return null;
  const q = r.query.toString();
  return `#${r.path}${q ? `?${q}` : ''}`;
}
export const lastLibrary = writable('#/library');
