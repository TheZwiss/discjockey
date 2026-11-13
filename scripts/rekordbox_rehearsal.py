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

`rehearse` (plan RH steps 3–7): copies `W/source/master.db` to `W/rb/master.db`, points the chosen tracks at their
copies in `W/music/Library/Rehearsal/` with Discjockey's own writer (and edits one title, a user edit to keep), makes
a scratch Discjockey library (`W/support`, music folder `W/music`) with the copies as own songs and per track a parked
upgrade rendered from its own audio, takes the "before" picture, runs `bin/discjockey upgrade apply --all --way
same-track --json` and `bin/discjockey batch undo <id> --json` with `DISCJOCKEY_SUPPORT` and `DISCJOCKEY_REKORDBOX`
pointing into `W`, and checks each step with Discjockey's reader. It prints one PASS/FAIL line per check (tracks by
their labels only) and writes `W/report.json`. Exit code 0 when every check passes, 1 otherwise, 2 when it refuses.
`rehearse-sync` (plan stage C §7 RH): the same copies, but the sync's Auto-upgrade phase instead of `upgrade apply`;
see its docstring. Run it on a work folder that only `copy-db` and `copy-tracks` have touched (it changes the copies).
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
from datetime import UTC, date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from mutagen.aiff import AIFF  # noqa: E402

from discjockey import audio, auto_upgrade, config, library, quality, sources, upgrades  # noqa: E402
from discjockey.library import Paths  # noqa: E402
from discjockey.models import OWN_PREFIX  # noqa: E402
from discjockey.settings import load_settings  # noqa: E402
from discjockey.names import expected_stem  # noqa: E402
from discjockey.planner import ENTRY_KEYS  # noqa: E402
from discjockey.rekordbox import anlz, master, offset, process, timing, write  # noqa: E402
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
              checks: Checks) -> None:
    """Plan RH step 6."""
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
               share_before: dict, code: int, result: dict, checks: Checks) -> None:
    checks.add("step 7 batch undo ran", code == 0, f"exit {code}, ok {result.get('ok')}")
    music_now = tree(ctx["paths"].root, skip=".discjockey")
    checks.add("step 7 every audio file back, byte-identical", music_now == music_before,
               f"{len(music_before)} files before, {len(music_now)} now; differing "
               f"{len(set(music_now.items()) ^ set(music_before.items()))}")
    share_now = tree(work / "rb" / "share")
    checks.add("step 7 every analysis file back, byte-identical", share_now == share_before, f"{len(share_now)} files")
    parked = [i["parked"] for i in ctx["info"].values()]
    checks.add("step 7 the parked downloads are back in Upgrades ready/",
               all(music_now.get(p) == music_before.get(p) for p in parked), f"{len(parked)} files")
    state = library.load_state(ctx["paths"])
    checks.add("step 7 the records are as before (old file, upgrade waiting)",
               all(state["tracks"][i["tid"]]["path"] == i["old_rel"] and state["tracks"][i["tid"]].get("upgrade")
                   for i in ctx["info"].values()))
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
    args = p.parse_args(argv)
    try:
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
