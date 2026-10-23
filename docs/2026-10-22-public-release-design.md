# Public release: Discjockey.app as a .dmg from a public GitHub repo — design

Status: draft for review (2026-10-22).

## 1. Goal

Anyone with an Apple Silicon Mac downloads `Discjockey-<version>.dmg` from the GitHub Releases page of a public repo,
drags Discjockey into Applications, allows it in System Settings (once per downloaded version), and is guided by
Setup from there. They never
need Terminal, Homebrew, Python, `uv` or the source code.

Decided with the user:

- **Audience:** friends and the public.
- **No Apple Developer Program.** The app is not notarized; the README walks users through "Open Anyway" once.
- **Name: Discjockey.** The parked rename (issue #5) is done first, so nothing ships under the old name.
- **A new public repo with a fresh history.** `TheZwiss/discjockey` starts from one clean commit; the private repo
  stays as the archive with the full history.
- **App updates: a notice and a download link.** No self-replacing updater.
- The user left the technical choices to Claude; they are made below with their reasons.

Out of scope: Intel Macs, the Mac App Store, Windows/Linux, a self-updater, translations.

## 2. What the user experiences

1. On the Releases page they download `Discjockey-1.0.0.dmg` (about 150 MB).
2. The .dmg opens a window: the Discjockey icon, an arrow, and an Applications shortcut. They drag the icon across.
3. On first open, macOS says it can't check the app. The README (with screenshots) says: click **Done**, open
   System Settings → Privacy & Security, scroll down, click **Open Anyway**, then confirm. This happens once
   per downloaded version.
4. Setup starts. Its first step is new: **Your music folder** (create `~/Music/Discjockey` or choose an existing
   folder). Then Spotify, Downloads, First playlist, as today. The "Programs" and "Dock icon" steps are gone.
5. When a newer version is out, the sidebar shows a quiet line "Discjockey 1.1 is available". Clicking it opens the
   release page; they drag the new app over the old one. Their music, logins and settings are untouched.

What the README states up front: Apple Silicon Mac; macOS version (§6.6); a **Spotify Premium** account (since
February 2026 Spotify only lets Premium accounts create the developer app every user needs); only playlists the user
owns or collaborates on can be read (Spotify's rule, already handled by the engine); Qobuz is optional.

## 3. Rename to Discjockey (first phase)

Scope as measured in issue #5 (about 1100 hits in about 120 files):

- Shown name everywhere (window title, menu bar, Dock, sidebar brand, page copy, README): "Discjockey".
- Package `djsync/` → `discjockey/` (`git mv`), all imports, `pyproject.toml` name, `uv sync` for `uv.lock`.
- Launcher `dj_sync` → `bin/discjockey` (a root-level `discjockey` would clash with the package folder; developer
  use only, §8). The user's zsh alias becomes `discjockey`.
- Bundle id `io.github.thezwiss.discjockey`, icon `discjockey.icns` (the same artwork renamed).
- Env vars `DJ_SYNC_*` → `DISCJOCKEY_*`.
- Stored names (localStorage keys, report and cache file names, the user agent): renamed outright. The only existing
  user is migrated once by hand (§10), so no compatibility code ships.
- `docs/archive/` is not rewritten (it is history and does not go public, §9).

The old `dj_sync.app` in /Applications is removed once the new app runs (§10).

## 4. Where things live

Today the engine finds everything relative to its own source folder (`default_paths()` = the folder above the repo).
An installed app can't do that: its own folder is read-only and is replaced on every update. The data splits by what
it belongs to.

| Where | What | Why there |
|---|---|---|
| **Music folder** (chosen in Setup) | `Library/`, `Superseded/`, `Upgrades ready/`, `playlists.txt` | What the user sees and points rekordbox at. Unchanged inside. |
| **`<music folder>/.discjockey/`** (hidden) | `state.json`, `.lock`, `.tmp/`, `reports/`, `not_lossless.md` | They describe this one library. `.tmp/` has to be on the same drive as `Library/` so `run_op`'s renames stay atomic, and moving the library to another drive takes its state along. |
| **`~/Library/Application Support/Discjockey/`** | `config.json` (the music folder's path), `settings.json`, `.spotify_app.json`, `.spotify_token.json`, `streamrip/`, `cache/`, `tools/` (§6.4) | Belong to this Mac and user, not to one library. |
| **`Discjockey.app`** | Python, packages, the built UI, `ffmpeg`, `ffprobe`, `deno`, licences | Read-only, replaced whole on update. |

Engine changes:

- `Paths` gets two roots, `music` and `support`, and loses `pipeline`. Every property maps to the table above.
  The tests' fixtures build both under `tmp_path`.
- `default_paths()` is replaced by `resolve_paths(support_dir)`: it reads `config.json`. Without a music folder set,
  the hub opens Setup on the music-folder step and nothing else runs; the console version says to run Setup.
  `DISCJOCKEY_SUPPORT` overrides the support folder (tests and developer runs against a scratch library).
- A configured music folder that is missing (an unplugged drive) gets its own state: the hub shows "Your music
  folder isn't there" with **Choose another** / **Try again**, never a crash and never a fresh empty library
  created in its place.
- Changing the music folder in Settings is refused while a change runs (the library lock), like other write methods.
- `qobuz.write_config` already writes streamrip's paths (`downloads.folder` = `.tmp/`); it runs before every Qobuz
  use, so a changed music folder is picked up without a migration.
- `not_lossless.md` stays a file the user can open: Settings/To-do link to it, as the reports folder is linked now.

UI: Setup's new first step and a "Music folder" row in Settings → This Mac (**Change…**, **Show in Finder**), built
from the existing blocks (a `ToggleGroup` for "new folder / existing folder", the standard card). The folder is
picked with pywebview's native folder dialog. The design-language rules and the design skills apply as for any page.

## 5. Building the app

**Tool: PyInstaller** (one-folder `.app` via its `BUNDLE` step), driven by a checked-in `packaging/discjockey.spec`.

Why: it is the most-used freezer, has maintained hooks for pywebview and pyobjc, gives Apple Silicon's required
signature to every binary, and is what pywebview's own docs show. The alternatives were a hand-built bundle with a
standalone Python and a venv (closest to today's launcher, but bigger and with more ways to break) and Briefcase
(made around its own widget toolkit; a pywebview app there would be finding its bugs).

- Entry point: `discjockey/app_main.py` starts the hub directly. The process *is* the app, so the Dock shows
  Discjockey with its icon. `bundle.py`'s generated script app and Setup's Dock-icon step are deleted.
- Data files: `discjockey/hub/static/`, the icon, the licences (§6.5).
- `Info.plist`: name, bundle id, version (§7), `LSMinimumSystemVersion` (§6.6), `NSHighResolutionCapable`, and the
  usage text macOS shows when the app reads browser logins.
- Architecture: arm64 only.

## 6. Bundled programs and download tools

### 6.1 ffmpeg, ffprobe, deno inside the app

- They sit in `Contents/Resources/bin/`. On start, `discjockey/tools.py` `activate()` puts that folder **first on
  `PATH`**. Every existing `["ffmpeg", …]` call, streamrip and yt-dlp (which finds deno on `PATH`) then use the
  bundled copies with no change at the call sites. One mechanism instead of passing paths through every module.
- In a source checkout (no bundled folder) `activate()` changes nothing; Homebrew's programs are used as today.
- Setup's "Programs" check stays for developer runs, but in the app it never finds anything missing.
- The `PATH` line in `bundle.py`'s script goes away with the script.

### 6.2 Where the binaries come from

`packaging/tools.json` pins each binary: version, download URL, SHA-256. The build downloads them, checks the hash,
and fails on a mismatch. Sources: `deno-aarch64-apple-darwin.zip` from Deno's GitHub releases; ffmpeg and ffprobe
built from FFmpeg's own source release (`ffmpeg-<version>.tar.xz` from ffmpeg.org, pinned by SHA-256) by
`packaging/build_ffmpeg.sh`, with the configure arguments `tools.json` lists. `fetch_tools.py` builds them on a cache
miss and caches the result under a key of the source hash, the arguments and the script; CI caches `dist/cache/`.
The configuration links no external library (`--disable-autodetect`; only FFmpeg's own code plus macOS's zlib,
bzip2 and Security framework), so every part of the binary is GPL-3.0 compatible and its corresponding source is the
pinned tarball plus the script (issue 19: the earlier prebuilt static build linked libzvbi, two of whose files are
GPL-2.0-only). FFmpeg's native decoders cover every format Discjockey reads (FLAC, ALAC, WAV, AIFF, MP3, AAC/M4A,
Opus, Vorbis), and its HTTPS (Secure Transport) serves yt-dlp's section downloads; `audio.py`'s conversion settings
already avoid libsoxr. The one gap: with autodetection off there is no libxml2, so no `dash` demuxer (only
`webm_dash_manifest`). yt-dlp hands ffmpeg the manifest URL of a `http_dash_segments` format only for a section
download (the "Wrong song?" preview clips), so those take `bestaudio[protocol!=http_dash_segments]/bestaudio/best`;
full downloads use yt-dlp's own DASH downloader and are not affected.

### 6.3 Signing

macOS needs every binary on Apple Silicon signed, and the "Open Anyway" grant, the keychain's "Always Allow" for
"Chrome Safe Storage", and Full Disk Access (Safari logins) are tied to the app's signature.

- With an ad-hoc signature (no certificate) that identity changes with every build, so each update would ask about
  the keychain again and lose Full Disk Access.
- **Choice: a self-signed "Discjockey Release" code-signing certificate**, made once. It gives the app the same
  signing identity across versions, so those grants survive updates. Gatekeeper treats it like an unsigned app
  ("Open Anyway"), so it costs nothing and needs no Apple account.
- The certificate (`extendedKeyUsage=codeSigning`, exported as PKCS#12 with `openssl -legacy`) and its key live as
  GitHub Actions secrets (§7) plus a copy in the user's password manager. `codesign` only finds an identity whose
  keychain is on the user search list, so CI rebuilds `$DISCJOCKEY_SIGNING_DIR` from the .p12 secret (its own
  keychain, `identity.sha1`, `keychain.pass`, `set-key-partition-list`) and runs `build_app.sh` with
  `REQUIRE_IDENTITY=1`; no trust setting is needed, because `sign_app.py` picks the identity by its SHA-1 from that
  keychain alone, which `scripts/make_signing_identity.sh` (it never trusts the certificate) lays out the same way.
- PyInstaller ad-hoc signs everything it collects, the bundled tools included, so every nested Mach-O file is
  re-signed with `--force` (deepest first, then `Contents/MacOS/Discjockey`, then the bundle). Spike result: two
  builds signed this way have an identical designated requirement; `spctl` rejects them as expected.
  Losing it only means users grant the keychain and Full Disk Access once more.
- The build signs inside-out (bundled binaries, Python extensions, then the app) without the hardened runtime: only
  notarization requires it, and its library validation would need extra entitlements for self-signed libraries.
- The same stable identity keeps macOS's one-time folder prompts (Downloads or Desktop for a dropped file,
  Documents if the music folder is there) from coming back after an update.

### 6.4 Download tools that can update without an app release

yt-dlp breaks every few weeks when YouTube changes, so a version frozen into the app goes stale between releases.

- The app ships yt-dlp and yt-dlp-ejs as **plain files** (PyInstaller `module_collection_mode={'yt_dlp': 'py',
  'yt_dlp_ejs': 'py'}`; proven in the spike: an earlier `sys.path` entry wins, an empty one falls back).
- `<support>/tools/current/` (a folder named by version, `current` pointing at it) holds updated copies and comes
  **before** them on `sys.path` — but only when its version is newer than the built-in one, which the startup code
  compares before inserting it (path order alone can't express "newer wins"). A release with a newer built-in
  yt-dlp is then not shadowed by an old update. The frozen app never writes bytecode
  (`sys.dont_write_bytecode`), so nothing is written into the signed bundle.
- **Update download tools** (Settings → This Mac) downloads the newest yt-dlp and yt-dlp-ejs wheels from PyPI's JSON
  API, checks their SHA-256 against PyPI's, unpacks them into a new version folder, and **tests them in a separate
  process** (`Discjockey --check-tools <folder>` imports them and prints the version). Only a passing folder becomes
  `current`; the previous one is kept for one rollback. Then the page asks to reopen the app, as today.
- streamrip is only updated with app releases (it changes rarely and has native dependencies).
- In a source checkout the same mechanism runs against `DISCJOCKEY_SUPPORT`'s folder. Nothing touches `uv.lock`
  any more; developers bump it deliberately. **This closes issue #10.**
- Settings → This Mac shows "yt-dlp 2026.10.21 (updated)" or "(built in)".

### 6.5 Licences

The repo is **GPL-3.0** (`LICENSE`): streamrip is GPL-3.0-only and mutagen GPL-2.0-or-later, so an app that
includes them must be GPL-3.0. The app carries `Resources/licenses/` with each bundled component's licence and,
for ffmpeg (GPL build), where its source is published. Settings → This Mac links to them.

### 6.6 Minimum macOS

`LSMinimumSystemVersion` is the highest minimum among the bundled parts. Spike measurement: ffmpeg 9.0.2 and deno
2.9.8 need **macOS 12.0**, Python 11.0 — but numpy's wheel follows the build Mac (macOS 14 on a new Mac), so the
build installs dependencies for a fixed platform (`uv … --python-platform aarch64-apple-darwin`, which picks the
`macosx_11_0` wheels). The build checks every Mach-O file's `minos` (`vtool`) and fails above 12.0. The README
says macOS 12 Monterey or later.

## 7. Versions and releases

- **One version source:** `discjockey/__init__.py` `__version__` (semantic, starting at `1.0.0`). `pyproject.toml`
  repeats it, and a test fails when they differ. The build writes it into `Info.plist`; Settings → This Mac shows it.
- **GitHub Actions on a tag `v*`** (`macos-15`, arm64, free for public repos; the older macOS 14 image is retired by GitHub on 2 Nov 2026): `uv sync`, the public check, `npm ci` +
  `npm run build` (the tests and `npm run verify` run locally before the tag instead, amended 2026-10-23: the
  design-rules pass alone took 15+ minutes on a runner; the app bundles the committed `hub/static`, and `build_app.sh` step 1 fails unless a fresh build equals it: stricter, same bytes), download and verify the
  tools, PyInstaller, sign, **self-test**, make the .dmg, and attach it to a **draft** release. The user publishes
  the draft after a look, so nothing goes public by accident.
- **Self-test:** `Discjockey.app/Contents/MacOS/Discjockey --self-test` imports every engine module, runs the bundled
  `ffmpeg -version`, `ffprobe -version`, `deno --version`, converts a generated one-second tone to AIFF, loads the UI
  file, and exits 0. Failing it fails the release. It never touches a network or a real library.
- **The .dmg:** `dmgbuild` (pinned; it needs no Finder or AppleScript, so it runs headless in CI) with a background image (the arrow), the app icon and an Applications link;
  file name `Discjockey-<version>.dmg`.
- **Local build:** `scripts/build_app.sh` runs the same steps on the user's Mac (ad-hoc signing when the certificate
  isn't in the keychain) for testing before tagging.

## 8. Update notice

- On start (and then daily while open) the engine fetches `api.github.com/repos/TheZwiss/discjockey/releases/latest`
  (unauthenticated; the limit of 60 an hour is plenty), compares semantic versions, and caches the answer for a day
  in `<support>/cache/`. Network errors, rate limits and drafts are silent: no line, nothing logged as an error.
- A newer version → a bridge event; the sidebar shows one line under the brand ("Discjockey 1.1 is available") that
  opens the release page in the browser. Settings → This Mac shows "Up to date" or the same link.
- No setting to switch it off (one request a day, no data sent beyond the request). The README says it happens.
- Contract: a new bridge method/event, so `docs/hub-bridge-contract.md`, `types.ts`, `contract.ts` and the fake
  backend change in the same commit, with fake scenarios for "up to date" and "update available".

## 9. The public repo

- **Fresh history:** after all phases are merged into private `main` and pushed, an orphan branch holds the
  scrubbed tree as one commit and is pushed as `main` of the new public repo `TheZwiss/discjockey`. The local
  checkout stays where it is, with `origin` pointing at the public repo; the old history stays in the private repo
  (and locally as `archive/main` until the user removes it).
- **Author identity:** from then on commits use the user's GitHub no-reply address (`<id>+TheZwiss@users.noreply.github.com`),
  set in the repo's git config, so no personal e-mail is published.
- **What goes public:** the code, tests, `hub-ui`, `packaging/`, `.github/workflows/`, `LICENSE`, the living docs
  (`hub-design-language*`, `hub-bridge-contract.md`, `hub-page-brief.md`, `hub-mockups/`, `issues.md`) and
  `CLAUDE.md`, this spec and its plan.
- **The existing archive stays private.** `docs/archive/` as it is today (thousands of lines with personal paths, a
  colleague's test notes) moves to `docs/archive/pre-public/`, which is gitignored but stays tracked in the private
  repo until the cutover (the public tree leaves it out). After the cutover it is restored onto disk, untracked, so
  docstring citations like `spec "hub" 6.8` still resolve for the maintainer. Plans archived after going public go
  into `docs/archive/` as usual and are public. `CLAUDE.md` says so.
- Any other file that refers to the user's real library or data is fixed or left out; the check script decides.
- **Scrub, checked by a script:** no macOS user name, no real name, no university e-mail, no real person's `/Users/`
  path (made-up `/Users/you`, `/Users/dj`, `/Users/someone`, `/Users/x` are allowed), no private repo URL in the tree
  (`scripts/check_public.sh`, also run in CI on every push). The script's rules are generic; the personal words come
  from a local file outside the tree (`~/.discjockey-public-denylist`) and, in CI, from a secret
  (`PUBLIC_CHECK_DENYLIST`). Test data uses made-up names (`spotify_user: 'dj'`).
- **README split:** `README.md` becomes the user manual: download, "Open Anyway" with screenshots, requirements,
  Setup, everything else it says today. Developer notes (checkout, `./discjockey`, tests, the UI workflow, how to
  release) move to `CONTRIBUTING.md`. `CLAUDE.md` loses "single user, private repo" and the `DJ Downloader/` layout,
  and gains the new layout and release commands.
- **Legal note in the README:** what the tool does, that it needs the user's own Qobuz/Spotify accounts, and that
  users are responsible for following those services' terms. (Public downloaders draw takedown requests at times;
  streamrip and yt-dlp being public on GitHub is the precedent.)
- Creating the public repo and publishing the first release are outward-facing: Claude asks the user for a last go
  at both moments, even with everything else approved.

## 10. Moving the user's own setup (one-off, not shipped)

Done by Claude once the app runs, with a script in the scratchpad (not in the repo), **copying, never moving**:

- `DJ Downloader/` becomes the music folder (`Library/` etc. stay exactly where they are).
- `Lossless Pipeline/state.json`, `reports/`, `not_lossless.md` → `DJ Downloader/.discjockey/`.
- `settings.json`, `.spotify_app.json`, `.spotify_token.json`, `.streamrip/` → `~/Library/Application Support/Discjockey/`.
- Paths inside `state.json` are relative to the music root, so they need no change; the copied file is compared
  with a check that every tracked file still resolves.
- Verify in the real app (read-only: open every page, no sync, no Qobuz download), then remove
  `/Applications/dj_sync.app`. The old gitignored files stay in the checkout until the user says to delete them.

## 11. Testing

- **Engine (pytest, offline):** `resolve_paths` (no config, missing folder, override env var), every `Paths`
  property under the new roots, the missing-music-folder state, `tools.activate()` with and without a bundled
  folder, the tools updater (wheel hash mismatch refused, failing `--check-tools` keeps the old `current`, rollback,
  newer built-in wins), version comparison and the update check (network stubbed: newer, same, error, rate limit),
  the version-source test.
- **UI:** models for the music-folder step and the update line with `*.test.ts`; fake scenarios plus `shots.json`
  entries (Setup music folder: empty/chosen/missing; sidebar update line; This Mac rows); `npm run verify`,
  `build`, `smoke`; screenshots looked at.
- **Build:** the frozen self-test (§7) locally and in CI.
- **Live checks for the user** (only what needs a human): install from the .dmg on their Mac including "Open
  Anyway"; one sync in the installed app; one Chrome login prompt ("Always Allow"); then installing a second build
  over the first keeps that grant (§6.3).

## 12. Phases

1. **Rename** to Discjockey (§3).
2. **Paths split** + music-folder step in Setup and Settings (§4).
3. **Bundled tools + updatable download tools** (§6.1, §6.4; closes #10).
4. **Packaging:** PyInstaller spec, signing certificate, self-test, .dmg, `build_app.sh` (§5, §6.2, §6.3, §6.5–6.6).
   The spike (2026-10-22, PyInstaller 6.22.3) settled the unknowns: the frozen hub renders, the native folder dialog
   works, the yt-dlp override works, a self-signed identity is stable across builds, the bundled ffmpeg converts
   every source format. Its working files (`discjockey.spec`, `build.sh`, `sign.sh`, kept in the gitignored `.superpowers/spike-packaging/`) seed this phase's plan.
   Measured: `.app` 276 MB (203 MB of it the three tools), `.dmg` 148 MB.
5. **Update notice** (§8).
6. **Public repo:** scrub + check script, licence, README/CONTRIBUTING/CLAUDE.md, CI workflow, then (with the
   user's go) the public repo and the first draft release (§7, §9).
7. **The user's own move-over** (§10).

Issue #10 is closed by phase 3; issue #5 by phase 1.

Each phase gets its own plan, `docs/2026-10-22-public-release-<n>-<topic>-plan.md` (finished ones in `docs/archive/`), written when the phase before it
is merged, so its code steps match the code as it is then.

## 13. Risks

- **FFmpeg's source release moves or changes.** It's pinned by hash; the build fails loudly. The same release is
  mirrored on FFmpeg's other download hosts, and the hash proves any copy.
- **Spotify tightens further.** It's already a hard requirement (Premium, own playlists), stated up front.
- **"Open Anyway" scares some users.** The README shows each screen; that's the cost of not paying Apple.
