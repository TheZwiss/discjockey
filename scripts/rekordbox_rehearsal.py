"""Rehearse issue 33's Same track batch on a copy of a real rekordbox library (plan stage B §7 RH).

Nothing here opens the real library: `copy-db` copies `master.db` before anything opens it, and every later step opens
only that copy. The user's audio and analysis files are read only to copy them (`copy-tracks`). Every path is an
argument; the work folder must lie outside the repo. Each step refuses while rekordbox runs or a `-wal`/`-shm` lies
beside the library it starts from.

    uv run python scripts/rekordbox_rehearsal.py copy-db --source ~/Library/Pioneer/rekordbox --work W
    uv run python scripts/rekordbox_rehearsal.py candidates --work W            # track ids by kind, no names
    uv run python scripts/rekordbox_rehearsal.py copy-tracks --source ~/Library/Pioneer/rekordbox --work W \
        --track "MP3 #1=<id>" --track "M4A 44.1 #1=<id>" ...
    uv run python scripts/rekordbox_rehearsal.py rehearse --work W [--edit-title "M4A 44.1 #2"]
    uv run python scripts/rekordbox_rehearsal.py rehearse-sync --work W --no-analysis "MP3 #2"
    uv run python scripts/rekordbox_rehearsal.py rehearse-convert --work W   # picks: MP3 #1, M4A 44.1 #1, M4A 48 #1, AIFF #1

`rehearse` (plan RH steps 3–7): copies `W/source/master.db` to `W/rb/master.db`, points the chosen tracks at their
copies in `W/music/Library/Rehearsal/` with Discjockey's own writer (and edits one title, a user edit to keep), makes
a scratch Discjockey library (`W/support`, music folder `W/music`) with the copies as own songs and per track a parked
upgrade rendered from its own audio, takes the "before" picture, runs `bin/discjockey upgrade apply --all --way
same-track --json` and `bin/discjockey batch undo <id> --json` with `DISCJOCKEY_SUPPORT` and `DISCJOCKEY_REKORDBOX`
pointing into `W`, and checks each step with Discjockey's reader. It prints one PASS/FAIL line per check (tracks by
their labels only) and writes `W/report.json`. Exit code 0 when every check passes, 1 otherwise, 2 when it refuses.
`rehearse-sync` (plan stage C §7 RH): the same copies, but the sync's Auto-upgrade phase instead of `upgrade apply`;
see its docstring. `rehearse-convert` (plan stage D §7.1): Convert to AIFF, Give it its clean name, Make all lossless
files AIFF and the CDJ group's Convert all; see its docstring. Run these on a work folder that only `copy-db` and
`copy-tracks` have touched (they change the copies).
Delete `W` afterwards: it holds the copies. `copy-db` marks `W` (`.discjockey-rehearsal`); `copy-tracks` and
`rehearse`, which delete inside `W`, refuse a folder without the mark, and every step refuses a `W` inside the
rekordbox folder or around it.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import quote

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from mutagen.aiff import AIFF  # noqa: E402

from discjockey import audio, auto_upgrade, config, library, quality, sources, upgrades  # noqa: E402
from discjockey.library import Paths  # noqa: E402
from discjockey.models import OWN_PREFIX  # noqa: E402
from discjockey.settings import load_settings  # noqa: E402
from discjockey.names import expected_stem  # noqa: E402
from discjockey.planner import ENTRY_KEYS  # noqa: E402
from discjockey.rekordbox import anlz, eligible, master, offset, process, timing, write  # noqa: E402
from discjockey.rekordbox.locate import Place  # noqa: E402

FOLDER = "Rehearsal"
ALBUM = "Rehearsal Album"
LABEL = "Rehearsal Label"
QUALITY = "Qobuz FLAC · verified lossless"
EDIT = " (my edit)"
SPLICED = (".DAT", ".EXT", ".2EX")
RELATED = ("djmdCue", "contentCue", "djmdSongPlaylist", "djmdSongHistory", "djmdSongMyTag")
LOOKUPS = ("djmdArtist", "djmdAlbum", "djmdLabel")
STAMP = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d\.\d{3} \+00:00$")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TEXT_COLUMN = write.TEXT_COLUMNS
LOOKUP_OF = {"artist": "djmdArtist", "album": "djmdAlbum", "label": "djmdLabel"}


class Refused(Exception):
    """The rehearsal can't run safely: nothing was done."""


# --- safety ---

def refuse_if_unsafe(db: Path) -> None:
    if process.running():
        raise Refused("rekordbox is running: quit it first.")
    if master.leftovers(db):
        raise Refused(f"{db.name} has -wal/-shm beside it (rekordbox didn't close cleanly): open and quit rekordbox.")


MARKER = ".discjockey-rehearsal"  # `copy-db` writes it; the steps that delete inside the work folder require it


def check_work(work: Path, source: Path | None = None) -> Path:
    """The work folder, resolved. It lies outside the repo and, when `source` is given, neither inside the source
    folder nor around it (a work folder around the real library would let `rehearse` delete inside it)."""
    work = work.resolve()
    if work == REPO or REPO in work.parents:
        raise Refused("The work folder must lie outside the repo.")
    if source is not None:
        real = source.resolve()
        if work == real or real in work.parents or work in real.parents:
            raise Refused("The work folder and the rekordbox folder must be separate folders (neither inside the "
                          "other).")
    return work


def need_marker(work: Path) -> None:
    if not (work / MARKER).is_file():
        raise Refused("This folder was not made by `copy-db`: start a new work folder with it.")


def env_for(work: Path) -> dict[str, str]:
    """The environment every Discjockey command of the rehearsal runs with: both overrides inside `work`."""
    env = dict(os.environ, **{library.SUPPORT_ENV: str(work / "support"), "DISCJOCKEY_REKORDBOX": str(work / "rb")})
    for name in (library.SUPPORT_ENV, "DISCJOCKEY_REKORDBOX"):
        value = env.get(name, "")
        if not value or not Path(value).resolve().is_relative_to(work):
            raise Refused(f"{name} is not set inside the work folder.")
        print(f"  {name}={value}")
    return env


# --- reading the copy ---

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def dump(db: Path) -> dict[str, dict]:
    """Every row of every table: `{table: {"cols": [...], "rows": {rowid: row}}}` (keyed read-only immutable open)."""
    con = master.connect(db, master.KEYS[0])
    try:
        out = {}
        for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"):
            cur = con.execute(f"SELECT rowid, * FROM {t}")
            cols = [c[0] for c in cur.description][1:]
            out[t] = {"cols": cols, "rows": {r[0]: tuple(r[1:]) for r in cur}}
        return out
    finally:
        con.close()


def diff(before: dict, after: dict) -> list[tuple]:
    """`(table, rowid, column, before, after)` per changed cell; `"<added>"` / `"<removed>"` for whole rows."""
    out = []
    for t in sorted(before.keys() | after.keys()):
        a, b = before.get(t, {"rows": {}}), after.get(t, {"rows": {}})
        cols = b.get("cols") or a.get("cols")
        for rowid in sorted(a["rows"].keys() | b["rows"].keys()):
            x, y = a["rows"].get(rowid), b["rows"].get(rowid)
            if x is None:
                out.append((t, rowid, "<added>", None, y))
            elif y is None:
                out.append((t, rowid, "<removed>", x, None))
            else:
                out += [(t, rowid, cols[i], u, v) for i, (u, v) in enumerate(zip(x, y)) if u != v]
    return out


def row(d: dict, table: str, key: str, value) -> tuple[int, dict] | None:
    cols = d[table]["cols"]
    i = cols.index(key)
    for rowid, r in d[table]["rows"].items():
        if r[i] == value:
            return rowid, dict(zip(cols, r))
    return None


def rows_where(d: dict, table: str, key: str, values: set) -> dict[int, tuple]:
    if table not in d or key not in d[table]["cols"]:
        return {}
    i = d[table]["cols"].index(key)
    return {rowid: r for rowid, r in d[table]["rows"].items() if r[i] in values}


def tree(folder: Path, skip: str | None = None) -> dict[str, str]:
    """SHA-256 of every file under `folder` (relative names), leaving out a top-level `skip` folder."""
    if not folder.is_dir():
        return {}
    return {p.relative_to(folder).as_posix(): sha256(p) for p in sorted(folder.rglob("*"))
            if p.is_file() and (skip is None or p.relative_to(folder).parts[0] != skip)}


def frames_of(path: Path) -> int:
    info = AIFF(str(path)).info
    return round(info.length * info.sample_rate)


# --- the commands ---

def copy_db(source: Path, work: Path) -> int:
    work = check_work(work, source)
    db = source / "master.db"
    refuse_if_unsafe(db)
    target = work / "source" / "master.db"
    if target.exists():
        raise Refused("The work folder already holds a copy: use a new one.")
    target.parent.mkdir(parents=True)
    shutil.copyfile(db, target)  # before anything opens it; the original is never opened
    if sha256(db) != sha256(target) or master.leftovers(db):
        raise Refused("The library changed while it was copied: quit rekordbox and start again.")
    (work / MARKER).write_text("a rehearsal's work folder: it holds copies only\n", encoding="utf-8")
    print("Copied master.db into the work folder.")
    return 0


def candidates(work: Path) -> int:
    con = master.connect(check_work(work) / "source" / "master.db", master.KEYS[0])
    rows = con.execute(
        "SELECT c.ID, c.FileType, c.SampleRate, c.FolderPath, IFNULL(c.Commnt, ''), "
        "(SELECT count(*) FROM djmdCue k WHERE k.ContentID = c.ID AND k.rb_local_deleted = 0 AND k.Kind > 0), "
        "(SELECT count(DISTINCT PlaylistID) FROM djmdSongPlaylist s WHERE s.ContentID = c.ID "
        "AND s.rb_local_deleted = 0) FROM djmdContent c WHERE c.rb_local_deleted = 0 AND c.usn IS NULL "
        "AND IFNULL(c.rb_local_synced, 0) = 0 AND c.AnalysisDataPath <> ''").fetchall()
    con.close()
    kinds = {"MP3 with hot cues": lambda r: r[1] == 1 and r[5] > 0,
             "M4A 44.1 kHz": lambda r: r[1] == 4 and r[2] == 44100,
             "M4A 48 kHz": lambda r: r[1] == 4 and r[2] == 48000,
             "AIFF 44.1 kHz": lambda r: r[1] == 12 and r[2] == 44100,
             "in two playlists or more": lambda r: r[6] >= 2,
             "a comment of the user's": lambda r: r[4] and not quality.is_quality_line(r[4])}
    for name, test in kinds.items():
        found = sorted((r for r in rows if test(r) and os.path.exists(r[3])), key=lambda r: (-r[5], r[0]))[:6]
        print(f"{name}: " + ", ".join(f"{r[0]} (hot cues {r[5]}, playlists {r[6]}, type {r[1]})" for r in found))
    return 0


def copy_tracks(source: Path, work: Path, tracks: list[str]) -> int:
    work = check_work(work, source)
    need_marker(work)
    refuse_if_unsafe(source / "master.db")
    picks = []
    con = master.connect(work / "source" / "master.db", master.KEYS[0])
    try:
        for spec in tracks:
            label, _, track_id = spec.rpartition("=")
            found = con.execute("SELECT FolderPath, AnalysisDataPath FROM djmdContent WHERE ID = ?",
                                (track_id,)).fetchone()
            if not label or found is None or not found[1]:
                raise Refused(f"{spec}: no analysed track with that id in the copy.")
            old, adp = Path(found[0]), found[1]
            copy = work / "music" / "Library" / FOLDER / old.name
            if copy.exists():
                raise Refused(f"{label}: two chosen tracks have the same file name.")
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(old, copy)
            rel = (source / "share" / adp.lstrip("/")).parent.relative_to(source / "share")
            shutil.copytree(source / "share" / rel, work / "rb" / "share" / rel)
            picks.append({"label": label, "id": track_id, "old": str(old), "copy": str(copy), "anlz_rel": str(rel),
                          "adp": adp})
    finally:
        con.close()
    (work / "picks.json").write_text(json.dumps(picks, indent=1), encoding="utf-8")
    print(f"Copied {len(picks)} tracks' audio and analysis files into the work folder.")
    return 0


# --- the rehearsal ---

class Checks:
    def __init__(self):
        self.items: list[dict] = []
        self.tag: str | None = None  # `rehearse-sync` reuses stage B's checks under its own step names: "step 6" -> tag

    def _name(self, name: str) -> str:
        return re.sub(r"^step \d+", self.tag, name) if self.tag else name

    def add(self, name: str, ok: bool, detail: str = "") -> bool:
        name = self._name(name)
        self.items.append({"check": name, "ok": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail else ""))
        return ok

    def note(self, name: str, detail: str) -> None:
        name = self._name(name)
        self.items.append({"check": name, "ok": None, "detail": detail})
        print(f"NOTE  {name}: {detail}")

    @property
    def failed(self) -> int:
        return sum(1 for i in self.items if i["ok"] is False)


# `offline` runs point every proxy variable at a closed port, so a request that slipped through fails instead of
# reaching a service. (A sandbox that denies network access can't be used: macOS refuses a setuid program such as
# /bin/ps inside it, and rekordbox's process check would then always answer "running".)
DEAD_PROXY = "http://127.0.0.1:9"
PROXY_VARS = ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy")


def run_cli(work: Path, tag: str, *args: str, offline: bool = False) -> tuple[int, dict, str, float]:
    """Runs `bin/discjockey <args>` with both overrides inside `work` (printed first), `offline` with every proxy
    pointing at a closed port. Returns the exit code, the JSON object on stdout ({} when there is none), stderr and
    the seconds it took. The output is kept in `work/cli-<tag>.txt`."""
    env = env_for(work)
    cmd = [str(REPO / "bin" / "discjockey"), *args]
    if offline:
        env.update({name: DEAD_PROXY for name in PROXY_VARS})
        print(f"  network: every proxy points at {DEAD_PROXY} (closed)")
    print(f"  run: {tag}: discjockey {' '.join(args)}")
    start = time.monotonic()
    r = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True)
    seconds = time.monotonic() - start
    (work / f"cli-{tag}.txt").write_text(r.stdout + "\n--- stderr ---\n" + r.stderr, encoding="utf-8")
    begin = r.stdout.find("{")
    try:
        data = json.loads(r.stdout[begin:]) if begin >= 0 else {}
    except ValueError:
        data = {}
    return r.returncode, data, r.stderr, seconds


def discjockey(work: Path, *args: str) -> tuple[int, dict]:
    code, data, _, _ = run_cli(work, f"{args[0]}-{args[1]}", *args)
    return code, data


def own_song(path: str, artist: str, title: str, info, codec: str, parked: str, now: datetime) -> dict:
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist=artist, title=title, duration_ms=round(info.duration_s * 1000), folder=FOLDER,
             path=path, status="lossless" if codec.startswith("pcm") else "not_lossless", source="manual",
             source_id=None, source_format=codec, cutoff_hz=None, rejected_sources=[], in_playlists=False,
             added=now.isoformat(timespec="seconds"),
             upgrade={"file": parked, "source": "qobuz", "source_id": "rehearsal", "source_format": "flac",
                      "found": now.date().isoformat(), "alignment": None})
    return e


def prepare(work: Path, picks: list[dict], edit_title: str | None, checks: Checks) -> dict:
    """Plan RH step 3. Returns what later steps need per label."""
    rb = work / "rb"
    shutil.copyfile(work / "source" / "master.db", rb / "master.db")
    place = Place(rb / "master.db", rb / "share", "override", None)
    with master.open_read(place, False) as m:
        entries = {p["label"]: next(e for e in m.entries_for(Path(p["old"])) if e.id == p["id"]) for p in picks}
    with write.open_write(place, dbid=None) as w:
        changes, splices = [], []
        for p in picks:
            e = entries[p["label"]]
            changes.append(write.RowChange(e.id, {"FolderPath": e.folder_path, "FileNameL": e.file_name},
                                           {"FolderPath": write.nfc(p["copy"]),
                                            "FileNameL": write.nfc(Path(p["copy"]).name)}))
            found, others = write.anlz_changes(place, e, p["copy"])
            if others:
                raise Refused(f"{p['label']}: an analysis file names another file.")
            splices += found
        w.repoint(changes, splices)
    with master.open_read(place, False) as m:
        entries = {p["label"]: next(e for e in m.entries_for(Path(p["copy"])) if e.id == p["id"]) for p in picks}
    if edit_title:
        e = entries[edit_title]
        with write.open_write(place, dbid=None) as w:
            w.repoint([write.RowChange(e.id, {"FolderPath": e.folder_path, "FileNameL": e.file_name}, {},
                                       {"title": write.TextChange("title", e.title, e.title + EDIT, False)})], [])
        with master.open_read(place, False) as m:
            entries[edit_title] = next(x for x in m.entries_for(Path(e.folder_path)) if x.id == e.id)

    paths = Paths(work / "music", support=work / "support")
    library.write_music_folder(paths.support, paths.root)
    now = datetime.now()
    first_album = next((entries[p["label"]].album for p in picks if entries[p["label"]].album), "")
    state = library.empty_state()
    info: dict[str, dict] = {}
    for n, p in enumerate(picks, 1):
        copy = Path(p["copy"])
        facts = audio.file_facts(copy)
        artist = facts.tags["artist"] or copy.stem.partition(" - ")[0]
        title = facts.tags["title"] or copy.stem.partition(" - ")[2] or copy.stem
        parked = f"Upgrades ready/{FOLDER}/{expected_stem(artist, title)}.aiff"
        target = paths.root / parked
        if target.exists():
            raise Refused(f"{p['label']}: two parked upgrades get the same name.")
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(copy), "-map", "0:a:0", "-ar", "44100",
                        "-ac", "2", "-c:a", "pcm_s16be", "-f", "aiff", str(target)], check=True)
        own_album = entries[p["label"]].album
        reuse = n == len(picks) and first_album and first_album != own_album  # an existing album row, found
        album = first_album if reuse else ALBUM
        audio.write_tags(target, title=title, artists=(artist,), album=album, isrc=f"ZZRHS26{n:05d}", label=LABEL,
                         cover=None, comment=QUALITY)
        tid = f"{OWN_PREFIX}{n}"  # an own song, as the import keys it (To-do lists those)
        rel = copy.relative_to(paths.root).as_posix()
        state["tracks"][tid] = own_song(rel, artist, title, quality.probe(copy), facts.codec, parked, now)
        info[p["label"]] = {"tid": tid, "parked": parked, "old_tags": facts.tags, "album": album,
                            "reuse_album": bool(reuse), "codec": facts.codec, "old_rel": rel,
                            "swap": facts.codec.startswith("pcm") and copy.suffix.lower() in (".aif", ".aiff")}
    with library.run_lock(paths.lock):
        library.save_state(paths, state)
        state = library.load_state(paths)
        for p in picks:
            tid = info[p["label"]]["tid"]
            a = upgrades.check(paths, state, tid)
            state["tracks"][tid]["upgrade"]["alignment"] = a.to_dict()
            info[p["label"]]["alignment"] = a.result
        library.save_state(paths, state)
    checks.add("step 3: every parked upgrade lines up (exact or shifted)",
               all(i["alignment"] in ("exact", "shifted") for i in info.values()),
               ", ".join(f"{label} {i['alignment']}" for label, i in info.items()))
    if edit_title:
        checks.add("step 3: the title edit is in the copy", entries[edit_title].title.endswith(EDIT), edit_title)
    for label, i in info.items():
        e = entries[label]
        clean = audio.file_facts(paths.root / i["parked"]).tags
        i["plan"] = {f: {"write": tc.write, "kept": tc.kept, "shown": tc.before_shown}
                     for f, tc in write.plan_text(e, i["old_tags"], clean).items()}
        i["entry_id"] = e.id
        i["comment_before"] = e.comment
    return {"place": place, "paths": paths, "info": info}


def anlz_files(work: Path, pick: dict) -> list[Path]:
    return sorted(p for p in (work / "rb" / "share" / pick["anlz_rel"]).iterdir() if p.is_file())


def outside_ppth(data: bytes) -> tuple[bytes, bytes]:
    """The bytes before and after the first PPTH tag, the file length field left out."""
    a = anlz.parse(data)
    t = a.tag("PPTH")
    head = data[:t.start]
    return head[:8] + head[12:], data[t.end:]


def check_scheme(d: dict, checks: Checks) -> None:
    """How rekordbox's own lookup rows and numbers look in the copy (the reference for the created rows)."""
    for t in LOOKUPS:
        cols, rows = d[t]["cols"], [dict(zip(d[t]["cols"], r)) for r in d[t]["rows"].values()]
        search = ("SearchStr NULL on " + str(sum(r["SearchStr"] is None for r in rows)) + "/" + str(len(rows))
                  if "SearchStr" in cols else "no SearchStr column")
        ids = [int(r["ID"]) for r in rows]
        checks.note(f"rekordbox's own {t} rows", f"{len(rows)} rows; {search}; ID text on "
                    f"{sum(isinstance(r['ID'], str) for r in rows)}; ID < 2^32 on {sum(i < 2 ** 32 for i in ids)}, "
                    f">= 2^31 on {sum(i >= 2 ** 31 for i in ids)}; lowercase UUID on "
                    f"{sum(bool(UUID.match(r['UUID'] or '')) for r in rows)}; usn NULL on "
                    f"{sum(r['usn'] is None for r in rows)}; created_at = updated_at on "
                    f"{sum(r['created_at'] == r['updated_at'] for r in rows)}")
    numbers = collections.Counter()
    shared = collections.Counter()
    for t, v in d.items():
        if "rb_local_usn" in v["cols"]:
            i = v["cols"].index("rb_local_usn")
            numbers.update((r[i], t) for r in v["rows"].values() if r[i] is not None)
    by_usn = collections.defaultdict(set)
    for (usn, t), n in numbers.items():
        by_usn[usn].add(t)
        if n > 1:
            shared[t] += 1
    count = row(d, "agentRegistry", "registry_id", "localUpdateCount")[1]["int_1"]
    checks.note("rekordbox's own numbering", f"localUpdateCount {count}, highest rb_local_usn {max(by_usn)}; "
                f"numbers shared by several rows of one table: {dict(shared) or 'none'}; numbers shared across "
                f"tables: {sum(1 for ts in by_usn.values() if len(ts) > 1)}")


def check_run(work: Path, picks: list[dict], ctx: dict, before: dict, after: dict, run: dict, window,
              checks: Checks, extra: dict | None = None) -> None:
    """Plan RH step 6. `extra` ({"cells", "usns", "stamps"}): what other steps of the same batch changed (the
    convert rehearsal's Rename item), counted in the numbering, the stamps and "nothing else changed"."""
    info, paths = ctx["info"], ctx["paths"]
    state = library.load_state(paths)
    results = {r["track"]: r for r in run.get("results", [])}
    checks.add("step 5: every track done", all(results.get(i["tid"], {}).get("state") == "done"
                                               for i in info.values()),
               ", ".join(f"{label} {results.get(i['tid'], {}).get('state')} "
                         f"{results.get(i['tid'], {}).get('reason') or ''}".strip() for label, i in info.items()))
    changes = diff(before, after)
    content_cols = before["djmdContent"]["cols"]
    expected_cells: set[tuple] = set()
    usns: list[int] = []
    stamps: list[str] = []
    created = {t: [c[4] for c in changes if c[0] == t and c[2] == "<added>"] for t in LOOKUPS}
    lengths = []
    for p in picks:
        label, i = p["label"], info[p["label"]]
        rowid, b = row(before, "djmdContent", "ID", i["entry_id"])
        a = dict(zip(content_cols, after["djmdContent"]["rows"][rowid]))
        e = state["tracks"][i["tid"]]
        new = paths.root / e["path"]
        swap = i["swap"]
        if not swap and new.suffix.lower() != ".aiff":
            checks.add(f"step 6 {label}: converted", False, f"the track still plays its {new.suffix} file")
            continue
        expect: dict[str, object] = {"FileSize": new.stat().st_size if new.exists() else None}
        if not swap:
            frames = frames_of(new) if new.exists() else 0
            expect.update(FolderPath=unicodedata.normalize("NFC", str(new)), FileNameL=new.name, FileType=12,
                          BitDepth=16, SampleRate=44100, BitRate=1411, Length=frames // 44100)
            lengths.append(f"{label} new AIFF {frames / 44100:.3f} s -> Length {a['Length']}")
            checks.add(f"step 6 {label}: points at the new AIFF, which exists",
                       new.exists() and a["FolderPath"] == expect["FolderPath"] and a["FileNameL"] == new.name
                       and new.suffix == ".aiff", f"FileNameL ends {Path(str(a['FileNameL'])).suffix}")
            facts = {k: (a[k], expect[k]) for k in ("FileType", "FileSize", "BitDepth", "SampleRate", "BitRate",
                                                    "Length")}
            checks.add(f"step 6 {label}: file facts", all(x == y for x, y in facts.values()),
                       "; ".join(f"{k} {x}" + ("" if x == y else f" (expected {y})") for k, (x, y) in facts.items()))
        else:
            checks.add(f"step 6 {label}: the AIFF swap keeps the path", a["FolderPath"] == b["FolderPath"]
                       and a["FileSize"] == expect["FileSize"], f"FileSize {b['FileSize']} -> {a['FileSize']}")
        # the text columns, per the text plan
        text_expected = {}
        for f, plan in i["plan"].items():
            col = TEXT_COLUMN[f]
            if plan["write"] is None:
                continue
            if f in LOOKUP_OF:
                hit = row(after, LOOKUP_OF[f], "ID", a[col])
                ok = hit is not None and hit[1]["Name"] == write.nfc(plan["write"])
                made = {r[0] for r in created[LOOKUP_OF[f]]}
                checks.add(f"step 6 {label}: {f} points at a row named the clean value", ok,
                           "a row this batch made" if a[col] in made else "a row that was there")
            else:
                checks.add(f"step 6 {label}: {f} written", a[col] == write.nfc(plan["write"]))
            if a[col] != b[col]:
                text_expected[col] = True
        for f, plan in i["plan"].items():
            col = TEXT_COLUMN[f]
            if plan["write"] is None:
                checks.add(f"step 6 {label}: {f} " + ("kept (the user's)" if plan["kept"] else "left as it was"),
                           a[col] == b[col])
        if i["comment_before"] and not quality.is_quality_line(i["comment_before"]):
            tag = audio.file_facts(new).tags["comment"] if new.exists() else None
            checks.add(f"step 6 {label}: the user's comment stays in Commnt and in the new file's tag",
                       a["Commnt"] == i["comment_before"] and tag == i["comment_before"],
                       f"Commnt {'same' if a['Commnt'] == i['comment_before'] else 'changed'}, tag "
                       f"{'same' if tag == i['comment_before'] else 'differs: ' + repr((tag or '')[:20])}")
        # exactly these columns changed
        allowed = {c for c in expect if expect[c] != b[c]} | set(text_expected) | {"rb_local_usn", "updated_at"}
        changed = {c[2] for c in changes if c[0] == "djmdContent" and c[1] == rowid}
        checks.add(f"step 6 {label}: exactly the expected columns changed", changed == allowed,
                   f"changed {sorted(changed)}" + ("" if changed == allowed else f", expected {sorted(allowed)}"))
        expected_cells |= {("djmdContent", rowid, c) for c in changed}
        usns.append(a["rb_local_usn"])
        stamps.append(a["updated_at"])
        # contentFile, PPTH, the other analysis bytes
        cf_rows = rows_where(before, "contentFile", "ContentID", {i["entry_id"]})
        cf_cols = before["contentFile"]["cols"]
        ok_cf, bad = 0, []
        for cf_rowid, r in cf_rows.items():
            r = dict(zip(cf_cols, r))
            ra = dict(zip(cf_cols, after["contentFile"]["rows"][cf_rowid]))
            file = work / "rb" / "share" / str(r["Path"]).lstrip("/")
            cells = {c[2] for c in changes if c[0] == "contentFile" and c[1] == cf_rowid}
            if not swap and file.suffix.upper() in SPLICED:
                md5, size = anlz.md5_size(file)
                good = ra["Hash"] == md5 and ra["Size"] == size and cells <= {"Hash", "Size", "rb_local_usn",
                                                                                "updated_at"} and "rb_local_usn" in cells
                usns.append(ra["rb_local_usn"])
                stamps.append(ra["updated_at"])
            else:
                good = not cells
            expected_cells |= {("contentFile", cf_rowid, c) for c in cells}
            ok_cf += good
            if not good:
                bad.append(file.suffix)
        checks.add(f"step 6 {label}: contentFile Hash/Size = MD5/size of the analysis files", not bad and cf_rows,
                   f"{ok_cf}/{len(cf_rows)} rows right" + (f", wrong: {bad}" if bad else ""))
        before_files = ctx["anlz_before"][label]
        ppth_ok, rest_ok, notes = True, True, []
        for f in anlz_files(work, p):
            data, old = f.read_bytes(), before_files[f.name]
            if not swap and f.suffix.upper() in SPLICED:
                got = anlz.ppth(anlz.parse(data))
                ppth_ok &= got == "?/" + write.nfc(new.name)
                rest_ok &= outside_ppth(data) == outside_ppth(old)
                notes.append(f"{f.suffix} PPTH {'new name' if got == '?/' + write.nfc(new.name) else 'WRONG'}")
            else:
                rest_ok &= data == old
                notes.append(f"{f.suffix} {'byte-equal' if data == old else 'CHANGED'}")
        checks.add(f"step 6 {label}: PPTH names the new file, every other analysis byte equal", ppth_ok and rest_ok,
                   ", ".join(notes))
        # timing: the new AIFF sits on rekordbox's timeline
        ext = anlz.read((work / "rb" / "share" / p["adp"].lstrip("/")).with_suffix(".EXT"))
        heights = None if ext is None else anlz.pwv3_heights(ext)
        if heights is not None and new.exists():
            mono, rate = quality.decode_mono(new)
            m = timing.measure(heights, mono, rate)
            decided = timing.decide(m, [0.0]) if m else None
            checks.add(f"step 6 {label}: the new AIFF's timing against rekordbox's waveform snaps to 0",
                       decided is not None and decided.offset_s == 0.0,
                       f"measured {m.offset_s * 1000:+.3f} ms, score {m.score:.3f}" if m else "no measurement")
        else:
            checks.add(f"step 6 {label}: the new AIFF's timing", False, "no waveform or no file")
        # cues, playlists, history, My Tags
        for t in RELATED:
            if t not in before:
                checks.note(f"step 6 {label}: {t}", "no such table in this library")
                continue
            rb_rows = rows_where(before, t, "ContentID", {i["entry_id"]})
            ra_rows = rows_where(after, t, "ContentID", {i["entry_id"]})
            if rb_rows or t in ("djmdCue", "djmdSongPlaylist"):
                checks.add(f"step 6 {label}: {t} rows byte-equal", rb_rows == ra_rows, f"{len(rb_rows)} rows")
    # lookup rows made, and rekordbox's scheme
    for t, rows in created.items():
        cols = after[t]["cols"]
        for r in rows:
            r = dict(zip(cols, r))
            problems = [k for k, ok in {
                "ID": isinstance(r["ID"], str) and r["ID"].isdigit() and 100 <= int(r["ID"]) < 2 ** 32,
                "UUID": bool(UUID.match(r["UUID"] or "")),
                "SearchStr": r.get("SearchStr") is None,
                "flags": all(r.get(k) == 0 for k in ("rb_data_status", "rb_local_data_status", "rb_local_deleted",
                                                      "rb_local_synced") if k in r),
                "usn": r["usn"] is None,
                "stamps": r["created_at"] == r["updated_at"] and bool(STAMP.match(str(r["created_at"]))),
                "album extras": t != "djmdAlbum" or (r["AlbumArtistID"] is None and r["ImagePath"] is None
                                                     and r["Compilation"] == 0),
            }.items() if not ok]
            checks.add(f"step 6 created {t} row in rekordbox's scheme", not problems,
                       f"ID {len(r['ID'])} digits, usn {r['rb_local_usn']}" + (f"; wrong: {problems}" if problems
                                                                               else ""))
            usns.append(r["rb_local_usn"])
            stamps.append(r["created_at"])
    reused = [label for label, i in info.items() if i["reuse_album"]]
    if reused:
        checks.add("step 6 an existing album row was reused, unchanged",
                   not any(c for c in changes if c[0] == "djmdAlbum" and c[2] != "<added>"), ", ".join(reused))
    if extra:
        expected_cells |= extra["cells"]
        usns += extra["usns"]
        stamps += extra["stamps"]
    # numbering and stamps
    count_before = row(before, "agentRegistry", "registry_id", "localUpdateCount")
    count_after = row(after, "agentRegistry", "registry_id", "localUpdateCount")[1]
    reg_cells = {c[2] for c in changes if c[0] == "agentRegistry"}
    checks.add("step 6 localUpdateCount: one number per changed or created row, consecutive, int_1 the last",
               sorted(usns) == list(range(count_before[1]["int_1"] + 1, count_after["int_1"] + 1)),
               f"{count_before[1]['int_1']} -> {count_after['int_1']} over {len(usns)} rows; agentRegistry columns "
               f"changed {sorted(reg_cells)}")
    t0, t1 = window
    in_window = all(STAMP.match(str(s)) and t0 <= str(s)[:23] <= t1 for s in stamps)
    checks.add("step 6 updated_at: 'YYYY-MM-DD HH:MM:SS.fff +00:00', UTC, during the run", in_window,
               f"{len(stamps)} stamps")
    expected_cells |= {("agentRegistry", count_before[0], c) for c in reg_cells}
    others = sorted({(c[0], c[2]) for c in changes
                     if (c[0], c[1], c[2]) not in expected_cells and not (c[0] in LOOKUPS and c[2] == "<added>")})
    checks.add("step 6 nothing else changed in any table", not others, f"{others}" if others else "")
    checks.note("step 6 Length (new rows)", "; ".join(lengths))
    ctx["created"] = created


def check_lengths(work: Path, picks: list[dict], ctx: dict, before: dict, checks: Checks) -> None:
    """Plan §0.13: rekordbox's own Length against each chosen file's duration (floor or round)."""
    lines, floor_ok, round_ok = [], 0, 0
    for p in picks:
        r = row(before, "djmdContent", "ID", p["id"])[1]
        copy = Path(p["copy"])
        seconds = frames_of(copy) / AIFF(str(copy)).info.sample_rate if copy.suffix.lower() in (".aif", ".aiff") \
            else quality.probe(copy).duration_s
        floor_ok += r["Length"] == int(seconds)
        round_ok += r["Length"] == round(seconds)
        lines.append(f"{p['label']} {seconds:.3f} s -> rekordbox {r['Length']}")
    checks.note("Length: rekordbox's own rows", f"floor matches {floor_ok}/{len(picks)}, round matches "
                f"{round_ok}/{len(picks)}; " + "; ".join(lines))
    aiffs = [p for p in picks if Path(p["copy"]).suffix.lower() in (".aif", ".aiff")]
    if aiffs:
        ok = all(row(before, "djmdContent", "ID", p["id"])[1]["Length"] == frames_of(Path(p["copy"])) // 44100
                 for p in aiffs)
        checks.add("Length = frames // 44100 on rekordbox's own AIFF rows (plan §0.13)", ok,
                   ", ".join(p["label"] for p in aiffs))


def check_backup(work: Path, picks: list[dict], ctx: dict, before_sha: str, batch: int, checks: Checks) -> None:
    folder = ctx["paths"].root / ".discjockey" / "rekordbox" / "backups"
    found = sorted(p for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []
    if not checks.add("step 6 one backup", len(found) == 1, f"{len(found)} backups"):
        return
    b = found[0]
    manifest = json.loads((b / "manifest.json").read_text(encoding="utf-8"))
    checks.add("step 6 backup master.db byte-equal to the 'before' copy", sha256(b / "master.db") == before_sha)
    # the analysis folders the batch writes (Same track for a file that isn't AIFF); an AIFF swap writes none
    spliced = [p for p in picks if not ctx["info"][p["label"]]["swap"]]
    same = all((b / "share" / p["anlz_rel"] / name).is_file()
               and sha256(b / "share" / p["anlz_rel"] / name) == hashlib.sha256(data).hexdigest()
               for p in spliced for name, data in ctx["anlz_before"][p["label"]].items())
    held = sorted(f.parent.relative_to(b / "share").as_posix() for f in (b / "share").rglob("ANLZ0000.DAT"))
    checks.add("step 6 backup holds every analysis folder the batch wrote, as it was",
               same and held == sorted(p["anlz_rel"] for p in spliced),
               f"{len(held)} folders held, {len(spliced)} written; the AIFF swaps' folders (unchanged) not held")
    after_sha = sha256(work / "rb" / "master.db")
    prop = ctx["before"]["djmdProperty"]
    dbid = next(iter(prop["rows"].values()))[prop["cols"].index("DBID")]
    want = {"dbid": dbid, "master_sha256_before": before_sha,
            "master_sha256_after": after_sha}
    wrong = [k for k, v in want.items() if manifest.get(k) != v]
    if batch not in (manifest.get("batches") or []):
        wrong.append("batches")
    checks.add("step 6 backup manifest", not wrong, f"keys {sorted(manifest)}" + (f"; wrong: {wrong}" if wrong else ""))


def check_undo(work: Path, picks: list[dict], ctx: dict, before: dict, undone: dict, music_before: dict,
               share_before: dict, code: int, result: dict, checks: Checks, own: bool = False) -> None:
    """`own`: the songs are the user's own files (Convert, Rename): no parked downloads, no upgrade waiting."""
    checks.add("step 7 batch undo ran", code == 0, f"exit {code}, ok {result.get('ok')}")
    music_now = tree(ctx["paths"].root, skip=".discjockey")
    checks.add("step 7 every audio file back, byte-identical", music_now == music_before,
               f"{len(music_before)} files before, {len(music_now)} now; differing "
               f"{len(set(music_now.items()) ^ set(music_before.items()))}")
    share_now = tree(work / "rb" / "share")
    checks.add("step 7 every analysis file back, byte-identical", share_now == share_before, f"{len(share_now)} files")
    parked = [i["parked"] for i in ctx["info"].values()]
    if not own:
        checks.add("step 7 the parked downloads are back in Upgrades ready/",
                   all(music_now.get(p) == music_before.get(p) for p in parked), f"{len(parked)} files")
    state = library.load_state(ctx["paths"])
    checks.add("step 7 the records are as before (old file" + ("" if own else ", upgrade waiting") + ")",
               all(state["tracks"][i["tid"]]["path"] == i["old_rel"]
                   and (own or state["tracks"][i["tid"]].get("upgrade")) for i in ctx["info"].values()))
    changes = diff(before, undone)
    ids = {i["entry_id"] for i in ctx["info"].values()}
    content = rows_where(before, "djmdContent", "ID", ids)
    files = rows_where(before, "contentFile", "ContentID", ids)
    allowed = set()
    for c in changes:
        t, rowid, col = c[0], c[1], c[2]
        if t == "djmdContent" and rowid in content and col in ("rb_local_usn", "updated_at"):
            allowed.add((t, col))
        elif t == "contentFile" and rowid in files and col in ("rb_local_usn", "updated_at"):
            allowed.add((t, col))
        elif t == "agentRegistry" and col == "int_1":
            allowed.add((t, col))
        elif t in LOOKUPS and col == "<added>":
            allowed.add((t, "<added>"))
    rest = sorted({(c[0], c[2]) for c in changes} - allowed)
    checks.add("step 7 master.db equal to before except the §0.8 columns", not rest,
               f"differs only in {sorted(allowed)}" + (f"; ALSO {rest}" if rest else ""))
    refs = set()
    for col in ("ArtistID", "AlbumID", "LabelID", "OrgArtistID", "RemixerID", "ComposerID", "OriginalArtistID",
                "LyricistID"):
        if col in undone["djmdContent"]["cols"]:
            i = undone["djmdContent"]["cols"].index(col)
            refs |= {r[i] for r in undone["djmdContent"]["rows"].values()}
    left = [r[0] for t, rows in ctx.get("created", {}).items() for r in rows]
    checks.add("step 7 the created lookup rows stay and no track points at them", not (set(left) & refs),
               f"{len(left)} rows")
    for t in ("djmdArtist", "djmdAlbum"):
        col = "ArtistID" if t == "djmdArtist" else "AlbumID"
        i = before["djmdContent"]["cols"].index(col)
        used = {r[i] for r in before["djmdContent"]["rows"].values()}
        if t == "djmdArtist":
            for extra in ("OrgArtistID", "RemixerID", "ComposerID", "OriginalArtistID", "LyricistID"):
                if extra in before["djmdContent"]["cols"]:
                    j = before["djmdContent"]["cols"].index(extra)
                    used |= {r[j] for r in before["djmdContent"]["rows"].values()}
            if "djmdAlbum" in before and "AlbumArtistID" in before["djmdAlbum"]["cols"]:
                j = before["djmdAlbum"]["cols"].index("AlbumArtistID")
                used |= {r[j] for r in before["djmdAlbum"]["rows"].values()}
        unused = sum(1 for r in before[t]["rows"].values() if r[0] not in used)
        checks.note(f"rekordbox's own unused {t} rows", f"{unused} of {len(before[t]['rows'])} rows no track uses")


def rehearse(work: Path, edit_title: str | None) -> int:
    work = check_work(work)
    need_marker(work)
    picks = json.loads((work / "picks.json").read_text(encoding="utf-8"))
    refuse_if_unsafe(work / "source" / "master.db")
    if edit_title and edit_title not in {p["label"] for p in picks}:
        raise Refused(f"--edit-title {edit_title}: no such track label.")
    copies = {Path(p["copy"]).name for p in picks}
    if {f.name for f in (work / "music" / "Library" / FOLDER).iterdir()} != copies:
        raise Refused("The work folder's copies are not as copy-tracks left them: start a new work folder.")
    for left in ("before", "support", "music/.discjockey", "music/Upgrades ready", "music/Superseded"):
        shutil.rmtree(work / left, ignore_errors=True)  # an earlier rehearsal that stopped before its apply
    (work / "rb" / "master.db").unlink(missing_ok=True)
    checks = Checks()
    print("Step 3: prepare the copy and the scratch library")
    ctx = prepare(work, picks, edit_title, checks)
    place, rb_db = ctx["place"], work / "rb" / "master.db"

    print("Step 4: before")
    before = dump(rb_db)
    ctx["before"] = before
    (work / "before").mkdir()
    shutil.copyfile(rb_db, work / "before" / "master.db")
    before_sha = sha256(rb_db)
    music_before = tree(ctx["paths"].root, skip=".discjockey")
    share_before = tree(work / "rb" / "share")
    ctx["anlz_before"] = {p["label"]: {f.name: f.read_bytes() for f in anlz_files(work, p)} for p in picks}
    offsets = {}
    for p in picks:
        t = offset.timeline_offset(Path(p["copy"]), place=place, running=process.running)
        offsets[p["label"]] = f"{t.samples} ({t.why})"
    checks.note("step 4 timeline offsets of the old files (44.1 kHz samples)",
                ", ".join(f"{k} {v}" for k, v in offsets.items()))
    check_scheme(before, checks)
    check_lengths(work, picks, ctx, before, checks)

    print("Step 5: upgrade apply --all --way same-track")
    t0 = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    code, run = discjockey(work, "upgrade", "apply", "--all", "--way", "same-track", "--json")
    t1 = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    checks.add("step 5 apply exit code 0", code == 0, f"exit {code}, batch {run.get('batch')}, state "
               f"{run.get('state')}, done {run.get('done')}/{run.get('total')}")
    checks.add("step 6 no -wal/-shm beside the copy after the run", not master.leftovers(rb_db))
    after = dump(rb_db)
    check_run(work, picks, ctx, before, after, run, (t0, t1), checks)
    if run.get("batch"):
        check_backup(work, picks, ctx, before_sha, run["batch"], checks)

        print(f"Step 7: batch undo {run['batch']}")
        code, result = discjockey(work, "batch", "undo", str(run["batch"]), "--json")
        checks.add("step 7 no -wal/-shm beside the copy after the undo", not master.leftovers(rb_db))
        check_undo(work, picks, ctx, before, dump(rb_db), music_before, share_before, code, result, checks)
    (work / "report.json").write_text(json.dumps(checks.items, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len([i for i in checks.items if i['ok']])} passed, {checks.failed} failed")
    return 1 if checks.failed else 0


# --- the sync's Auto-upgrade phase (plan stage C §7 RH) ---

SYNC_MARK = ".rehearse-sync-ran"  # `rehearse-sync` changes the copies (the PPTH splice): once per work folder
# Liked music is left out, with no request, while Settings' choice is off (and the scratch support folder has no
# YouTube login): an active line that reads nothing. A playlists.txt without an active line is a setup problem (exit 2).
PLAYLISTS = "Liked = https://music.youtube.com/playlist?list=LM\n"


def snapshot(work: Path, ctx: dict) -> dict:
    rb_db = work / "rb" / "master.db"
    return {"dump": dump(rb_db), "sha": sha256(rb_db), "music": tree(ctx["paths"].root, skip=".discjockey"),
            "share": tree(work / "rb" / "share")}


def same_snapshot(a: dict, b: dict) -> tuple[bool, str]:
    """Whether the audio tree (with `Superseded/` and `Upgrades ready/`), the analysis files and master.db (its bytes
    and with them every row) are equal."""
    parts = {"audio files": a["music"] == b["music"], "analysis files": a["share"] == b["share"],
             "master.db bytes": a["sha"] == b["sha"]}
    detail = f"{len(a['music'])} audio files, {len(a['share'])} analysis files; " + ", ".join(
        f"{k} {'equal' if ok else 'DIFFER'}" for k, ok in parts.items())
    if not parts["master.db bytes"]:
        detail += f"; {len(diff(a['dump'], b['dump']))} cells differ"
    return all(parts.values()), detail


def only(ctx: dict, labels: set[str]) -> dict:
    """`ctx` for a subset of the tracks (stage B's checks loop over `ctx["info"]`)."""
    return {**ctx, "info": {label: i for label, i in ctx["info"].items() if label in labels}, "created": {}}


def by_track(block: dict | None) -> dict[str, dict]:
    return {r["track"]: r for r in (block or {}).get("results", [])}


def defer_checks(paths: Paths) -> None:
    """Puts the scratch songs' next upgrade check a week ahead (the plan then holds no first check)."""
    with library.run_lock(paths.lock):
        state = library.load_state(paths)
        for e in state["tracks"].values():
            e["last_upgrade_check"] = date.today().isoformat()
        library.save_state(paths, state)


def real_sync(work: Path, tag: str) -> tuple[int, dict, str, float]:
    """A sync that changes things (`--yes --json`). Never reaches the network: a dry run first must plan no action
    (no download, no Qobuz, YouTube or SoundCloud search, no playlist read), or the rehearsal stops."""
    code, data, _, _ = run_cli(work, f"{tag}-guard", "--dry-run", "--json", offline=True)
    if code != 0 or data.get("counts"):
        raise Refused(f"{tag}: the dry run before the sync planned actions ({data.get('counts')}) or failed "
                      f"(exit {code}): no real run.")
    return run_cli(work, tag, "--yes", "--json", offline=True)


def rh1_dry(work: Path, ctx: dict, checks: Checks) -> None:
    checks.tag = "RH1"
    print("RH1: a dry run on the prepared copy plans no action")
    paths = ctx["paths"]
    lines = config.load_playlists(paths.playlists_file)
    checks.add("RH1 playlists.txt: one active line, left out before any request",
               len(lines) == 1 and all(sources.left_out(paths, line) for line in lines),
               f"{len(lines)} line, service {lines[0].service}")
    for attempt in (1, 2):
        code, data, err, _ = run_cli(work, f"rh1-dry-{attempt}", "--dry-run", "--json", offline=True)
        counts = data.get("counts") or {}
        if not counts or attempt == 2:
            break
        checks.note("RH1 first upgrade checks planned", f"{counts}: their next-check dates are set ahead")
        defer_checks(paths)
    headers = re.findall(r"^\[\d+/\d+\]", err, re.M)
    block = data.get("auto_upgrade") or {}
    checks.add("RH1 dry run: exit 0, ok, a dry run", code == 0 and data.get("ok") is True and data.get("dry_run") is True,
               f"exit {code}")
    checks.add("RH1 dry run: the action list is empty (no download, no search, no playlist read)",
               not counts and not headers and "Logging in" not in err,
               f"actions {counts or 'none'}, action lines {len(headers)}")
    checks.note("RH1 the dry run's Auto-upgrade rows", f"{block.get('done')} done, "
                f"{sum(1 for r in block.get('results', []) if r['state'] == 'would')} would")
    if counts:
        raise Refused(f"The dry run still plans actions ({counts}): stopped before any real run.")


def rh2_off(work: Path, ctx: dict, checks: Checks, state: dict) -> None:
    checks.tag = "RH2"
    print("RH2: switch off")
    code, data, _, _ = run_cli(work, "rh2-setting", "settings", "auto-upgrade", "off", "--json", offline=True)
    checks.add("RH2 settings auto-upgrade off", code == 0 and data.get("auto_upgrade") is False, f"exit {code}")
    before = snapshot(work, ctx)
    code, data, _, seconds = real_sync(work, "rh2-sync")
    state["off_seconds"] = seconds
    checks.add("RH2 sync --yes --json: exit 0, the auto_upgrade block is null",
               code == 0 and data.get("ok") is True and "auto_upgrade" in data and data["auto_upgrade"] is None,
               f"exit {code}, {seconds:.1f} s")
    ok, detail = same_snapshot(before, snapshot(work, ctx))
    checks.add("RH2 audio tree (Superseded/ and Upgrades ready/ with it), analysis files and master.db equal "
               "to before", ok, detail)
    code, data, _, _ = run_cli(work, "rh2-batches", "batch", "list", "--json", offline=True)
    checks.add("RH2 no batch row", code == 0 and data.get("count") == 0, f"{data.get('count')} batches")


def rh3_dry_on(work: Path, ctx: dict, picks: list[dict], checks: Checks) -> None:
    checks.tag = "RH3"
    print("RH3: dry run with the switch on")
    code, data, _, _ = run_cli(work, "rh3-setting", "settings", "auto-upgrade", "on", "--json", offline=True)
    checks.add("RH3 settings auto-upgrade on", code == 0 and data.get("auto_upgrade") is True, f"exit {code}")
    before = snapshot(work, ctx)
    code, data, _, _ = run_cli(work, "rh3-dry", "--dry-run", "--json", offline=True)
    block = data.get("auto_upgrade") or {}
    rows = block.get("results", [])
    would = [r for r in rows if r["state"] == "would"]
    checks.add("RH3 dry run: batch null, done 0, one would row per pick",
               code == 0 and block.get("dry_run") is True and block.get("batch") is None and block.get("done") == 0
               and len(would) == len(picks) == len(rows) and not data.get("counts"),
               f"{len(would)} would of {len(rows)} rows, {len(picks)} picks; "
               f"{sum(r['how'] == 'in_place' for r in would)} in place, {sum(r['how'] == 'new_aiff' for r in would)} "
               "new AIFF")
    ok, detail = same_snapshot(before, snapshot(work, ctx))
    checks.add("RH3 nothing changed", ok, detail)


def rh4_phase(work: Path, ctx: dict, picks: list[dict], drop: dict, checks: Checks, state: dict) -> None:
    checks.tag = "RH4"
    print("RH4: the phase")
    paths, rb_db = ctx["paths"], work / "rb" / "master.db"
    done_picks = [p for p in picks if p is not drop]
    before = snapshot(work, ctx)
    ctx["before"] = before["dump"]
    state["before"] = before
    t0 = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    code, data, err, _ = real_sync(work, "rh4-sync")
    t1 = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    block = data.get("auto_upgrade") or {}
    rows = by_track(block)
    tid = ctx["info"][drop["label"]]["tid"]
    checks.add("RH4 sync --yes --json: exit 0, ok", code == 0 and data.get("ok") is True and bool(block),
               f"exit {code}, counts {data.get('counts')}")
    checks.add("RH4 no -wal/-shm beside the copy", not master.leftovers(rb_db))
    checks.add(f"RH4 block: done {len(done_picks)}, refused 1, waiting 0, failed 0, not stopped",
               (block.get("done"), block.get("refused"), block.get("waiting"), block.get("failed"),
                block.get("stopped")) == (len(done_picks), 1, 0, 0, False),
               f"done {block.get('done')}, refused {block.get('refused')}, waiting {block.get('waiting')}, "
               f"failed {block.get('failed')}")
    checks.add("RH4 the refused track is the one without analysis, reason not_analysed",
               rows.get(tid, {}).get("state") == "refused" and rows[tid].get("reason") == "not_analysed",
               f"{drop['label']} {rows.get(tid, {}).get('state')} {rows.get(tid, {}).get('reason')}")
    if not block.get("batch"):
        raise Refused("RH4: the sync ran no batch: stopped before the later steps.")
    state["batch1"], state["backup1"] = block["batch"], block.get("backup")
    code, shown, _, _ = run_cli(work, "rh4-show", "batch", "show", str(block.get("batch")), "--json", offline=True)
    checks.add("RH4 batch show: started_by auto_upgrade, state done", shown.get("started_by") == "auto_upgrade"
               and shown.get("state") == "done", f"started_by {shown.get('started_by')}, state {shown.get('state')}, "
               f"{shown.get('total')} items")
    record = (library.load_state(paths)["tracks"][tid].get("upgrade") or {}).get("auto_refused") or {}
    state["record"] = record
    stamps = record.get("anlz")
    checks.add("RH4 the refusal is recorded with its stamps (analysis files now: none)",
               record.get("reason") == "not_analysed" and isinstance(stamps, dict) and bool(record.get("at")),
               f"reason {record.get('reason')}, {len(stamps) if isinstance(stamps, dict) else stamps} analysis files "
               "stamped")
    sub = only(ctx, {p["label"] for p in done_picks})
    check_run(work, done_picks, sub, before["dump"], dump(rb_db), block_as_run(block), (t0, t1), checks)
    check_backup(work, done_picks, sub, before["sha"], block["batch"], checks)
    ctx["created"] = sub["created"]
    report = Path(data["report"]) if data.get("report") else None
    text = report.read_text(encoding="utf-8") if report and report.is_file() else ""
    backup_line = auto_upgrade_backup_line(block.get("backup"))
    checks.add("RH4 the report has the Upgraded section and the backup line with the block's backup id",
               "Upgraded (your cues stayed)" in text and backup_line in text
               and (paths.root / ".discjockey" / "rekordbox" / "backups" / str(block.get("backup"))).is_dir(),
               f"section {'yes' if 'Upgraded (your cues stayed)' in text else 'NO'}, backup line "
               f"{'yes' if backup_line in text else 'NO'}")
    state["after4"] = snapshot(work, ctx)


def block_as_run(block: dict) -> dict:
    """`check_run` reads `results` (track, state) and nothing else of a batch's JSON."""
    return {"results": block.get("results", [])}


def auto_upgrade_backup_line(backup_id: str | None) -> str:
    from discjockey import report as rep
    return rep.UPGRADE_BACKUP.format(id=backup_id)


def rh5_repeat(work: Path, ctx: dict, drop: dict, checks: Checks, state: dict) -> None:
    checks.tag = "RH5"
    print("RH5: a second sync decodes nothing")
    paths = ctx["paths"]
    tid = ctx["info"][drop["label"]]["tid"]
    before = state["after4"]
    code, data, err, seconds = real_sync(work, "rh5-sync")
    block = data.get("auto_upgrade") or {}
    rows = by_track(block)
    checks.add("RH5 no new batch, no new backup: batch null, backup null, done 0",
               code == 0 and block.get("batch") is None and block.get("backup") is None and block.get("done") == 0
               and "Upgrading" not in err, f"batch {block.get('batch')}, done {block.get('done')}")
    checks.add("RH5 the refused one is listed as held (refused, not_analysed, the recorded words)",
               block.get("refused") == 1 and rows.get(tid, {}).get("state") == "refused"
               and rows[tid].get("reason") == "not_analysed" and rows[tid].get("message") == state["record"].get("message"),
               f"refused {block.get('refused')}")
    record = (library.load_state(paths)["tracks"][tid].get("upgrade") or {}).get("auto_refused") or {}
    checks.add("RH5 the record is the one from the first sync (not written again)", record == state["record"],
               f"at {'same' if record.get('at') == state['record'].get('at') else 'CHANGED'}")
    ok, detail = same_snapshot(before, snapshot(work, ctx))
    checks.add("RH5 audio tree, analysis files and master.db equal to after RH4", ok, detail)
    backups = sorted((paths.root / ".discjockey" / "rekordbox" / "backups").iterdir())
    checks.add("RH5 still one backup", len(backups) == 1, f"{len(backups)} backups")
    # the time the held refusal costs: the phase's own plan (one read open of the copy for the stamps), measured
    # in-process; a decode of the file would take 1-3 s
    settings = load_settings(paths.settings_file)
    place = Place(work / "rb" / "master.db", work / "rb" / "share", "override", None)
    loaded = library.load_state(paths)
    start = time.monotonic()
    planned = auto_upgrade.plan(paths, loaded, set(), settings, running=lambda: False, place=place)
    plan_ms = (time.monotonic() - start) * 1000
    checks.add("RH5 the phase's plan holds the track back without decoding it (refused, nothing to run)",
               planned is not None and not planned.run and [k for k, _ in planned.refused] == [tid],
               f"plan took {plan_ms:.0f} ms (it includes the read open for the stamps)")
    checks.note("RH5 run times", f"RH2 (switch off) {state['off_seconds']:.1f} s, RH5 {seconds:.1f} s, "
                f"difference {seconds - state['off_seconds']:+.1f} s")


def rh6_reanalysed(work: Path, ctx: dict, drop: dict, checks: Checks, state: dict) -> None:
    checks.tag = "RH6"
    print("RH6: rekordbox analysed the track again")
    paths, rb_db = ctx["paths"], work / "rb" / "master.db"
    label = drop["label"]
    tid = ctx["info"][label]["tid"]
    folder = work / "rb" / "share" / drop["anlz_rel"]
    for name, data in ctx["anlz_before"][label].items():
        (folder / name).write_bytes(data)  # a new mtime, as rekordbox writing the files again
    checks.add("RH6 the analysis files are back", sorted(p.name for p in folder.iterdir())
               == sorted(ctx["anlz_before"][label]), f"{len(ctx['anlz_before'][label])} files")
    before = snapshot(work, ctx)
    state["before6"] = before
    t0 = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    code, data, err, _ = real_sync(work, "rh6-sync")
    t1 = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    block = data.get("auto_upgrade") or {}
    row_ = by_track(block).get(tid, {})
    tried = block.get("batch") is not None and row_.get("state") in ("done", "refused", "failed")
    checks.add("RH6 the track is tried again (a batch ran, the track is done, refused or failed)", code == 0 and tried,
               f"exit {code}, batch {block.get('batch')}, {drop['label']} {row_.get('state')} {row_.get('reason') or ''}")
    after = library.load_state(paths)["tracks"][tid]
    record = (after.get("upgrade") or {}).get("auto_refused")
    if row_.get("state") == "refused":
        checks.add("RH6 the record changed (a new time, the analysis files stamped)",
                   bool(record) and record != state["record"] and bool(record.get("anlz")),
                   f"reason {record and record.get('reason')}, {len((record or {}).get('anlz') or {})} files stamped")
    elif row_.get("state") == "done":
        checks.add("RH6 the record is gone with the parked upgrade", not after.get("upgrade"), "")
        sub = only(ctx, {label})
        check_run(work, [drop], sub, before["dump"], dump(rb_db), block_as_run(block), (t0, t1), checks)
        found = sorted(p for p in (paths.root / ".discjockey" / "rekordbox" / "backups").iterdir() if p.is_dir())
        manifest = json.loads((found[0] / "manifest.json").read_text(encoding="utf-8")) if found else {}
        checks.add("RH6 the first backup is reused (master.db was as the first batch left it): still one, listing "
                   "both batches", len(found) == 1 and block.get("backup") == state["backup1"]
                   and sorted(manifest.get("batches") or []) == sorted([state["batch1"], block["batch"]]),
                   f"{len(found)} backups, batches {manifest.get('batches')}")
        state["batch2"] = block["batch"]
        state["created2"] = sub["created"]
        state["tried_done"] = True
    checks.note("RH6 outcome", f"{drop['label']} {row_.get('state')} {row_.get('reason') or ''}".strip())


def rh7_undo(work: Path, ctx: dict, picks: list[dict], drop: dict, checks: Checks, state: dict) -> None:
    checks.tag = "RH7"
    print("RH7: Undo all from this sync")
    rb_db = work / "rb" / "master.db"
    if state.get("batch2"):  # the newest batch first
        before = state["before6"]
        code, result, _, _ = run_cli(work, "rh7-undo2", "batch", "undo", str(state["batch2"]), "--json", offline=True)
        sub = only(ctx, {drop["label"]})
        sub["created"] = state["created2"]
        checks.add("RH7 no -wal/-shm beside the copy after the second batch's undo", not master.leftovers(rb_db))
        check_undo(work, [drop], sub, before["dump"], dump(rb_db), before["music"], before["share"], code, result, checks)
    block_batch = state["batch1"]
    code, result, _, _ = run_cli(work, "rh7-undo1", "batch", "undo", str(block_batch), "--json", offline=True)
    checks.add("RH7 no -wal/-shm beside the copy after the undo", not master.leftovers(rb_db))
    final = {**ctx, "created": {**ctx["created"], **{t: ctx["created"].get(t, []) + state.get("created2", {}).get(t, [])
                                                     for t in state.get("created2", {})}}}
    before = state["before"]
    # everything back as it was before RH4, plus the analysis files RH6 put back for the track that had none
    back = drop["anlz_rel"] + "/"
    share = {**before["share"], **{k: v for k, v in state["before6"]["share"].items() if k.startswith(back)}}
    check_undo(work, picks, final, before["dump"], dump(rb_db), before["music"], share, code, result, checks)


def rehearse_sync(work: Path, no_analysis: str) -> int:
    """Plan stage C §7 RH. Over the copies `copy-db` and `copy-tracks` made: a scratch library with the copies as own
    songs and a parked same-edit upgrade each, the copy of rekordbox's library repointed at the copies, a
    playlists.txt that reads nothing, and the sync (`bin/discjockey --yes --json`, every run with the proxies closed
    and a real run only after a dry run planned no action) in five states: RH1 a dry run plans no action; RH2 switch off changes nothing; RH3 dry run with
    the switch on; RH4 the phase (all but `--no-analysis`'s track, whose analysis files are removed, are upgraded;
    stage B's checks per track, the backup and the report); RH5 a second sync decodes nothing; RH6 the analysis
    files are back, the track is tried again; RH7 Undo all from this sync. Prints PASS/FAIL per check, tracks by
    label only, and writes `W/report.json`. Exit 0 when every check passes, 1 otherwise, 2 when it refuses."""
    work = check_work(work)
    need_marker(work)
    picks = json.loads((work / "picks.json").read_text(encoding="utf-8"))
    refuse_if_unsafe(work / "source" / "master.db")
    drop = next((p for p in picks if p["label"] == no_analysis), None)
    if drop is None or not no_analysis.startswith("MP3"):
        raise Refused(f"--no-analysis {no_analysis}: give the label of one of the MP3 tracks.")
    if (work / SYNC_MARK).exists():
        raise Refused("rehearse-sync ran in this work folder already (it changes the copies): start a new one.")
    copies = {Path(p["copy"]).name for p in picks}
    if {f.name for f in (work / "music" / "Library" / FOLDER).iterdir()} != copies:
        raise Refused("The work folder's copies are not as copy-tracks left them: start a new work folder.")
    for left in ("before", "support", "music/.discjockey", "music/Upgrades ready", "music/Superseded"):
        shutil.rmtree(work / left, ignore_errors=True)
    (work / "rb" / "master.db").unlink(missing_ok=True)
    (work / SYNC_MARK).write_text("rehearse-sync changed the copies in this folder\n", encoding="utf-8")
    checks = Checks()
    state: dict = {}
    checks.tag = "RH1"
    print("RH1: prepare the copy and the scratch library")
    ctx = prepare(work, picks, None, checks)
    paths = ctx["paths"]
    paths.playlists_file.write_text(PLAYLISTS, encoding="utf-8")
    ctx["anlz_before"] = {p["label"]: {f.name: f.read_bytes() for f in anlz_files(work, p)} for p in picks}
    for f in anlz_files(work, drop):
        f.unlink()
    checks.add("RH1 one MP3's analysis files removed", not anlz_files(work, drop),
               f"{drop['label']}: {len(ctx['anlz_before'][drop['label']])} files")
    try:
        rh1_dry(work, ctx, checks)
        rh2_off(work, ctx, checks, state)
        rh3_dry_on(work, ctx, picks, checks)
        rh4_phase(work, ctx, picks, drop, checks, state)
        rh5_repeat(work, ctx, drop, checks, state)
        rh6_reanalysed(work, ctx, drop, checks, state)
        rh7_undo(work, ctx, picks, drop, checks, state)
    finally:
        (work / "report.json").write_text(json.dumps(checks.items, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{len([i for i in checks.items if i['ok']])} passed, {checks.failed} failed")
    return 1 if checks.failed else 0


# --- Convert, Rename, Make all lossless files AIFF and the CDJ group's Convert all (plan stage D §7.1) ---

CONVERT_MARK = ".rehearse-convert-ran"  # `rehearse-convert` changes the copies: once per work folder
PCM = "AIFF #1"  # the pick the derived files come from; it is the "clean name only" item, under a messy name
MESSY = "pick_final_v3.aiff"
ARTIST = "Rehearsal Artist"
EDIT_LABEL = "M4A 44.1 #1"  # the pick whose title gets the user's edit
# label, file name, the plan's kind, the song's title in the scratch library, rekordbox's FileType, ffmpeg's arguments
DERIVED = (
    ("FLAC (derived)", "derived_flac.flac", "flac", "Rehearsal FLAC", 5, ("-c:a", "flac")),
    ("AIFF 24-bit 96 kHz (derived)", "derived_hires.aiff", "aiff_hires", "Rehearsal hires", 12,
     ("-ar", "96000", "-c:a", "pcm_s24be", "-write_id3v2", "1", "-f", "aiff")),
    ("AIFF 16/44.1 wrong tags (derived)", "derived_tags.aiff", "tags", "Rehearsal tags", 12,
     ("-ar", "44100", "-c:a", "pcm_s16be", "-write_id3v2", "1", "-f", "aiff")),
    ("AAC 420 kbps (derived)", "derived_aac.m4a", "aac", "Rehearsal AAC", 4, ("-c:a", "aac", "-b:a", "420k")),
)
RECORD_TITLES = {"MP3 #1": "Rehearsal MP3", "M4A 44.1 #1": "Rehearsal M4A 44", "M4A 48 #1": "Rehearsal M4A 48"}
LOSSLESS_SET = ("FLAC (derived)", "AIFF 24-bit 96 kHz (derived)", "AIFF 16/44.1 wrong tags (derived)", PCM)
CDJ_SET = ("AAC 420 kbps (derived)",)
LOSSY_SET = ("MP3 #1", "M4A 44.1 #1", "M4A 48 #1")
PCM_KIND = "name"


def pcm_of(path: Path) -> np.ndarray:
    """What ffmpeg decodes `path` to: 16-bit stereo at 44.1 kHz, shape (frames, 2)."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ar", "44100", "-ac",
                        "2", "-f", "s16le", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype="<i2").reshape(-1, 2)


def shifted(old: np.ndarray, d: int) -> np.ndarray:
    """`old` as the render puts it for rekordbox's offset `d` (44.1 kHz samples): `d > 0` delays it by `d`, `d < 0`
    trims `-d` from the start (`audio.render_aiff` with k = -d)."""
    return np.concatenate([np.zeros((d, 2), dtype=old.dtype), old]) if d >= 0 else old[-d:]


def lag_of(old: np.ndarray, new: np.ndarray, window: int = 441_000, span: int = 20_000) -> tuple[int, float]:
    """The delay of `new` against `old` in samples (new[n] ≈ old[n - lag]) and the normalised correlation at it, over
    a 10 s stretch from the middle of `new` (FFT cross-correlation, the lag searched within ±span)."""
    a = new.astype(np.float64).sum(axis=1)
    b = old.astype(np.float64).sum(axis=1)
    m = max(span, (len(a) - window) // 2)
    seg = a[m:m + window]
    ref = b[max(0, m - span):m + window + span]
    left = m - max(0, m - span)
    size = 1 << int(np.ceil(np.log2(len(ref) + len(seg))))
    corr = np.fft.irfft(np.fft.rfft(ref, size) * np.conj(np.fft.rfft(seg, size)), size)[:len(ref) - len(seg) + 1]
    j = int(np.argmax(corr))
    norm = float(np.linalg.norm(seg) * np.linalg.norm(ref[j:j + len(seg)])) or 1.0
    return left - j, float(corr[j]) / norm


def clone_rows(place: Place, work: Path, src_id: str, count: int) -> list[dict]:
    """Inserts `count` copies of rekordbox's track `src_id` (one per derived file) into the copy: the same row with a
    new ID and UUID, its own copy of the analysis files (the folder named by the new UUID) and its own contentFile
    rows. The copies keep the original's analysis. Returns each one's id, analysis folder and analysis data path."""
    out = []
    with write.open_write(place, dbid=None) as w:
        con = w.con
        cols = [c[1] for c in con.execute("PRAGMA table_info(djmdContent)")]
        src = dict(zip(cols, con.execute("SELECT * FROM djmdContent WHERE ID = ?", (src_id,)).fetchone()))
        cf_cols = [c[1] for c in con.execute("PRAGMA table_info(contentFile)")]
        src_files = [dict(zip(cf_cols, r)) for r in con.execute("SELECT * FROM contentFile WHERE ContentID = ?",
                                                                (src_id,))]
        con.execute("BEGIN IMMEDIATE")
        try:
            for _ in range(count):
                new_id, u = w._unused_id("djmdContent"), str(uuid.uuid4())
                rel = f"PIONEER/USBANLZ/{u[:3]}/{u[3:]}"
                old_rel = str(src["AnalysisDataPath"]).lstrip("/").rpartition("/")[0]
                folder = place.share / rel
                shutil.copytree(place.share / old_rel, folder)
                row = dict(src, ID=new_id, UUID=u, MasterSongID=new_id, ImagePath="",
                           AnalysisDataPath=f"/{rel}/ANLZ0000.DAT")
                con.execute(f"INSERT INTO djmdContent ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                            [row[c] for c in cols])
                for f in src_files:
                    if not (place.share / str(f["Path"]).lstrip("/")).is_file():
                        continue  # the artwork: not among the copied files
                    path = f"/{rel}/{Path(f['Path']).name}"
                    new = dict(f, ID=f"{u}_{quote(path, safe='')}", ContentID=new_id, Path=path, UUID=str(uuid.uuid4()))
                    con.execute(f"INSERT INTO contentFile ({', '.join(cf_cols)}) VALUES "
                                f"({', '.join('?' * len(cf_cols))})", [new[c] for c in cf_cols])
                out.append({"id": new_id, "anlz_rel": rel, "adp": f"/{rel}/ANLZ0000.DAT"})
            con.execute("COMMIT")
        except BaseException:
            con.execute("ROLLBACK")
            raise
    return out


def render_derived(src: Path, dst: Path, args: tuple[str, ...]) -> None:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", "0:a:0", "-map_metadata", "0",
                    *args, str(dst)], check=True)


def rb_facts(path: Path, file_type: int) -> dict:
    """What rekordbox's row says about a derived file (its own numbers: whole seconds, kbps)."""
    info = quality.probe(path)
    return {"FileType": file_type, "FileSize": path.stat().st_size, "BitDepth": info.bits or 16,
            "SampleRate": info.sample_rate, "BitRate": round((info.stream_kbps or info.kbps or 0)),
            "Length": int(info.duration_s)}


def prepare_convert(work: Path, picks: list[dict], checks: Checks) -> dict:
    """Plan §7.1 step 1. Returns what later steps need: `all` (every item's pick dict), `info` per label."""
    rb = work / "rb"
    shutil.copyfile(work / "source" / "master.db", rb / "master.db")
    place = Place(rb / "master.db", rb / "share", "override", None)
    folder = work / "music" / "Library" / FOLDER
    pcm = next(p for p in picks if p["label"] == PCM)
    messy = folder / MESSY
    Path(pcm["copy"]).rename(messy)
    pcm["copy"] = str(messy)
    with master.open_read(place, False) as m:
        entries = {p["label"]: next(e for e in m.entries_for(Path(p["old"])) if e.id == p["id"]) for p in picks}
    with write.open_write(place, dbid=None) as w:
        changes, splices = [], []
        for p in picks:
            e = entries[p["label"]]
            changes.append(write.RowChange(e.id, {"FolderPath": e.folder_path, "FileNameL": e.file_name},
                                           {"FolderPath": write.nfc(p["copy"]),
                                            "FileNameL": write.nfc(Path(p["copy"]).name)}))
            found, others = write.anlz_changes(place, e, p["copy"])
            if others:
                raise Refused(f"{p['label']}: an analysis file names another file.")
            splices += found
        w.repoint(changes, splices)
    # the derived files, each from the PCM pick, and a copy of the PCM pick's rekordbox row for each
    derived = []
    for label, name, kind, title, file_type, args in DERIVED:
        render_derived(messy, folder / name, args)
        derived.append({"label": label, "copy": str(folder / name), "kind": kind, "title": title,
                        "file_type": file_type})
    made = clone_rows(place, work, pcm["id"], len(derived))
    for d, c in zip(derived, made):
        d.update(c, old=str(messy))
    with master.open_read(place, False) as m:
        at_messy = {e.id: e for e in m.entries_for(messy)}
    with write.open_write(place, dbid=None) as w:
        changes, splices = [], []
        for d in derived:
            e = at_messy[d["id"]]
            after = {"FolderPath": write.nfc(d["copy"]), "FileNameL": write.nfc(Path(d["copy"]).name),
                     **rb_facts(Path(d["copy"]), d["file_type"])}
            changes.append(write.RowChange(e.id, {"FolderPath": e.folder_path, "FileNameL": e.file_name}, after))
            found, others = write.anlz_changes(place, e, d["copy"])
            if others:
                raise Refused(f"{d['label']}: an analysis file names another file.")
            splices += found
        w.repoint(changes, splices)
    everything = picks + derived
    with master.open_read(place, False) as m:
        entries = {p["label"]: next(e for e in m.entries_for(Path(p["copy"])) if e.id == p["id"])
                   for p in everything}
    edit = entries[EDIT_LABEL]
    with write.open_write(place, dbid=None) as w:
        w.repoint([write.RowChange(edit.id, {"FolderPath": edit.folder_path, "FileNameL": edit.file_name}, {},
                                   {"title": write.TextChange("title", edit.title, edit.title + EDIT, False)})], [])
    with master.open_read(place, False) as m:
        entries[EDIT_LABEL] = next(x for x in m.entries_for(Path(edit.folder_path)) if x.id == edit.id)
    checks.add("RH1 the user's title edit is in the copy", entries[EDIT_LABEL].title.endswith(EDIT), EDIT_LABEL)

    paths = Paths(work / "music", support=work / "support")
    library.write_music_folder(paths.support, paths.root)
    now = datetime.now()
    state = library.empty_state()
    info: dict[str, dict] = {}
    (work / "pcm-old").mkdir(exist_ok=True)
    for n, p in enumerate(everything, 1):
        copy = Path(p["copy"])
        facts = audio.file_facts(copy)
        if p["label"] == PCM:  # tags clean already: only its name is wrong
            artist = facts.tags["artist"] or ARTIST
            title = facts.tags["title"] or "Rehearsal name"
        else:
            artist, title = ARTIST, p.get("title") or RECORD_TITLES[p["label"]]
        tid = f"{OWN_PREFIX}{n}"
        rel = copy.relative_to(paths.root).as_posix()
        e = own_song(rel, artist, title, quality.probe(copy), facts.codec, "", now)
        e["upgrade"] = None
        e["status"] = "lossless" if quality.is_lossless_codec(facts.codec) else "not_lossless"
        state["tracks"][tid] = e
        t = offset.timeline_offset(copy, place=place, running=process.running)
        np.save(work / "pcm-old" / f"{n}.npy", pcm_of(copy))
        info[p["label"]] = {"tid": tid, "old_rel": rel, "old_tags": facts.tags, "codec": facts.codec,
                            "artist": artist, "title": title, "entry": entries[p["label"]], "entry_id": p["id"],
                            "comment_before": entries[p["label"]].comment, "swap": False, "reuse_album": False,
                            "parked": "", "d": t.samples, "why": t.why, "sha_before": sha256(copy), "n": n}
    with library.run_lock(paths.lock):
        library.save_state(paths, state)
    checks.add("RH1 the scratch library holds every file as an own song, no parked upgrade",
               len(info) == len(everything) == len(library.load_state(paths)["tracks"])
               and not any(e.get("upgrade") for e in library.load_state(paths)["tracks"].values()),
               f"{len(info)} songs: " + ", ".join(info))
    checks.add("RH1 every derived file is the kind it was made as and every row points at its file",
               all(entries[d["label"]].folder_path == write.nfc(d["copy"]) for d in derived),
               ", ".join(f"{d['label']} {audio.file_facts(Path(d['copy'])).codec}" for d in derived))
    checks.note("RH1 rekordbox's offset d per file before the run (44.1 kHz samples)",
                ", ".join(f"{label} {i['d']} ({i['why']})" for label, i in info.items()))
    return {"place": place, "paths": paths, "info": info, "all": everything}


def cli(work: Path, tag: str, *args: str) -> tuple[int, dict, str]:
    """A Discjockey command of the convert rehearsal: no network, `--json`. Returns exit code, JSON, stderr."""
    code, data, err, _ = run_cli(work, tag, *args, "--json", offline=True)
    return code, data, err


def convert_snapshot(work: Path, ctx: dict) -> dict:
    s = snapshot(work, ctx)
    s["state"] = tree(ctx["paths"].root / ".discjockey")
    return s


def same_convert_snapshot(a: dict, b: dict) -> tuple[bool, str]:
    ok, detail = same_snapshot(a, b)
    changed = sorted(k for k in a["state"].keys() | b["state"].keys() if a["state"].get(k) != b["state"].get(k))
    return ok and not changed, detail + f"; {len(a['state'])} files in .discjockey/, differing {changed or 'none'}"


def kinds_of(plan: dict) -> dict[str, int]:
    return {k["kind"]: k["n"] for k in plan.get("kinds", [])}


def rh2_dry(work: Path, ctx: dict, checks: Checks, view: str) -> dict:
    checks.tag = "RH2"
    print("RH2: dry runs")
    # the first dry run fills the files' stored facts (it only reads the files, and writes library.db once)
    code, data, err = cli(work, "rh2-warm", "convert", "--all", "lossless", "--in", view, "--dry-run")
    checks.add("RH2 a first dry run fills the stored facts (exit 0, ok, a dry run)",
               code == 0 and data.get("ok") is True and data.get("dry_run") is True,
               f"exit {code}; reading lines on stderr: {len(re.findall('Reading what your files are', err))}")
    before = convert_snapshot(work, ctx)
    want = {"flac": 1, "aiff_hires": 1, "tags": 1, PCM_KIND: 1}
    code, data, err = cli(work, "rh2-lossless", "convert", "--all", "lossless", "--in", view, "--dry-run")
    plan = data.get("plan") or {}
    checks.add("RH2 Make all dry run: the kinds equal the made picks (flac 1, aiff_hires 1, tags 1, name 1)",
               code == 0 and kinds_of(plan) == want and plan.get("total") == 4 and plan.get("lossy") == 0,
               f"kinds {kinds_of(plan)}, total {plan.get('total')}, lossy {plan.get('lossy')}, skipped "
               f"{len(plan.get('skipped', []))}, waiting {len(plan.get('waiting', []))}")
    checks.add("RH2 Make all dry run: the actions are convert x3 and rename x1; no lossy file in it",
               sorted(i["action"] for i in plan.get("items", [])) == ["convert", "convert", "convert", "rename"],
               f"{[i['action'] for i in plan.get('items', [])]}")
    ok, detail = same_convert_snapshot(before, convert_snapshot(work, ctx))
    checks.add("RH2 Make all dry run changed nothing (tree, library.db, master.db bytes and rows)", ok, detail)
    code, data, err = cli(work, "rh2-cdj", "convert", "--all", "cdj", "--dry-run")
    plan_cdj = data.get("plan") or {}
    checks.add("RH2 CDJ dry run: the AAC only", code == 0 and kinds_of(plan_cdj) == {"aac": 1}
               and plan_cdj.get("total") == 1, f"kinds {kinds_of(plan_cdj)}, total {plan_cdj.get('total')}")
    ok, detail = same_convert_snapshot(before, convert_snapshot(work, ctx))
    checks.add("RH2 CDJ dry run changed nothing", ok, detail)
    return {"lossless": plan, "cdj": plan_cdj}


def results_of(run: dict) -> dict[str, dict]:
    return {r["track"]: r for r in run.get("results", [])}


def sub_ctx(ctx: dict, labels: set[str]) -> dict:
    return only(ctx, labels)


def pick_of(ctx: dict, label: str) -> dict:
    return next(p for p in ctx["all"] if p["label"] == label)


def fill_plans(ctx: dict, labels: set[str], checks: Checks) -> None:
    """After a run: the text plan of each converted file's row (its old tags against the new file's tags, the
    engine's rule for the user's edit) and the new tags against `eligible.expected_tags`."""
    paths = ctx["paths"]
    state = library.load_state(paths)
    for label in sorted(labels):
        i = ctx["info"][label]
        e = state["tracks"][i["tid"]]
        new = paths.root / e["path"]
        clean = audio.file_facts(new).tags
        i["plan"] = {f: {"write": tc.write, "kept": tc.kept, "shown": tc.before_shown}
                     for f, tc in write.plan_text(i["entry"], i["old_tags"], clean).items()}
        expected = eligible.expected_tags(e, i["old_tags"])
        norm = lambda v: unicodedata.normalize("NFC", (v or "").strip())  # noqa: E731
        wrong = [f for f in ("title", "artist", "album") if norm(clean.get(f)) != norm(expected[f])]
        checks.add(f"step 6 {label}: the new file's title, artist and album are the song record's",
                   not wrong, f"{wrong or 'all three equal'}")


def check_samples(ctx: dict, label: str, exact: bool, checks: Checks) -> None:
    """The new AIFF against ffmpeg's decode of the old file (saved before the run), shifted by the engine's `d`."""
    i = ctx["info"][label]
    paths = ctx["paths"]
    new_file = paths.root / library.load_state(paths)["tracks"][i["tid"]]["path"]
    old = np.load(ctx["work"] / "pcm-old" / f"{i['n']}.npy")
    new = pcm_of(new_file)
    d = int(i["d"] or 0)
    if exact:
        want = shifted(old, d)
        same = want.shape == new.shape and bool(np.array_equal(want, new))
        checks.add(f"step 6 {label}: the samples equal the old file's, shifted by d = {d}", same,
                   f"{len(new)} frames, old {len(old)}" + ("" if same else f"; differing samples "
                   f"{int((want[:len(new)] != new[:len(want)]).sum()) if want.shape == new.shape else 'length differs'}"))
        return
    lag, score = lag_of(old, new)
    checks.add(f"step 6 {label}: the render matches the old file's decode shifted by d = {d} "
               "(cross-correlation, within 1 sample)", abs(lag - d) <= 1 and score > 0.99,
               f"measured lag {lag} samples, correlation {score:.4f}, {len(new)} frames, old {len(old)}")


def check_format(ctx: dict, label: str, checks: Checks) -> None:
    i = ctx["info"][label]
    paths = ctx["paths"]
    new_file = paths.root / library.load_state(paths)["tracks"][i["tid"]]["path"]
    facts = audio.file_facts(new_file)
    checks.add(f"step 6 {label}: the new file is a 16-bit 44.1 kHz AIFF",
               new_file.suffix.lower() == ".aiff" and facts.codec == "pcm_s16be",
               f"{facts.codec}, {new_file.suffix}, {quality.probe(new_file).sample_rate} Hz, "
               f"{quality.probe(new_file).bits} bit")


def check_rename(work: Path, ctx: dict, label: str, before: dict, after: dict, run: dict, window,
                 checks: Checks) -> dict:
    """§7.1 step 3: the renamed item changed only its path columns, PPTH and contentFile, and its bytes are the
    file's. Returns the cells, numbers and stamps it used (for check_run's numbering and "nothing else")."""
    i, paths, p = ctx["info"][label], ctx["paths"], pick_of(ctx, label)
    state = library.load_state(paths)
    e = state["tracks"][i["tid"]]
    new = paths.root / e["path"]
    result = results_of(run).get(i["tid"], {})
    checks.add(f"step 6 {label}: renamed", result.get("state") == "done" and result.get("action") == "rename",
               f"{result.get('action')} {result.get('state')} {result.get('reason') or ''}".strip())
    want_name = expected_stem(i["artist"], i["title"]) + ".aiff"
    checks.add(f"step 6 {label}: the new name is the clean one, in the same folder",
               new.name == write.nfc(want_name) and new.parent == (paths.root / i["old_rel"]).parent,
               f"clean name {'yes' if new.name == write.nfc(want_name) else 'NO'}")
    checks.add(f"step 6 {label}: the file's bytes are the file's (SHA-256 equal), the old name is gone, nothing "
               "of it in Superseded/", new.is_file() and sha256(new) == i["sha_before"]
               and not (paths.root / i["old_rel"]).exists()
               and i["sha_before"] not in set(tree(paths.root / "Superseded").values()),
               f"{new.stat().st_size if new.is_file() else 0} bytes")
    changes = diff(before, after)
    rowid, b = row(before, "djmdContent", "ID", i["entry_id"])
    a = dict(zip(before["djmdContent"]["cols"], after["djmdContent"]["rows"][rowid]))
    changed = {c[2] for c in changes if c[0] == "djmdContent" and c[1] == rowid}
    must = {"FolderPath", "FileNameL", "rb_local_usn", "updated_at"}
    checks.add(f"step 6 {label}: whole row: only the path columns, rb_local_usn and updated_at changed",
               must <= changed <= must | {"OrgFolderPath", "rb_LocalFolderPath"}
               and a["FolderPath"] == unicodedata.normalize("NFC", str(new)) and a["FileNameL"] == new.name,
               f"changed {sorted(changed)}")
    cells = {("djmdContent", rowid, c) for c in changed}
    usns, stamps = [a["rb_local_usn"]], [a["updated_at"]]
    cf_cols = before["contentFile"]["cols"]
    ok_cf, bad = 0, []
    cf_rows = rows_where(before, "contentFile", "ContentID", {i["entry_id"]})
    for cf_rowid, r in cf_rows.items():
        r = dict(zip(cf_cols, r))
        ra = dict(zip(cf_cols, after["contentFile"]["rows"][cf_rowid]))
        file = work / "rb" / "share" / str(r["Path"]).lstrip("/")
        got = {c[2] for c in changes if c[0] == "contentFile" and c[1] == cf_rowid}
        if file.suffix.upper() in SPLICED:
            md5, size = anlz.md5_size(file)
            good = ra["Hash"] == md5 and ra["Size"] == size and got <= {"Hash", "Size", "rb_local_usn", "updated_at"} \
                and "rb_local_usn" in got
            usns.append(ra["rb_local_usn"])
            stamps.append(ra["updated_at"])
        else:
            good = not got
        cells |= {("contentFile", cf_rowid, c) for c in got}
        ok_cf += good
        if not good:
            bad.append(file.suffix)
    checks.add(f"step 6 {label}: contentFile Hash/Size = MD5/size of the analysis files, the others untouched",
               bool(cf_rows) and not bad, f"{ok_cf}/{len(cf_rows)} rows right" + (f", wrong: {bad}" if bad else ""))
    ppth_ok, rest_ok, notes = True, True, []
    for f in anlz_files(work, p):
        data, old = f.read_bytes(), ctx["anlz_before"][label][f.name]
        if f.suffix.upper() in SPLICED:
            got = anlz.ppth(anlz.parse(data))
            ppth_ok &= got == "?/" + write.nfc(new.name)
            rest_ok &= outside_ppth(data) == outside_ppth(old)
            notes.append(f"{f.suffix} PPTH {'new name' if got == '?/' + write.nfc(new.name) else 'WRONG'}")
        else:
            rest_ok &= data == old
            notes.append(f"{f.suffix} {'byte-equal' if data == old else 'CHANGED'}")
    checks.add(f"step 6 {label}: PPTH names the new file, every other analysis byte equal", ppth_ok and rest_ok,
               ", ".join(notes))
    for t in RELATED:
        if t in before and (t in ("djmdCue", "djmdSongPlaylist") or rows_where(before, t, "ContentID",
                                                                              {i["entry_id"]})):
            same = rows_where(before, t, "ContentID", {i["entry_id"]}) == rows_where(after, t, "ContentID",
                                                                                      {i["entry_id"]})
            checks.add(f"step 6 {label}: {t} rows byte-equal", same, "")
    return {"cells": cells, "usns": usns, "stamps": stamps}


def check_batch(work: Path, ctx: dict, tag: str, run: dict, code: int, started_by: str, kind: str, labels: set[str],
                checks: Checks) -> None:
    checks.add(f"{tag} run: exit 0, ok, every item done, none skipped or failed",
               code == 0 and run.get("ok") is True and run.get("done") == len(labels) == run.get("total")
               and not run.get("skipped") and not run.get("failed"),
               f"exit {code}, batch {run.get('batch')}, state {run.get('state')}, done {run.get('done')}/"
               f"{run.get('total')}, skipped {run.get('skipped')}, failed {run.get('failed')}")
    code, shown, _ = cli(work, f"{tag.lower()}-show", "batch", "show", str(run.get("batch")))
    checks.add(f"{tag} batch show: started_by {started_by}, kind {kind}, state done",
               shown.get("started_by") == started_by and shown.get("kind") == kind and shown.get("state") == "done",
               f"started_by {shown.get('started_by')}, kind {shown.get('kind')}, state {shown.get('state')}, "
               f"{shown.get('total')} items")


def check_backups_for(work: Path, ctx: dict, tag: str, run: dict, picks: list[dict], before: dict,
                      checks: Checks, state_: dict) -> None:
    """The batch's backup: master.db is the 'before' copy of this batch or of the first (a backup is reused while
    master.db is as the earlier batch left it), every analysis folder this batch wrote is held as it was, the
    manifest lists the batch."""
    folder = ctx["paths"].root / ".discjockey" / "rekordbox" / "backups"
    found = sorted(p for p in folder.iterdir() if p.is_dir()) if folder.is_dir() else []
    backup = folder / str(run.get("backup"))
    if not checks.add(f"{tag} the batch's backup exists", backup.is_dir(), f"backup {run.get('backup')} of "
                      f"{len(found)}"):
        return
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    reused = state_.get("first") == run.get("backup")
    wanted = state_["first_sha"] if reused else before["sha"]
    if not reused and "first" not in state_:
        state_["first"], state_["first_sha"] = run.get("backup"), before["sha"]
    checks.add(f"{tag} backup master.db byte-equal to the " + ("first batch's 'before' copy (the backup is reused)"
                                                               if reused else "'before' copy"),
               sha256(backup / "master.db") == wanted, f"{'reused' if reused else 'new'} backup, {len(found)} in all")
    held_ok = all((backup / "share" / p["anlz_rel"] / name).is_file()
                  and sha256(backup / "share" / p["anlz_rel"] / name) == hashlib.sha256(data).hexdigest()
                  for p in picks for name, data in ctx["anlz_before"][p["label"]].items())
    checks.add(f"{tag} backup holds every analysis folder the batch wrote, as it was", held_ok,
               f"{len(picks)} folders")
    checks.add(f"{tag} backup manifest lists the batch", run.get("batch") in (manifest.get("batches") or []),
               f"batches {manifest.get('batches')}")


KEPT_KEYS = ("status", "source", "source_id", "source_format", "source_kbps", "cutoff_hz", "artist", "title")


def check_records(ctx: dict, tag: str, labels: set[str], rename_label: str | None, was: dict, batch: int,
                  checks: Checks) -> None:
    """Plan §1.2 step 7: the song records after the batch: `path` the new file, quality fields unchanged, the new file's
    facts and `placed_by = 'app'` (Convert), the rekordbox check `converted` / `renamed` with this batch."""
    state = library.load_state(ctx["paths"])
    problems, notes = [], []
    for label in sorted(labels):
        i = ctx["info"][label]
        e, old = state["tracks"][i["tid"]], was[label]
        renamed = label == rename_label
        if any(e.get(k) != old.get(k) for k in KEPT_KEYS):
            problems.append(f"{label}: {[k for k in KEPT_KEYS if e.get(k) != old.get(k)]} changed")
        found = quality.file_audio(quality.probe(ctx["paths"].root / e["path"]))  # what a scan would store
        if not renamed and ((e.get("file_codec"), e.get("file_rate"), e.get("file_bits"), e.get("file_kbps"))
                            != (found.codec, found.rate, found.bits, found.kbps) or found.codec != "pcm_s16be"
                            or e.get("placed_by") != "app"):
            problems.append(f"{label}: facts {(e.get('file_codec'), e.get('file_rate'), e.get('file_bits'), e.get('file_kbps'), e.get('placed_by'))}")
        if renamed and any(e.get(k) != old.get(k) for k in ("file_codec", "file_rate", "file_bits", "file_kbps")):
            problems.append(f"{label}: the rename changed the file's facts")
        check = e.get("rekordbox_check") or {}
        if check.get("reason") != ("renamed" if renamed else "converted") or check.get("batch") != batch:
            problems.append(f"{label}: check {check.get('reason')} batch {check.get('batch')}")
        notes.append(f"{label} check {check.get('reason')}")
    checks.add(f"{tag} the song records: quality fields kept, the new file's facts, the rekordbox check of this "
               "batch", not problems, "; ".join(problems) if problems else ", ".join(notes))


def run_batch(work: Path, ctx: dict, tag: str, args: tuple[str, ...], started_by: str, kind: str, labels: set[str],
              checks: Checks, state: dict, rename_label: str | None = None) -> dict:
    """One batch of the rehearsal: the run, stage B's checks per item, the backup; returns the pieces undo needs."""
    checks.tag = tag
    print(f"{tag}: {' '.join(args)}")
    rb_db, paths = work / "rb" / "master.db", ctx["paths"]
    before = convert_snapshot(work, ctx)
    ctx["before"] = before["dump"]
    ctx["work"] = work
    was = {label: dict(library.load_state(paths)["tracks"][ctx["info"][label]["tid"]]) for label in labels}
    t0 = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    code, run, err = cli(work, f"{tag.lower()}-run", *args)
    t1 = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")[:23]
    check_batch(work, ctx, tag, run, code, started_by, kind, labels, checks)
    if not run.get("batch"):
        raise Refused(f"{tag}: no batch ran ({run.get('reason') or code}): stopped before the later steps.")
    checks.add(f"{tag} no -wal/-shm beside the copy after the run", not master.leftovers(rb_db))
    check_records(ctx, tag, labels, rename_label, was, run["batch"], checks)
    after = dump(rb_db)
    converts = {label for label in labels if label != rename_label}
    fill_plans(ctx, converts, checks)
    picks = [pick_of(ctx, label) for label in sorted(converts)]
    sub = only(ctx, converts)
    extra = None
    if rename_label:
        extra = check_rename(work, ctx, rename_label, before["dump"], after, run, (t0, t1), checks)
    check_run(work, picks, sub, before["dump"], after, run, (t0, t1), checks, extra)
    done = results_of(run)
    for label in sorted(converts):
        i = ctx["info"][label]
        res = done.get(i["tid"], {})
        checks.add(f"{tag} {label}: a convert item", res.get("action") == "convert", f"{res.get('action')}")
    for label in sorted(converts):
        check_format(ctx, label, checks)
    walk = [pick_of(ctx, label) for label in sorted(labels)]
    check_backups_for(work, ctx, tag, run, walk, before, checks, state)
    state[f"{tag}-new"] = {label: sha256(paths.root / library.load_state(paths)["tracks"][ctx["info"][label]["tid"]]
                                         ["path"]) for label in converts}
    return {"before": before, "run": run, "labels": labels, "created": sub["created"], "tag": tag, "was": was}


def rh3_make_all(work: Path, ctx: dict, view: str, checks: Checks, state: dict) -> dict:
    labels = set(LOSSLESS_SET)
    out = run_batch(work, ctx, "RH3", ("convert", "--all", "lossless", "--in", view), "make_aiff", "convert",
                    labels, checks, state, rename_label=PCM)
    fl, hi, tg = (ctx["info"][x] for x in LOSSLESS_SET[:3])
    check_samples(ctx, LOSSLESS_SET[0], True, checks)
    check_samples(ctx, LOSSLESS_SET[1], False, checks)
    check_samples(ctx, LOSSLESS_SET[2], True, checks)
    paths = ctx["paths"]
    new = paths.root / library.load_state(paths)["tracks"][hi["tid"]]["path"]
    probe = quality.probe(new)
    checks.add("RH3 the 24-bit 96 kHz AIFF became 16-bit 44.1 kHz", probe.bits == 16 and probe.sample_rate == 44100,
               f"{probe.bits} bit, {probe.sample_rate} Hz (before: 24 bit, 96000 Hz)")
    return out


def rh4_cdj(work: Path, ctx: dict, checks: Checks, state: dict) -> dict:
    labels = set(CDJ_SET)
    out = run_batch(work, ctx, "RH4", ("convert", "--all", "cdj"), "cdj_all", "convert", labels, checks, state)
    i = ctx["info"][CDJ_SET[0]]
    checks.add("RH4 the AAC's offset d was 0", i["d"] == 0, f"d {i['d']} ({i['why']})")
    check_samples(ctx, CDJ_SET[0], False, checks)
    paths = ctx["paths"]
    after = dump(work / "rb" / "master.db")
    r = row(after, "djmdContent", "ID", i["entry_id"])[1]
    checks.add("RH4 the AAC's row is a 16-bit 44.1 kHz AIFF", (r["FileType"], r["BitDepth"], r["SampleRate"],
                                                                r["BitRate"]) == (12, 16, 44100, 1411),
               f"FileType {r['FileType']}, {r['BitDepth']} bit, {r['SampleRate']} Hz, BitRate {r['BitRate']}")
    return out


def rh5_lossy(work: Path, ctx: dict, checks: Checks, state: dict) -> dict:
    labels = set(LOSSY_SET)
    names = tuple(ctx["info"][label]["tid"] for label in LOSSY_SET)
    out = run_batch(work, ctx, "RH5", ("convert", *names), "user", "convert", labels, checks, state)
    for label in LOSSY_SET:
        check_samples(ctx, label, False, checks)
    return out


def rh6_undo(work: Path, ctx: dict, batches: list[dict], checks: Checks, state: dict) -> None:
    checks.tag = "RH6"
    print("RH6: batch undo, newest first")
    rb_db, paths = work / "rb" / "master.db", ctx["paths"]
    for b in reversed(batches):
        run, before = b["run"], b["before"]
        news = state[f"{b['tag']}-new"]
        code, result, _ = cli(work, f"rh6-undo-{b['tag'].lower()}", "batch", "undo", str(run["batch"]))
        checks.add(f"RH6 {b['tag']}: no -wal/-shm beside the copy after the undo", not master.leftovers(rb_db))
        sub = only(ctx, b["labels"])
        sub["created"] = b["created"]
        check_undo(work, [pick_of(ctx, x) for x in sorted(b["labels"])], sub, before["dump"], dump(rb_db),
                   before["music"], before["share"], code, result, checks, own=True)
        state_now = library.load_state(paths)
        changed = {}
        for label in sorted(b["labels"]):  # a key a record never had reads as None (the scratch records are made by hand)
            a, z = b["was"][label], state_now["tracks"][ctx["info"][label]["tid"]]
            if any(a.get(k) != z.get(k) for k in a.keys() | z.keys()):
                changed[label] = sorted(k for k in a.keys() | z.keys() if a.get(k) != z.get(k))
        checks.add(f"RH6 {b['tag']}: every song record is exactly as before the batch (path, facts, check)",
                   not changed, f"{changed or 'all ' + str(len(b['labels'])) + ' equal'}")
        kept = {sha256(f) for f in (paths.root / ".discjockey" / "undo").rglob("*") if f.is_file()} \
            if (paths.root / ".discjockey" / "undo").is_dir() else set()
        checks.add(f"RH6 {b['tag']}: the renders are in .discjockey/undo/", set(news.values()) <= kept,
                   f"{len(set(news.values()) & kept)}/{len(news)} renders found")


def rehearse_convert(work: Path) -> int:
    """Plan stage D §7.1. Over the copies `copy-db` and `copy-tracks` made (one MP3, one M4A 44.1 kHz, one M4A 48 kHz,
    one AIFF): the PCM pick under a messy name and four files derived from it (a FLAC, a 24-bit 96 kHz AIFF, a 16/44.1
    AIFF with wrong tags, an AAC at 420 kbps), each derived file with its own copy of the PCM pick's rekordbox row and
    analysis; a scratch Discjockey library with all eight as own songs. Then RH2 dry runs, RH3 Make all lossless files
    AIFF, RH4 the CDJ group's Convert all, RH5 Convert by name for the three lossy picks, RH6 `batch undo` for each
    batch, newest first. Prints PASS/FAIL per check, tracks by label only, writes `W/report.json`. Exit 0 when every
    check passes, 1 otherwise, 2 when it refuses."""
    work = check_work(work)
    need_marker(work)
    picks = json.loads((work / "picks.json").read_text(encoding="utf-8"))
    refuse_if_unsafe(work / "source" / "master.db")
    if sorted(p["label"] for p in picks) != sorted([PCM, *LOSSY_SET]):
        raise Refused(f"rehearse-convert needs exactly these picks: {', '.join([PCM, *LOSSY_SET])}.")
    if (work / CONVERT_MARK).exists():
        raise Refused("rehearse-convert ran in this work folder already (it changes the copies): start a new one.")
    copies = {Path(p["copy"]).name for p in picks}
    if {f.name for f in (work / "music" / "Library" / FOLDER).iterdir()} != copies:
        raise Refused("The work folder's copies are not as copy-tracks left them: start a new work folder.")
    for left in ("before", "support", "music/.discjockey", "music/Upgrades ready", "music/Superseded", "pcm-old"):
        shutil.rmtree(work / left, ignore_errors=True)
    (work / "rb" / "master.db").unlink(missing_ok=True)
    (work / CONVERT_MARK).write_text("rehearse-convert changed the copies in this folder\n", encoding="utf-8")
    checks = Checks()
    state: dict = {}
    checks.tag = "RH1"
    print("RH1: prepare the copy and the scratch library")
    ctx = prepare_convert(work, picks, checks)
    ctx["work"] = work
    ctx["anlz_before"] = {p["label"]: {f.name: f.read_bytes() for f in anlz_files(work, p)} for p in ctx["all"]}
    view = f"folder:Library/{FOLDER}"  # a Library folder's key is relative to the music folder
    batches = []
    try:
        rh2_dry(work, ctx, checks, view)
        batches.append(rh3_make_all(work, ctx, view, checks, state))
        batches.append(rh4_cdj(work, ctx, checks, state))
        batches.append(rh5_lossy(work, ctx, checks, state))
        rh6_undo(work, ctx, batches, checks, state)
    finally:
        (work / "report.json").write_text(json.dumps(checks.items, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"{len([i for i in checks.items if i['ok']])} passed, {checks.failed} failed")
    return 1 if checks.failed else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Rehearse Same track on a copy of a rekordbox library.")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("copy-db", "copy-tracks"):
        s = sub.add_parser(name)
        s.add_argument("--source", type=Path, required=True, help="the folder holding master.db and share/")
        s.add_argument("--work", type=Path, required=True, help="a new folder outside the repo")
        if name == "copy-tracks":
            s.add_argument("--track", action="append", required=True, help='"LABEL=ID", e.g. "MP3 #1=12345"')
    sub.add_parser("candidates").add_argument("--work", type=Path, required=True)
    s = sub.add_parser("rehearse")
    s.add_argument("--work", type=Path, required=True)
    s.add_argument("--edit-title", default=None, help="the label of the track whose title gets a user edit")
    s = sub.add_parser("rehearse-sync")
    s.add_argument("--work", type=Path, required=True)
    s.add_argument("--no-analysis", required=True, help="the label of the MP3 track whose analysis files are removed")
    sub.add_parser("rehearse-convert").add_argument("--work", type=Path, required=True)
    args = p.parse_args(argv)
    try:
        if args.command == "rehearse-convert":
            return rehearse_convert(args.work)
        if args.command == "rehearse-sync":
            return rehearse_sync(args.work, args.no_analysis)
        if args.command == "copy-db":
            return copy_db(args.source, args.work)
        if args.command == "candidates":
            return candidates(args.work)
        if args.command == "copy-tracks":
            return copy_tracks(args.source, args.work, args.track)
        return rehearse(args.work, args.edit_title)
    except Refused as e:
        print(f"Refused: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
