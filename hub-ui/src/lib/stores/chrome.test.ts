import { describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { parseHash } from '../router';
import {
  BROWSER_DEFAULT, BROWSER_MAX, BROWSER_MIN, bringBrowserBack, chrome, chromeLayout, chromeMotion, chromeMove,
  clampBrowserWidth, detailsAfter, detailsHidden, detailsShown, detailsStand, detailsSubject, detailsWanted, edgeCursor,
  edgeKeyWidth, filterFocus, fold, formOther, hasDetailsSubject, inspectorOpen, inspectorToggles, libraryTrack, pickTrack,
  showDetails, trackOffTable, type DetailsState, libraryReturn, placeOf, requestFilterFocus, setBrowserWidth,
  toggleInspector, type ChromeInput,
} from './chrome';

const input = (o: Partial<ChromeInput> = {}): ChromeInput => ({ place: 'library', formLibrary: 'rail', formOther: 'full',
  browserWidth: 240, details: false, windowWidth: 1280, ...o });

describe('chromeLayout', () => {
  it('Library: the rail and the browser at 240 make the chrome 50 + 1 + 240', () => {
    expect(chromeLayout(input())).toEqual({ place: 'library', form: 'rail', browserShown: true, steppedBack: false,
      browserWidth: 240, sidebarW: 291 });
  });
  it('another page: the full sidebar alone, 168', () => {
    const l = chromeLayout(input({ place: 'other' }));
    expect([l.form, l.browserShown, l.sidebarW]).toEqual(['full', false, 168]);
  });
  it('each place keeps its own form: folded by hand outside Library, unfolded in Library', () => {
    expect(chromeLayout(input({ place: 'other', formOther: 'rail' })).sidebarW).toBe(50);
    expect(chromeLayout(input({ formLibrary: 'full' })).sidebarW).toBe(168 + 1 + 240);
  });
  it('a stored form that is neither falls back to the place\'s default', () => {
    expect(chromeLayout(input({ formLibrary: 'x' as never })).form).toBe('rail');
    expect(chromeLayout(input({ place: 'other', formOther: 'x' as never })).form).toBe('full');
  });
  it('the width is clamped to 200–360 and whole', () => {
    expect(chromeLayout(input({ browserWidth: 120 })).sidebarW).toBe(50 + 1 + 200);
    expect(chromeLayout(input({ browserWidth: 999 })).sidebarW).toBe(50 + 1 + 360);
    expect(clampBrowserWidth(301.6)).toBe(302);
    expect(clampBrowserWidth(Number.NaN)).toBe(BROWSER_DEFAULT);
    expect(clampBrowserWidth('300')).toBe(BROWSER_DEFAULT);
  });
  it('below 1240 standing details step the browser back behind the rail; at 1240 and up both stand', () => {
    const narrow = chromeLayout(input({ details: true, windowWidth: 1100 }));
    expect([narrow.steppedBack, narrow.browserShown, narrow.sidebarW]).toEqual([true, false, 50]);
    const wide = chromeLayout(input({ details: true, windowWidth: 1240 }));
    expect([wide.steppedBack, wide.browserShown, wide.sidebarW]).toEqual([false, true, 291]);
    expect(chromeLayout(input({ details: false, windowWidth: 1100 })).browserShown).toBe(true);
  });
  it('details wanted but with nothing to show step nothing back (the first open with a remembered open inspector)', () => {
    const details = detailsStand({ open: true, hidden: false }, null, false);
    const l = chromeLayout(input({ details, windowWidth: 1100 }));
    expect([l.steppedBack, l.browserShown, l.sidebarW]).toEqual([false, true, 291]);
  });
  it('the inspector pref never steps anything back outside Library', () => {
    const l = chromeLayout(input({ place: 'other', details: true, windowWidth: 1100 }));
    expect([l.steppedBack, l.browserShown]).toEqual([false, false]);
  });
});

describe('chromeMove', () => {
  const lib = chromeLayout(input());
  const other = chromeLayout(input({ place: 'other' }));
  it('nothing moves on the first layout or between two other pages', () => {
    expect(chromeMove(null, lib)).toBe('none');
    expect(chromeMove(other, chromeLayout(input({ place: 'other' })))).toBe('none');
  });
  it('into and out of Library', () => {
    expect(chromeMove(other, lib)).toBe('into');
    expect(chromeMove(lib, other)).toBe('out');
  });
  it('folding in either place', () => {
    expect(chromeMove(other, chromeLayout(input({ place: 'other', formOther: 'rail' })))).toBe('fold');
    expect(chromeMove(lib, chromeLayout(input({ formLibrary: 'full' })))).toBe('fold');
  });
  it('the step-back and its return', () => {
    const back = chromeLayout(input({ details: true, windowWidth: 1100 }));
    expect(chromeMove(lib, back)).toBe('step-back');
    expect(chromeMove(back, chromeLayout(input({ windowWidth: 1100 })))).toBe('step-in');
  });
  it('a dragged width changes at once; the double-click back to 240 glides', () => {
    const wide = chromeLayout(input({ browserWidth: 320 }));
    expect(chromeMove(wide, lib)).toBe('none');
    expect(chromeMove(wide, lib, true)).toBe('reset');
  });
});

describe('the stores', () => {
  it('fold turns over the current place\'s form only (the tests run on Dashboard)', () => {
    expect(get(chrome).place).toBe('other');
    expect(get(chrome).sidebarW).toBe(168);
    fold();
    expect(get(formOther)).toBe('rail');
    expect(get(chrome).sidebarW).toBe(50);
    fold();
    expect(get(chrome).form).toBe('full');
  });
  it('a corrupt stored form shows the default, and the first fold turns that over', () => {
    formOther.set('foo' as never);
    expect(get(chrome).form).toBe('full');
    fold();
    expect(get(chrome).form).toBe('rail');
    formOther.set('full');
  });
  it('chromeMotion names the move that led to each layout, starting with none', () => {
    const seen: string[] = [];
    const stop = chromeMotion.subscribe((m) => seen.push(m.move));
    fold();
    fold();
    stop();
    expect(seen).toEqual(['none', 'fold', 'fold']);
  });
  it('a width set with glide moves as a reset, once', () => {
    const seen: string[] = [];
    const stop = chromeMotion.subscribe((m) => seen.push(m.move));
    setBrowserWidth(320);
    setBrowserWidth(240, true);
    setBrowserWidth(500);
    stop();
    expect(seen).toEqual(['none', 'none', 'reset', 'none']);
    setBrowserWidth(240);
  });
  it('⌘K below 1240 closes the inspector from any page, so the browser stands when Library shows', () => {
    inspectorOpen.set(true);
    bringBrowserBack(1100);
    expect(get(inspectorOpen)).toBe(false);
  });
  it('at 1240 and up both fit: ⌘K leaves the inspector open', () => {
    inspectorOpen.set(true);
    bringBrowserBack(1240);
    expect(get(inspectorOpen)).toBe(true);
    bringBrowserBack();   // the tests' window: 1280
    expect(get(inspectorOpen)).toBe(true);
    inspectorOpen.set(false);
  });
  it('chromeMotion stays quiet while the layout stays: no `none` cuts a glide short', () => {
    const seen: string[] = [];
    const stop = chromeMotion.subscribe((m) => seen.push(m.move));
    fold();
    inspectorOpen.set(true);    // outside Library: the layout is the same
    inspectorOpen.set(false);
    fold();
    stop();
    expect(seen).toEqual(['none', 'fold', 'fold']);
  });
  it('⌘I does nothing outside Library', () => {
    toggleInspector();
    expect(get(inspectorOpen)).toBe(false);
  });
  it('⌘I turns the inspector over only in Library with something to show', () => {
    expect(inspectorToggles('library', true)).toBe(true);
    expect(inspectorToggles('library', false)).toBe(false);
    expect(inspectorToggles('other', true)).toBe(false);
  });
  it('each filter request is a new number for the column to answer', () => {
    const n = get(filterFocus);
    requestFilterFocus();
    expect(get(filterFocus)).toBe(n + 1);
  });
});

describe('when Library\'s details show (detailsAfter)', () => {
  const closed: DetailsState = { open: false, hidden: false };
  const shown: DetailsState = { open: true, hidden: false };
  const hidden: DetailsState = { open: false, hidden: true };
  it('picking a track opens them', () => {
    expect(detailsAfter(closed, 'pick')).toEqual(shown);
    expect(detailsAfter(shown, 'pick')).toEqual(shown);
  });
  it('the toggle (or ⌘I) while they show hides them by hand, and further picks only select', () => {
    const h = detailsAfter(shown, 'toggle');
    expect(h).toEqual(hidden);
    expect(detailsAfter(detailsAfter(h, 'pick'), 'pick')).toEqual(hidden);
  });
  it('opening them by hand ends the hide: the toggle, a quality badge or the menu', () => {
    expect(detailsAfter(hidden, 'toggle')).toEqual(shown);
    expect(detailsAfter(hidden, 'show')).toEqual(shown);
    // and then picks open them again after a later close by the browser
    expect(detailsAfter(detailsAfter(detailsAfter(hidden, 'show'), 'yield'), 'pick')).toEqual(shown);
  });
  it('the toggle opens details that are only closed (never shown yet, or closed for the browser)', () => {
    expect(detailsAfter(closed, 'toggle')).toEqual(shown);
  });
  it('making room for the browser (⌘K, ♫ below 1240) closes them without a hide by hand', () => {
    expect(detailsAfter(shown, 'yield')).toEqual(closed);
    expect(detailsAfter(hidden, 'yield')).toEqual(hidden);
  });
  it('two stored values both true (hand edit, older version): hidden wins and the next act straightens them', () => {
    const both: DetailsState = { open: true, hidden: true };
    expect(detailsAfter(both, 'pick')).toEqual(hidden);
    expect(detailsAfter(both, 'toggle')).toEqual(shown);
  });
});

describe('the details stores', () => {
  const reset = () => { inspectorOpen.set(false); detailsHidden.set(false); };
  it('a pick opens them and the chrome steps the browser back at 1100', () => {
    reset();
    pickTrack();
    expect(get(detailsWanted)).toBe(true);
    expect(chromeLayout(input({ details: detailsStand({ open: true, hidden: false }, 't2', false), windowWidth: 1100 }))
      .steppedBack).toBe(true);
    reset();
  });
  it('hidden by hand: a pick keeps them closed; a badge opens them and ends the hide', () => {
    reset();
    detailsHidden.set(true);
    pickTrack();
    expect([get(inspectorOpen), get(detailsWanted), get(detailsHidden)]).toEqual([false, false, true]);
    showDetails();
    expect([get(detailsWanted), get(detailsHidden)]).toEqual([true, false]);
    reset();
  });
  it('⌘K below 1240 closes them but the next pick opens them again', () => {
    reset();
    pickTrack();
    bringBrowserBack(1100);
    expect([get(detailsWanted), get(detailsHidden)]).toEqual([false, false]);
    pickTrack();
    expect(get(detailsWanted)).toBe(true);
    reset();
  });
  it('hidden wins over a stored open', () => {
    inspectorOpen.set(true);
    detailsHidden.set(true);
    expect(get(detailsWanted)).toBe(false);
    reset();
  });
  it('outside Library (the tests\' route) nothing stands and ⌘I does nothing, whatever is wanted', () => {
    reset();
    pickTrack();
    expect([get(detailsWanted), get(detailsShown), get(detailsSubject)]).toEqual([true, false, false]);
    reset();
  });
  it('the page\'s word that the track is off the table reaches the subject; it starts unknown (false)', () => {
    expect(get(trackOffTable)).toBe(false);
    trackOffTable.set(true);
    expect(get(detailsSubject)).toBe(false);
    trackOffTable.set(false);
  });
});

describe('the details never stand empty (detailsStand)', () => {
  const wanted: DetailsState = { open: true, hidden: false };
  it('they stand only with a selected track on the table', () => {
    expect(detailsStand(wanted, 't2', false)).toBe(true);
    expect(detailsStand(wanted, null, false)).toBe(false);   // nothing selected: a first open, a new playlist
    expect(detailsStand(wanted, 't2', true)).toBe(false);    // filtered or searched away, gone, an empty folder
  });
  it('old saved prefs (open, from before or from the last session) show nothing on a first open of Library', () => {
    // a first open: the route has no track
    const first = libraryTrack(parseHash('#/library'));
    expect(first).toBeNull();
    expect(detailsStand({ open: true, hidden: false }, first, false)).toBe(false);
    expect(detailsStand({ open: true, hidden: true }, first, false)).toBe(false);
    expect(hasDetailsSubject(first, false)).toBe(false);
    // coming back to Library with its last track: they stand again
    expect(detailsStand({ open: true, hidden: false }, libraryTrack(parseHash('#/library/folder/Hard_Bounce?track=t2')), false))
      .toBe(true);
  });
  it('not wanted (closed, or hidden by hand): never, whatever the selection', () => {
    expect(detailsStand({ open: false, hidden: false }, 't2', false)).toBe(false);
    expect(detailsStand({ open: false, hidden: true }, 't2', false)).toBe(false);
    expect(detailsStand({ open: true, hidden: true }, 't2', false)).toBe(false);
  });
  it('the selected track is the route\'s, and only in Library', () => {
    expect(libraryTrack(parseHash('#/library/not-in-playlist?track=local%3A1'))).toBe('local:1');
    expect(libraryTrack(parseHash('#/todo?track=t2'))).toBeNull();
  });
  it('the toggle and ⌘I need a subject', () => {
    expect(hasDetailsSubject('t2', false)).toBe(true);
    expect(hasDetailsSubject('t2', true)).toBe(false);
    expect(inspectorToggles('library', hasDetailsSubject(null, false))).toBe(false);
  });
});

describe('places', () => {
  it('Library is its own place; every other route shares one', () => {
    expect(placeOf('library')).toBe('library');
    expect(['dashboard', 'runs', 'sync', 'settings', 'gallery'].map(placeOf)).toEqual(Array(5).fill('other'));
  });
  it('libraryReturn keeps the collection and its selected track', () => {
    expect(libraryReturn(parseHash('#/library/folder/Hard%20Bounce?track=t2'))).toBe('#/library/folder/Hard%20Bounce?track=t2');
    expect(libraryReturn(parseHash('#/library'))).toBe('#/library');
    expect(libraryReturn(parseHash('#/todo'))).toBeNull();
  });
});

describe('the column edge from the keyboard and its cursor', () => {
  it('steps by 10 (⇧ 40) within 200–360, Home and End to the ends', () => {
    expect(edgeKeyWidth('ArrowRight', 240)).toBe(250);
    expect(edgeKeyWidth('ArrowLeft', 240, true)).toBe(200);
    expect(edgeKeyWidth('ArrowLeft', 205)).toBe(BROWSER_MIN);
    expect(edgeKeyWidth('ArrowRight', 355, true)).toBe(BROWSER_MAX);
    expect(edgeKeyWidth('Home', 300)).toBe(BROWSER_MIN);
    expect(edgeKeyWidth('End', 300)).toBe(BROWSER_MAX);
    expect(edgeKeyWidth('Enter', 300)).toBeNull();
  });
  it('shows the one way left at a limit', () => {
    expect(edgeCursor(200)).toBe('e-resize');
    expect(edgeCursor(360)).toBe('w-resize');
    expect(edgeCursor(240)).toBe('col-resize');
  });
});
