// Runs in the page. Returns the design-system rule violations of what is on screen (spec §9).
(() => {
  const SKIP = '[data-dev], [data-dev] *';
  const DIALOG = 'dialog[open], [role=dialog]';   // the app's Dialog is a native <dialog> without a role
  const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const where = (el) => el.closest('[data-test]')?.getAttribute('data-test') ?? el.tagName.toLowerCase();
  const scrolls = (el) => { for (let p = el.parentElement; p; p = p.parentElement) {
    const s = getComputedStyle(p); if (/(auto|scroll)/.test(s.overflowY) && p.scrollHeight > p.clientHeight) return true; }
    return false; };
  function tokenColours() {
    const root = getComputedStyle(document.documentElement); const probe = document.createElement('i');
    document.body.append(probe); const out = new Set(['rgba(0, 0, 0, 0)']);
    for (const name of Array.from(document.styleSheets).flatMap((sh) => { try { return Array.from(sh.cssRules); } catch { return []; } })
      .filter((r) => r.selectorText === ':root').flatMap((r) => Array.from(r.style)).filter((n) => n.startsWith('--'))) {
      probe.style.color = ''; probe.style.color = `var(${name})`; const c = getComputedStyle(probe).color;
      if (c && root.getPropertyValue(name).trim()) out.add(c);
    }
    probe.remove(); return out;
  }
  window.__rules = () => {
    const v = []; const add = (rule, el, detail) => v.push({ rule, where: where(el), detail });
    const all = Array.from(document.querySelectorAll('body *')).filter((el) => !el.matches(SKIP) && visible(el));
    // 1 overflow
    const de = document.scrollingElement;
    if (de.scrollWidth > de.clientWidth + 1) add('overflow', de, `page ${de.scrollWidth} > ${de.clientWidth}`);
    for (const el of all) { const s = getComputedStyle(el);
      if (/(auto|scroll)/.test(s.overflowX) && el.scrollWidth > el.clientWidth + 1) add('overflow', el, `${el.scrollWidth} > ${el.clientWidth}`); }
    // 2 max widths: a frame's `data-max` names the token its content grows to (one source: tokens.css); the panel's
    // width follows the window, --panel-w, or --panel-w-narrow below --panel-narrow-below (final review I5)
    const rootCss = getComputedStyle(document.documentElement);
    const token = (name) => parseFloat(rootCss.getPropertyValue(name));
    for (const el of document.querySelectorAll('[data-frame-content][data-max]')) {
      const w = el.getBoundingClientRect().width, name = el.dataset.max, max = token(name);
      if (!name.startsWith('--') || Number.isNaN(max)) { add('max-width', el, `data-max "${name}" is not a size token`); continue; }
      if (w > max + 1) add('max-width', el, `${Math.round(w)} > ${max} (${name})`); }
    const narrowBelow = token('--panel-narrow-below');
    const panelName = innerWidth < narrowBelow ? '--panel-w-narrow' : '--panel-w', panelMax = token(panelName);
    for (const el of document.querySelectorAll('[data-panel]')) {
      const w = el.getBoundingClientRect().width;
      if (Number.isNaN(panelMax) || Number.isNaN(narrowBelow)) add('max-width', el, `no ${panelName} or --panel-narrow-below token`);
      else if (w > panelMax + 1) add('max-width', el, `panel ${Math.round(w)} > ${panelMax} (${panelName} at a ${innerWidth} px window)`); }
    // 2b one frame: a redesigned page draws in exactly one frame, with at most one page header. A page without a frame
    // has no [data-frame-content] to measure, so the width rules above would pass it unseen (final review I5)
    // a frame counts unless display:none (its size can be 0 while its content is positioned)
    const frames = Array.from(document.querySelectorAll('[data-frame]')).filter((f) => !f.matches(SKIP) && getComputedStyle(f).display !== 'none');
    if (frames.length !== 1) add('frame', document.body, `${frames.length} frames, want 1`);
    const headers = Array.from(document.querySelectorAll('[data-page-header]')).filter((h) => !h.matches(SKIP) && visible(h));
    if (headers.length > 1) add('frame', document.body, `${headers.length} page headers`);
    // 3 buttons and the one primary
    for (const el of all.filter((e) => e.matches('button, a[role=button], .btn'))) {
      if (el.closest('[data-panel-foot]') && el.matches('[data-stretch]')) continue;
      // a row's or a segment's own hit area fills by design: segments, switch rows, menu items, and the hit areas that
      // ListRow (`.main`) and Surface (the fold) mark `data-row-hit`, StepStrip's equal steps `data-step-hit`. Any other
      // button keeps its natural width, also one in a list's head or a row's trailing cell (final review I5: the whole
      // list surface was exempt)
      if (el.matches('[role=radio], [role=switch], [role=menuitem], [data-row-hit], [data-step-hit]')) continue;
      const w = el.getBoundingClientRect().width;
      const keep = el.getAttribute('style');   // measure the natural size: no stretching by width, flex-grow or align
      el.style.width = 'max-content'; el.style.flex = '0 0 auto'; el.style.alignSelf = 'flex-start';
      const natural = Math.max(el.getBoundingClientRect().width, parseFloat(getComputedStyle(el).minWidth) || 0);
      if (keep === null) el.removeAttribute('style'); else el.setAttribute('style', keep);
      if (w > natural + 2) add('button', el, `${Math.round(w)} wide, natural ${Math.round(natural)}`); }
    const layers = [document, ...document.querySelectorAll(DIALOG)];
    for (const layer of layers) { const n = Array.from(layer.querySelectorAll('[data-primary]'))
      .filter((b) => visible(b) && (layer === document ? !b.closest(DIALOG) : true)).length;
      if (n > 1) add('primary', layer === document ? document.body : layer, `${n} filled buttons`); }
    // 4 clipped at the minimum size
    if (innerWidth <= 1100 && innerHeight <= 700) {
      for (const el of all.filter((e) => e.matches('button, a, input, [role=checkbox], [role=switch]'))) {
        const r = el.getBoundingClientRect();
        if ((r.bottom > innerHeight || r.right > innerWidth) && !scrolls(el)) add('clipped', el, 'outside the window'); }
      for (const f of document.querySelectorAll('[data-panel-foot]')) { const r = f.getBoundingClientRect();
        if (r.bottom > innerHeight + 1 || r.top < 0) add('clipped', f, 'panel foot not fully visible'); } }
    // 5 loose text
    const SHELTER = '[data-surface], [data-note], [data-infotip], ' + DIALOG;
    const looseText = (el) => Array.from(el.childNodes).map((n) => n.nodeType === 3 ? n.textContent
      : n.nodeType === 1 && !n.matches(SHELTER) ? looseText(n) : '').join('');
    for (const el of all) {
      if (el.closest(SHELTER)) continue;
      if (!Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim())) continue;
      const text = looseText(el).replace(/\s+/g, ' ').trim();   // own text + children not inside a container
      if (text.length > 90) add('loose-text', el, `${text.length} characters: "${text.slice(0, 40)}…"`); }
    // 6 type scale and colours
    const scale = getComputedStyle(document.documentElement).getPropertyValue('--type-scale').trim().split(/\s+/).map(Number);
    const colours = tokenColours();
    for (const el of all) { const s = getComputedStyle(el);
      const hasText = Array.from(el.childNodes).some((n) => n.nodeType === 3 && n.textContent.trim());
      if (hasText && !scale.includes(Math.round(parseFloat(s.fontSize)))) add('font-size', el, s.fontSize);
      if (hasText && !colours.has(s.color)) add('colour', el, `text ${s.color}`);
      if (!colours.has(s.backgroundColor)) add('colour', el, `background ${s.backgroundColor}`);
      for (const side of ['Top', 'Right', 'Bottom', 'Left']) if (parseFloat(s[`border${side}Width`]) > 0 && !colours.has(s[`border${side}Color`]))
        { add('colour', el, `border ${s[`border${side}Color`]}`); break; } }
    // 7 Spotify status only in the page header (§5a, §12: a shared element is placed by its block, never by the page)
    for (const el of document.querySelectorAll('[data-read-status]'))
      if (!el.matches(SKIP) && !el.closest('[data-page-header]')) add('read-status', el, 'Spotify status outside the page header');
    // 8 chrome edge (plan library stage 5, D19): the page frame's left edge is --sidebar-w, the chrome's whole width, so
    // the foot's line and the page's edge can't drift apart. Only where the chrome stands: a page without the sidebar
    // (Setup, the missing-folder screen) has its frame at the window's edge
    if (document.querySelector('[data-test=sidebar]')) {
      for (const f of frames) {
        const probe = document.createElement('i');   // measured inside the frame, where --sidebar-w is inherited
        probe.style.cssText = 'position:absolute;visibility:hidden;width:var(--sidebar-w)';
        f.append(probe);
        const want = probe.getBoundingClientRect().width;
        probe.remove();
        const left = f.getBoundingClientRect().left;
        if (!Number.isNaN(want) && Math.abs(left - want) > 1) add('chrome-edge', f, `frame starts at ${Math.round(left)}, --sidebar-w is ${Math.round(want)}`);
      }
    }
    return v;
  };
})();
