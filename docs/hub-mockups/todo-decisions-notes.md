# To-do decisions: notes to the mockup

Companion to `todo-decisions.html`. Open it from disk. The bar on top switches Before / After, the state, and the window
size (1100 × 700 is the smallest, 1280 × 800 the default). ← / → step through the states and `b` flips Before / After.
The URL hash keeps the view (`#mp3/after/1100`). In the After view the choices can be clicked, and "Replace with
lossless" goes on to the matching "After" state.

The app is dark only (OLED, `tokens.css`), so there is no light version to check. Every text was measured at
1100 × 700 with a 320 px panel: nothing is cut off and there are no tooltips that carry meaning. Where the panel is
taller than the window (the AIFF states, after a replace), its body scrolls and the foot stays, as in `Panel`.

## What the live test showed

- **Upgrade:** the result of "Add as new file" sat in a tooltip that was cut off at the window's edge. The cue line
  said one thing before the step and another after it, and a green dot stood beside "a new rekordbox entry". Undo
  was a loose orange link under Done.
- **The user's model** (their feedback on the live app): both buttons mean "replace my lossy file with the lossless
  one". Only rekordbox differs: Swap keeps the same rekordbox track and its cues (AIFF only), and Add as new file
  makes a new track that they relocate to keep the cues.
- **Duplicates:** "Move to Superseded" sat on each card's head with no word on what it means. "Keep both" was the
  orange main action, nothing was recommended, and folder paths served as headings.

## Upgrade ready: one action, with rekordbox as the choice

- **The action is named by what happens to the track:** the one filled button is **Replace with lossless**, the same
  for Swap and Add as new. The engine's two modes stay as they are; the panel maps "Same track" to `swap` and "New
  track" to `add_new`.
- **"In rekordbox" card.** This is the only place where the two ways differ, so it is the only choice:
  - **AIFF and the same edit** (Swap possible): two radio rows, **Same track** (Recommended, picked) and **New
    track**. The picked row lists what happens in rekordbox (outcome lines), and the other row shows a one-line
    summary. You can compare the two without clicking.
  - **Swap not possible** (MP3, a different edit, couldn't compare): there is no choice. The card says what will
    happen ("rekordbox lists it as a new track", then "Relocate your old track to it: cues fit", "A different edit: set
    the cues again" or "Unsure if your cues fit: listen first"), and a grey line gives the reason ("Same track needs
    an AIFF file", "…the same edit", "…a measured match").
  - The file outcome is the card's last row: "Your old file is kept in Superseded/".
- **Outcome lines** each have a glyph. ✓ green means it stays as it was or fits. ⓘ yellow means you need a step in
  rekordbox. ✕ red means something is lost (used in the confirm only). Grey with a folder glyph is about a file.
  Each line is short enough for one line at 1100.
- **The match is a fact about the audio, not about the cues:** an "Edit" row under the comparison with "The same edit
  as yours" / "The same edit, 12 ms later" (green), "A different edit" (yellow) and "Couldn't compare them" (grey).
  The green no longer promises anything about rekordbox; the "In rekordbox" card says that. **Fix for the implementer:**
  `cueTone` checks `'aligned'`, but the engine's result is `'shifted'`, so a shifted match shows yellow today.
- **Compare:** the old "▶ Compare" button becomes a play button with a `Segmented` Now | New beside it, so A/B is
  visible as A/B. Now / New labels sit in each spectrum's format line ("NOW MP3 320 kbps", "NEW Lossless").
- **Discard** is a secondary wide button under Replace, with its confirm. It is the second real answer ("not this
  version") and no longer a muted link.
- **Undo before the click:** a one-line hint under the buttons says "You can undo a replace until you press Done".
  This answers "why did it not warn me / why no undo" before the step.
- **Current file** card dropped from the upgrade decision. Its facts (format, source) are in the Now column, and its
  "Wrong song?" belongs to the tracks that aren't lossless yet.
- **List rows** get a short status instead of the engine's sentence: "Lossless ready · cues can stay",
  "· new rekordbox track", "· different edit", "· not compared". These need a short form from the engine, or a
  mapping in `todoModel` (`views.py` `cue_text` is the long form).

## After the step: rekordbox check, Done and Undo

- **"In rekordbox" card (yellow):** numbered steps instead of a paragraph. For the same track: 1 Reload Tag, 2 Analyse
  again, plus a hint about Auto Relocate. For a new track: 1 Auto Relocate finds the new file by its name, 2 Analyse
  again, "your cues fit" or "set the cues again". The words follow the README; nothing new is claimed about
  rekordbox.
- **"Replaced with lossless · 2 min ago" card:** where each file is now (Library / Superseded), then one hint
  saying what Undo puts back.
- **Foot, using the height and not the width (the user's wish):** **Done, checked in rekordbox** (filled, full width),
  and under it **↶ Undo the replace** as a full-width secondary button. They are aligned and the same width, and the
  hierarchy is clear: filled above, plain below. This replaces the orange text link, and the label keeps its full
  wording.
- Undo keeps its confirm ("Undo the replace?"). Its tooltip says what it does.

## Duplicates: "Which file stays?"

- **One radio list of the files.** Line 1 is quality and format (badge, "AIFF · 16-bit"); line 2 is the folder's last
  part plus "in your playlists"; ▶ is at the row's end. The full path and the file name are the tooltip. The song's
  name ("Artist - Title") is in the head, not repeated per file, and folder paths are no longer headings.
- **The app recommends:** the best file is picked and says why in one line ("Recommended: best quality" /
  "…AIFF keeps tags"). Proposed ranking, from what the engine knows: quality (lossless before lossy, then
  cutoff/bitrate), then in a playlist, then AIFF before WAV (tags), then inside `Library/` before an import folder.
- **The consequence shows live:** every file that won't stay shows "→ Goes to Superseded/" (yellow) in its row, and
  the button says exactly what happens: **Move 1 file to Superseded** / **Move 2 files to Superseded**. A one-line
  hint under it reads "Not deleted: kept in Superseded/". There is no longer a separate note box.
- **Keep both / Keep all** is the last row of the same list, ruled off, with "Both stay; this to-do goes away". It is
  a choice like the others; it is no longer the default primary.
- **No clear winner** (same quality and length): nothing is picked. The header says "no clear winner" with one line
  inside the card ("Same quality and length. Keep the one in the folder rekordbox uses."). The filled button is
  switched off and reads "Choose the file that stays".
- Three files: same list. Keeping two of three takes two passes; it is rare enough.

## Empty state

With nothing left, the panel says "Nothing to decide" and when it will have something, so it is never blank. When
there are to-dos the first one is always selected (`keepSelection`), so there is no "no selection" state with items.

## New pattern (to add centrally if approved)

**ChoiceGroup:** radio rows inside a `Surface flush`, each a name (+ an optional "Recommended" in accent caps), a
one-line summary, and the outcome lines when picked. A row that can't be picked is dimmed (`--dim-locked`) with
its reason. Both panels use it. It would go into `lib/components` with a gallery entry and a design-language row
("one of a few, each with a consequence → ChoiceGroup"). The outcome lines' green / yellow / red need a colour-rule
amendment, "an outcome in a decision: kept / needs a step from you / lost", in the decision log.

## Words that change (README and tests follow)

"Swap the files" / "Add as new file" become **Replace with lossless** + Same track / New track. "Move to Superseded"
(per card) becomes **Move N files to Superseded** (foot). "Keep both" becomes a row. The README's Upgrades and
Duplicates sections name the old buttons.

## Open questions for the user

1. Is **Replace with lossless** the right word for the action? Another option: "Use the lossless version".
2. For a new track, rekordbox needs Auto Relocate. Should the panel also say **quit rekordbox first** (the README's
   tip) above the button, or is that known?
3. **Which file rekordbox uses** isn't known to the app (it never reads rekordbox). Reading the rekordbox XML
   export would make the duplicates recommendation surer. Worth a later stage?
