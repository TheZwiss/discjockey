// Blocks the design system replaces (spec §7). A page listed in REDESIGNED (src/pages/designSystem.ts) must not
// import one; src/lib/outdated.test.ts enforces it. Deleted when phase 2 ends.
export const OUTDATED = [
  'SplitView', // fixed list width and a stretching panel: use ListPanelFrame
  'Chip', // a loose pill: use ToggleGroup or Segmented
  'ChipGroup', // pills that wrap: use ToggleGroup or Segmented
  'Tile', // a stat tile: use StatCard
  'Card', // a bare card: use Surface
  'SectionLabel', // a floating section title: use a Surface label
] as const;

// Tokens kept only for the pages not yet redesigned (tokens.css marks each OUTDATED); a redesigned page uses none.
export const OUTDATED_TOKENS = [
  '--main-w', // use the frames
  '--fs-big', // use --fs-stat
  '--t-fast', '--t-med', // use --t-press / --t-state / --t-value / --t-live
  '--r-input', '--r-btn', '--r-card', // use --r-ctl / --r-surface
] as const;
