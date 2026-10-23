# Hub page brief (phase 2 playbook)

The brief a page agent gets when it redesigns one hub page on the design system. Living document. The rules are in
`docs/hub-design-language.md`; the authority is the spec `docs/2026-10-20-hub-design-system-design.md` (§9 is this
playbook, §12 the rules for improving what you touch).

Load the `apple-design` and `emil-design-eng` skills before you start. Work in fake mode only
(`cd hub-ui && npm run dev`); never start a real sync, upgrade swap or Qobuz download.

---

## What you may edit

- Your page's folder, `hub-ui/src/pages/<page>/`, its fake scenarios and its `shots.json`, and its mockup.
- **Only the main agent edits `lib/components`, `lib/frames`, `tokens.css` and `designSystem.ts`.** If your page needs
  a change there (a missing pattern, a block flaw, a new token), stop and report it; don't build a local variant.
- **Never write a checker marker in a page** (`data-note`, `data-surface`, `data-frame`, `data-row-hit`, …): blocks and
  frames set them, and `lib/guards.test.ts` fails a page that does. Text that needs shelter goes into a block.
- Other pages: not yours. Flaws you see there go in your report (safeguard 5).

---

## The playbook (spec §9), always in this order

1. **Read.** Read `docs/hub-design-language.md`, the gallery (`#/dev/gallery` in fake mode) and the Sync reference
   (its section in the design-language doc and its shots). Screenshot the page's current states at three sizes:
   `cd hub-ui && node scripts/shots.mjs --port <dev port> --page <page>` (all three sizes by default).
2. **Audit.** List every rule the page breaks (an audit, in your report). Include the §12 critique: edges and
   alignment, grouping, space at 1100 and 2560, hierarchy, consistency, intent. A critique that finds nothing lists
   what it checked. Run `npm run rules -- --page <page> --force` for the checker's view of the current page.
3. **Mockup.** Make an HTML mockup in `docs/hub-mockups/design-system/<page>.html` using only existing blocks, or stop
   and flag a missing pattern.
4. **Review.** The main agent reviews the mockup against the rules; the user approves (mockups of a pair are shown
   together). **Stop here and wait.**
5. **Build.** Build the page, flag it (add it to `REDESIGNED` in `hub-ui/src/pages/designSystem.ts`; the main agent
   makes that edit, see above), keep every fake scenario, add shots for new states.
6. **Done** when `npm run verify`, `npm run build`, `npm run smoke` and the rule checker are green at all three sizes
   and the main agent has looked at the screenshots.

---

## Stop points

Stop, report and wait for the main agent when:
- **The mockup is ready** (step 4). Nothing is built before the main agent's review and the user's approval.
- **A pattern is missing.** No block covers what the page needs. Don't build it in the page; describe it (what, where,
  which states, a sketch). The main agent adds it centrally (block + gallery + design-language doc), then you use it.
- **A block, frame or token has a flaw** (system level, safeguard 2). Report it with its reason and where you saw it.
- **It's taste** (safeguard 4): a new look, what a colour means, or the layout direction of a whole page type. The
  user decides.
- **A recorded decision would change back.** Reopen a decision only for a reason it didn't weigh; a second reversal
  goes to the user (safeguard 3). Search spec §11 and the design-language doc's decision log first.
- **A checker rule seems wrong for a real case.** Never edit the checker or silence a rule; report it.

---

## The rules you work under (spec §12, in full)

**Improve, don't preserve.** The existing look is evidence, not law. No page, block or header is "how it is" just
because it exists. Write a critique of what your task touches before building, with `apple-design` and
`emil-design-eng` loaded, at all three sizes:
- **Edges and alignment:** does every line of content start and end on purpose? Which edges are hard (search field,
  buttons, row ends), and does everything that should meet them meet them?
- **Grouping:** do related things read as one object, unrelated ones as separate?
- **Space:** is empty space chosen, or left over? What happens to it at 1100 and at 2560?
- **Hierarchy:** what does the eye land on first, and is that the most important thing?
- **Consistency:** does the same element look, sit and behave the same on every other page?
- **Intent:** was this element designed, or carried over? Minimal is good only when it's a choice that serves the
  content. If it's just what was left, design it.

Every flaw you can fix inside the design system, you must fix. Flaws you can't (system level, or outside your task)
go in your report. A flaw visible in your screenshots that nobody flagged is a review miss, not a matter of taste.

**Consistency is absolute.** One element has one place, one look and one behaviour on every page. A shared element
(the page header, Spotify status with Read Spotify, the start button, filters) is placed by its block, never by the
page.

**Safeguards against drift:**
1. A reason, not a taste: every change names a skill rule, a spec section or a measured problem.
2. System changes are made once, centrally, by the main agent.
3. Decisions are recorded and stick; a second reversal goes to the user.
4. Taste goes to the user.
5. Scope: fix what your task touches; the rest goes in your report, then `docs/issues.md`.
6. Done is finite: done when every flaw your critique found is fixed or recorded.

---

## Your report

Write it to the path the main agent gives you, in this order:

1. **Audit:** every rule the page broke (rule, where, which shot), and the §12 critique (or what it checked).
2. **Mockup:** the path, `docs/hub-mockups/design-system/<page>.html`, and the decisions in it with their reasons.
3. **Missing patterns and system flaws:** what, where seen, why (empty if none).
4. **Files changed:** each path, one line on what changed.
5. **Verification output:** the last lines of `npm run verify`, `npm run build`, `npm run smoke` and
   `npm run rules -- --page <page>` (the summary line and any `FAIL` lines), plus `uv run pytest -q` if Python changed.
6. **Screenshots:** the paths you looked at (`hub-ui/screenshots/<shot>@<size>.png`), every state at three sizes.
7. **Out of scope:** flaws elsewhere for `docs/issues.md`.
8. **Concerns:** anything you're unsure of.

---

## Phase 2 order (spec §9)

Pairs, at most two page agents at a time, complex design work on the strongest model:
1. To-do + Dashboard · 2. Library + Playlists · 3. Download limits + Settings · 4. Setup + dialogs (Wrong song,
confirm).

Blocks both pages of a pair need are built by the main agent before the pair starts. Known phase 2 work is in
`docs/issues.md` (frames for Settings and All runs, Setup's titles
and link buttons).
