# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 24. Identify imported files by their sound (AcoustID) — wish, after stage 4

Follow-up of `docs/2026-10-23-library-and-sources-design.md` (§1 out of scope, §10.3). Files with missing or wrong tags
are identified today only from tags and file names. An opt-in setting would send Chromaprint fingerprints to AcoustID
(free service; needs an application key and the `fpcalc` program bundled, with its licence in `packaging/licenses/`)
and use the returned recording's ISRC and names. Ask the user before building: it sends data about their files to an
outside service.
