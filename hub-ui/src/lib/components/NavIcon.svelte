<script lang="ts" module>
  /** The pages of the app's navigation, in the rail's order (plan library stage 5 A3.1). */
  export type NavIconName = 'dashboard' | 'sync' | 'todo' | 'playlists' | 'limits' | 'library' | 'settings';
  // The shapes of the approved mockup (docs/hub-mockups/design-system/library-layout.html, `NAVI`), but Settings: one
  // family on a 14 px grid, drawn with a 1.3 px stroke in the text colour; a dot is a filled circle. Constant markup,
  // never user text, so {@html} is safe here.
  const SHAPES: Record<NavIconName, string> = {
    dashboard: '<rect x="1.5" y="1.5" width="4.6" height="4.6" rx="1.2"/><rect x="7.9" y="1.5" width="4.6" height="4.6" rx="1.2"/><rect x="1.5" y="7.9" width="4.6" height="4.6" rx="1.2"/><rect x="7.9" y="7.9" width="4.6" height="4.6" rx="1.2"/>',
    sync: '<path d="M11.9 5.6A5.1 5.1 0 0 0 2.6 4.3M2.1 8.4a5.1 5.1 0 0 0 9.3 1.3"/><path d="M2.4 1.6v2.9h2.9M11.6 12.4V9.5H8.7"/>',
    todo: '<circle cx="7" cy="7" r="5.6"/><path d="M4.6 7.1 6.2 8.7 9.5 5.3"/>',
    playlists: '<path d="M4.8 3.2h7.7M4.8 7h7.7M4.8 10.8h7.7"/><circle cx="2" cy="3.2" r=".5" fill="currentColor"/><circle cx="2" cy="7" r=".5" fill="currentColor"/><circle cx="2" cy="10.8" r=".5" fill="currentColor"/>',
    limits: '<path d="M1.9 10.6a5.3 5.3 0 1 1 10.2 0"/><path d="M7 9.3 9.4 6.1"/><circle cx="7" cy="9.6" r=".7" fill="currentColor"/>',
    library: '<path d="M5.2 10.9V3.1l6.6-1.5v7.7"/><circle cx="3.6" cy="10.9" r="1.6"/><circle cx="10.2" cy="9.3" r="1.6"/>',
    // a gear (six teeth, a hole), never rays: the mockup's eight rays round a dot read as a sun (the user, step A)
    settings: '<path d="M5.64 2.82 5.77 1.23A5.9 5.9 0 0 1 8.23 1.23L8.36 2.82A4.4 4.4 0 0 1 9.94 3.73L11.38 3.05A5.9 5.9 0 0 1 12.61 5.18L11.3 6.09A4.4 4.4 0 0 1 11.3 7.91L12.61 8.82A5.9 5.9 0 0 1 11.38 10.95L9.94 10.27A4.4 4.4 0 0 1 8.36 11.18L8.23 12.77A5.9 5.9 0 0 1 5.77 12.77L5.64 11.18A4.4 4.4 0 0 1 4.06 10.27L2.62 10.95A5.9 5.9 0 0 1 1.39 8.82L2.7 7.91A4.4 4.4 0 0 1 2.7 6.09L1.39 5.18A5.9 5.9 0 0 1 2.62 3.05L4.06 3.73A4.4 4.4 0 0 1 5.64 2.82Z"/><circle cx="7" cy="7" r="1.7"/>',
  };
  export const NAV_ICONS = Object.keys(SHAPES) as NavIconName[];
</script>

<script lang="ts">
  // A page's icon in the app's navigation (plan library stage 5 D16.6, notes N1 and house rule 6): drawn, 14 px, a
  // 1.3 px stroke, one family, the same in the full sidebar and the rail. In the rail the icon is the only label, and
  // the old text glyphs (◉ ⟳ ✓ ≡ ◔ ⚙) rendered at 12 px as dots and rings that couldn't be told apart. It takes the
  // colour of its row (currentColor), so the nav's grey, hover and selected colours apply unchanged. Decorative: the
  // row's text (full form) or its tooltip and aria-label (rail) names the page.
  let { name }: { name: NavIconName } = $props();
</script>

<svg class="nav-icon" viewBox="0 0 14 14" aria-hidden="true" data-nav-icon={name}>{@html SHAPES[name]}</svg>

<style>
  .nav-icon { display: block; flex: none; width: 14px; height: 14px; fill: none; stroke: currentColor;
    stroke-width: 1.3; stroke-linecap: round; stroke-linejoin: round; }
</style>
