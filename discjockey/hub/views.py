"""Pure functions: state, run reports, settings and the preview plan -> the JSON of each hub screen (spec "hub" 6.9).

No file access and no clock here: the API passes everything in (today, now, and helpers that turn a track into a
cover or audio URL). Every number on the screens comes from these functions.
"""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import PurePosixPath
from typing import Callable
from urllib.parse import quote_plus

from .. import playlists_file as pf
from ..accounts import (ACCOUNTS, BROWSERS, DEFAULT_LIMITS, MAX_LIMIT, PREMIUM_MIN_KBPS, SERVICES, SERVICE_NAMES,
                        SERVICE_SIGNALS)
from ..accounts import assessment as service_assessment, zones as service_zones
from ..names import expected_stem, fold
from ..models import (OWN_FILE, SERVICE_NAMES as PLAYLIST_SERVICES, SOURCE_NAMES, BatchResult, BatchRow, DupFile, DuplicateGroup,
                      ImportCounts, MoveRow, PlannedMove, PlaylistRecord, Question, WatchedFolder, is_own, split_token,
                      track_link as key_link)
from ..pacing import KEEP_SIGNALS, Budget
from ..planner import KIND_RANK, WAIT_DAYS, TidyRow, out_of_place, tidy_rows
from ..quality import quality_line
from ..report import PLAN_LABELS, check_text
from ..settings import Settings
from ..sources import SOURCES
from ..upgrades import can_undo, swap_possible, upgrade_name

SECONDS_PER_DOWNLOAD = 70  # average per acquisition or upgrade check: pause, download, conversion, long breaks
WEAK_HZ = 17_000  # a lossy cutoff at or below this is audible: "weak"
QUALITIES = ("lossless", "good_lossy", "weak", "fake", "missing")
SIGNAL_DAYS = 14
SHORT_SOURCE = {"qobuz": "Qobuz", "youtube_music": "YT Music", "soundcloud": "SoundCloud", "youtube": "YouTube",
                "manual": "bought"}
SHORT_OWN = "own file"  # SHORT_SOURCE["manual"] for a file the import found
LOSSLESS_SECTIONS = ("new_lossless", "redownloaded", "bought", "replaced", "swapped", "added_new")
LOSSY_SECTIONS = ("new_not_lossless", "fake")
PROBLEM_SECTIONS = ("missing", "errors", "conflicts", "ambiguous")
MOVED_SECTIONS = ("moved", "adopted")
NEW_FILE_SECTIONS = ("new_lossless", "new_not_lossless", "fake", "redownloaded", "bought", "replaced", "added_new")
STOPPED_NOTE = "stopped before this track was done"
LAST_RUNS = 30  # on the dashboard; the panel scrolls, "All runs" has the whole history by month


# --- quality of one entry ---

def quality_class(e: dict) -> str:
    """The colour of a track: lossless (green), good_lossy (yellow), weak (red), fake (purple), missing (red)."""
    status = e.get("status")
    if status == "lossless":
        return "lossless"
    if status == "fake_lossless":
        return "fake"
    if status == "missing":
        return "missing"
    cutoff = e.get("cutoff_hz")
    return "weak" if cutoff and cutoff <= WEAK_HZ else "good_lossy"


def khz(hz: int | None) -> str | None:
    return f"{hz / 1000:.1f} kHz" if hz else None


def quality_label(e: dict) -> str:
    q = quality_class(e)
    if q == "lossless":
        return "LOSSLESS"
    if q == "missing":
        return "NOT FOUND"
    if q == "fake":
        return f"FAKE · {khz(e.get('cutoff_hz'))}" if e.get("cutoff_hz") else "FAKE"
    return khz(e.get("cutoff_hz")) or "LOSSY"


def sound_checked(e: dict) -> bool:
    """False while an imported file has only the codec's provisional quality (import_state "identified": tags read,
    sound not judged yet, plan library stage 4 D1). Every count of qualities leaves such a file out."""
    return e.get("import_state") != "identified"


def quality_counts(entries: list[dict]) -> dict:
    """How many entries are of each quality; files whose sound isn't checked yet are not counted."""
    by = {q: 0 for q in QUALITIES}
    for e in entries:
        if sound_checked(e):
            by[quality_class(e)] += 1
    return by


# --- formulas (spec 6.9) ---

def lossless_share(state: dict) -> dict:
    """Lossless tracks ÷ tracks in playlists (hidden ones count; a file whose sound isn't checked yet doesn't).
    share is None when there are none ("—")."""
    by = quality_counts([e for e in state["tracks"].values() if e.get("in_playlists")])
    total = sum(by.values())
    return {"share": round(by["lossless"] / total, 4) if total else None, "lossless": by["lossless"], "total": total,
            "by_quality": by}


def run_minutes(downloads: int) -> int:
    """≈ 70 s per acquisition or upgrade check (a bought file counts as 0), rounded to 5 minutes (at least 5)."""
    if downloads <= 0:
        return 0
    return max(5, 5 * round(downloads * SECONDS_PER_DOWNLOAD / 300))


def minutes_by_downloads(most: int) -> list[int]:
    """run_minutes for 0 .. `most` downloads. The Sync page ticks and unticks actions, so it needs the time for any
    smaller count at once; it looks it up here instead of repeating the formula (and without a bridge call per tick)."""
    return [run_minutes(n) for n in range(max(most, 0) + 1)]


def days_to_load(rest: int, remaining_today: int, limit: int) -> int:
    """The days the rest takes, today counted only when something is left today: 1 if the rest fits today's
    remaining allowance, else 1 + ceil((rest − today's remaining) ÷ daily limit); with nothing left today it starts
    tomorrow: ceil(rest ÷ daily limit). 0 when nothing is left to load. The window's twin: lib/days.ts."""
    if rest <= 0:
        return 0
    remaining_today = max(0, remaining_today)
    if rest <= remaining_today:
        return 1
    return (1 if remaining_today else 0) + math.ceil((rest - remaining_today) / limit)


def assessment(limit: int, service: str = "qobuz") -> dict:
    """A guess, labelled as one (accounts.assessment)."""
    return service_assessment(service, limit)


def services_of(settings: Settings) -> list[str]:
    """The services with a daily limit that are set up, in quality order. Qobuz counts as set up unless the user said
    "I don't have Qobuz" (a missing login shows up when a sync starts, as before)."""
    return ([] if settings.qobuz_skipped else ["qobuz"]) + [s for s in ACCOUNTS if s in settings.accounts]


def budget(state: dict, settings: Settings, today: date, service: str = "qobuz") -> dict:
    b = Budget(state, lambda: None, settings, today=lambda: today, service=service)
    return {"used": b.used_today(), "allowance": b.allowance(), "limit": b.limit(),
            "carry_over": b.carry_over(), "extra": settings.extra_of(service, today), "remaining": b.remaining()}


def moneys(state: dict, settings: Settings, today: date) -> dict[str, dict]:
    return {s: budget(state, settings, today, s) for s in services_of(settings)}


def gate(money: dict[str, dict]) -> dict | None:
    """What every planned download counts against (plan "Decisions" 2): Qobuz when it is set up (a track waits when
    Qobuz is used up, as before), else the accounts together. None: no limit at all (only the free sources)."""
    if not money:
        return None
    if "qobuz" in money:
        return {"remaining": money["qobuz"]["remaining"], "limit": money["qobuz"]["limit"]}
    return {"remaining": sum(m["remaining"] for m in money.values()), "limit": sum(m["limit"] for m in money.values())}


def split(needed: int, money: dict[str, dict]) -> list[dict]:
    """Which service the planned downloads are expected to use (spec §7). With Qobuz set up, Qobuz takes them up to
    what's left and the accounts only get the tracks Qobuz doesn't have, so they show what's left, not a share.
    Without Qobuz, the accounts fill up in order. Both are estimates ("about"), except Qobuz's own number."""
    out, rest = [], needed
    for service, m in money.items():
        behind = "qobuz" in money and service != "qobuz"
        uses = None if behind else min(rest, m["remaining"])
        out.append({"service": service, "name": SERVICE_NAMES[service], "uses": uses, "left": m["remaining"],
                    "limit": m["limit"], "about": service != "qobuz"})
        rest -= uses or 0
    return out


def plan_counts(actions: list) -> dict:
    c = {"new": 0, "retries": 0, "redownloads": 0, "bought": 0, "weekly_checks": 0}
    for a in actions:
        if a.kind == "acquire":
            c[{"new": "new", "retry": "retries", "redownload": "redownloads"}.get(a.reason, "new")] += 1
        elif a.kind == "adopt_bought":
            c["bought"] += 1
        elif a.kind == "upgrade":
            c["weekly_checks"] += 1
    return c


def downloads_in(actions: list) -> int:
    return sum(1 for a in actions if a.kind in ("acquire", "upgrade"))


def estimate(actions: list, money: dict | None, accounts: list | tuple = ()) -> dict:
    """Once today's allowance is used up, the rest is queued for the next run at once, so only the downloads that fit
    today take time. `money`: gate(); None means no limit. The qobuz_* names stay for one release (spec §8)."""
    needed = downloads_in(actions)
    left = None if money is None else money["remaining"]
    limit = 0 if money is None else money["limit"]
    fits = needed if left is None else min(needed, left)
    return {"duration_min": run_minutes(fits), "qobuz_limit": limit, "qobuz_needed": needed,
            "qobuz_left": needed if left is None else left, "qobuz_uses": fits,
            "accounts": list(accounts), "left": left, "limit": limit}


def sync_estimate(actions: list, money: dict[str, dict]) -> dict:
    """The preview's estimate: `estimate()` plus what the page needs for any ticked subset of the plan. A subset has
    fewer downloads, and at most `left` of them run, so `qobuz_uses` is the most it can run today. `minutes_by_downloads`
    is the time for 0 .. that many downloads. Each account also gets `uses_by_downloads`: its `uses` (split()) for
    each of those counts, null for an account behind Qobuz; a larger count runs no more, so the page takes the last
    entry. The page looks these up and never repeats split() or the formula. `money`: moneys()."""
    needed = downloads_in(actions)
    e = estimate(actions, gate(money), split(needed, money))
    most = e["qobuz_uses"]
    by_count = [split(n, money) for n in range(most + 1)]
    accounts = [{**acc, "uses_by_downloads": None if acc["uses"] is None else [rows[i]["uses"] for rows in by_count]}
                for i, acc in enumerate(e["accounts"])]
    return {**e, "accounts": accounts, "minutes_by_downloads": minutes_by_downloads(most)}


def planned(prep, state: dict) -> tuple[list, list]:
    """The preview's actions split by the current "never download" list: (to do, never download). A track marked or
    unmarked after the read moves at once, without reading Spotify again."""
    if prep is None:
        return [], []
    never = state.get("never") or {}
    both = sorted([*prep.plan.actions, *prep.plan.never], key=lambda a: (KIND_RANK[a.kind], a.order))
    out: tuple[list, list] = ([], [])
    for a in both:
        out[a.kind == "acquire" and a.track_id in never].append(a)
    return out


def still_to_load(prep, money: dict | None, state: dict) -> dict:
    """Acquisitions in the latest preview plan, and how many days they take at the current limits (money: gate())."""
    count = sum(1 for a in planned(prep, state)[0] if a.kind == "acquire") if prep else None
    if count is None:
        return {"count": None, "days": None, "fits_today": None}
    days = (1 if count else 0) if money is None else days_to_load(count, money["remaining"], money["limit"])
    return {"count": count, "days": days, "fits_today": money is None or count <= money["remaining"]}


def read_status(store, now: datetime, reading: bool, logins: Sequence[tuple[str, bool]]) -> dict:
    """"Playlists read 2 min ago · ↻" (the wire field is `read_status`). problem: the last read's problem kind
    (offline: the data shown is older); problem_service: the playlist service it is about, else null. auto_read: the
    hub's one automatic read of this session has started (the Sync page then never reads by itself). services: each
    playlist service playlists.txt uses with whether its login is there; `logins` is (service, connected) in that
    order, worked out by the caller (this module does no I/O)."""
    read_at = store.read_at
    return {"read_at": read_at.isoformat(timespec="seconds") if read_at else None,
            "minutes_ago": int((now - read_at).total_seconds() // 60) if read_at else None,
            "problem": store.problem, "problem_service": store.problem_service, "message": store.message,
            "stale": store.stale, "reading": reading, "offline": store.problem == "offline",
            "auto_read": store.auto_read,
            "services": [{"service": s, "name": PLAYLIST_SERVICES[s], "connected": ok} for s, ok in logins]}


# --- run history (reports/*.json) ---

def run_summary(run_id: str, data: dict) -> dict:
    results = data.get("results") or []

    def count(sections) -> int:
        return sum(1 for r in results if r.get("section") in sections)

    lossless = sum(1 for r in results if r.get("section") in LOSSLESS_SECTIONS and r.get("status") == "lossless")
    lossy = count(LOSSY_SECTIONS) + sum(1 for r in results if r.get("section") in LOSSLESS_SECTIONS and
                                        r.get("status") not in (None, "lossless"))
    started, finished = data.get("started"), data.get("finished")
    seconds = None
    if started and finished:
        seconds = int((datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds())
    code = data.get("exit_code")
    stopped_after = None
    if code == 130:
        # every "queued" result was not done: stopped before it, left out by the user, or over the daily limit
        stopped_after = sum(1 for r in results if r.get("track_id") and r.get("section") != "queued")
    return {"run_id": run_id, "started": started, "finished": finished, "duration_s": seconds, "exit_code": code,
            "counts": {"lossless": lossless, "lossy": lossy, "problems": count(PROBLEM_SECTIONS),
                       "moved": count(MOVED_SECTIONS)},
            "stopped_after": stopped_after}


def runs(reports: list[tuple[str, dict]]) -> list[dict]:
    """Newest first. `reports`: (run id = file stem, the .json content)."""
    return [run_summary(rid, data) for rid, data in sorted(reports, key=lambda r: r[0], reverse=True)]


def run_detail(run_id: str, data: dict, state: dict, cover: Url | None = None,
               folder_order: list[str] | None = None) -> dict:
    """The end screen of a run: totals, what needs the user, what changed for rekordbox, upgrades waiting. With
    `cover`, every row that is shown one by one gets its `cover_url` (not the tracks still waiting); `folder_order`: the
    playlist folders in playlists.txt order, for the groups."""
    results = data.get("results") or []
    if cover is not None:
        results = [{**r, "cover_url": cover(r["track_id"], state["tracks"].get(r["track_id"]))}
                   if r.get("track_id") and r.get("section") != "queued" else r for r in results]
    sections: dict[str, list] = {}
    for r in results:
        sections.setdefault(r.get("section"), []).append(r)
    needs = [r for r in results if r.get("section") in PROBLEM_SECTIONS and r.get("track_id")]
    new_files = [r["path"] for r in results if r.get("section") in NEW_FILE_SECTIONS and r.get("path")]
    folders = sorted({p.rsplit("/", 1)[0] for p in new_files})
    return {**run_summary(run_id, data), "sections": sections, "needs_you": needs,
            "for_rekordbox": {"new_files": len(new_files), "folders": folders},
            "upgrades_ready": sum(1 for e in state["tracks"].values() if e.get("upgrade") and e.get("in_playlists")),
            "report_md": f"reports/{run_id}.md", "queued": len(sections.get("queued", [])),
            "folder_order": list(folder_order or [])}


# --- dashboard ---

def greeting(now: datetime) -> str:
    if now.hour < 5 or now.hour >= 18:
        return "Good evening"
    return "Good morning" if now.hour < 12 else "Good afternoon"


def folder_bars(state: dict, folder_order: list[str]) -> list[dict]:
    """Per playlist folder (playlists.txt order): tracks in playlists and their qualities."""
    out = []
    for folder in folder_order:
        entries = [e for e in state["tracks"].values() if e.get("in_playlists") and e.get("folder") == folder]
        by = quality_counts(entries)
        counted = sum(by.values())
        out.append({"folder": folder, "tracks": len(entries),
                    "lossless_share": round(by["lossless"] / counted, 4) if counted else None,
                    "by_quality": by})
    return out


def needs_you(state: dict) -> dict:
    never = state.get("never") or {}
    live = [(k, e) for k, e in state["tracks"].items() if e.get("in_playlists") and not e.get("hidden")]
    ups = [e for e in state["tracks"].values() if e.get("upgrade") and e.get("in_playlists")]
    swappable = sum(1 for e in ups if (e["upgrade"].get("alignment") or {}).get("result") in ("exact", "shifted"))
    return {"upgrades": len(ups), "swappable": swappable,
            "not_found": sum(1 for k, e in live if e.get("status") == "missing" and k not in never),
            "weak": sum(1 for _, e in live if quality_class(e) == "weak")}


def dashboard(state: dict, settings: Settings, store, reports: list[tuple[str, dict]], folder_order: list[str],
              setup: dict, today: date, now: datetime, reading: bool, logins: Sequence[tuple[str, bool]] = ()) -> dict:
    money = budget(state, settings, today)
    m = moneys(state, settings, today)
    prep = store.prep
    ready = None
    todo = planned(prep, state)[0]
    if prep is not None:
        ready = {"counts": plan_counts(todo), "actions": len(todo),
                 **estimate(todo, gate(m), split(downloads_in(todo), m))}
    history = runs(reports)
    empty = None
    if not setup["playlists"]:
        empty = "no_playlists"
    elif not setup["complete"]:
        empty = "not_set_up"
    elif not state["tracks"]:
        empty = "empty_library"
    return {"greeting": greeting(now), "read_status": read_status(store, now, reading, logins),
            "tiles": {"lossless": lossless_share(state), "qobuz_today": money,
                      "still_to_load": still_to_load(prep, gate(m), state),
                      "account_today": next((c for c in limit_cards(state, settings, today) if c["set_up"]), None)},
            "ready": ready, "needs_you": needs_you(state), "folders": folder_bars(state, folder_order),
            "last_runs": history[:LAST_RUNS], "has_more_runs": len(history) > LAST_RUNS,
            "next_checks": sum(1 for a in todo if a.kind == "upgrade") if prep else None,
            "empty": empty}


# --- Download limits ---

def _signals(state: dict, today: date, service: str = "qobuz", seen: str | None = None) -> list[dict]:
    """The warning signs of the last SIGNAL_DAYS days. Each also says whether it came after the user's last "Got it"
    (`new`) and in how many days it drops out of the window (`clears_in`, 1 = tomorrow)."""
    since = (today - timedelta(days=SIGNAL_DAYS - 1)).isoformat()
    return [{**s, "new": seen is None or s.get("time", "") > seen,
             "clears_in": SIGNAL_DAYS - (today - date.fromisoformat(s["time"][:10])).days}
            for s in state.get(f"{service}_usage", {}).get("signals", [])[-KEEP_SIGNALS:]
            if s.get("time", "") >= since]


def limit_cards(state: dict, settings: Settings, today: date) -> list[dict]:
    """The three cards on top of the Download limits page, always all three (spec §6)."""
    up = services_of(settings)
    out = []
    for service in SERVICES:
        card = {"service": service, "name": SERVICE_NAMES[service], "set_up": service in up, "used": 0,
                "allowance": 0, "warnings": 0, "new_warnings": 0, "paused": False}
        if service in up:
            m = budget(state, settings, today, service)
            signals = _signals(state, today, service, settings.warnings_seen.get(service))
            card.update(used=m["used"], allowance=m["allowance"], warnings=len(signals),
                        new_warnings=sum(1 for s in signals if s["new"]),
                        paused=any(s["kind"] == "auto_stop" and s["time"][:10] == today.isoformat() for s in signals))
        out.append(card)
    return out


STREAM_SOURCES = ("youtube_music", "soundcloud", "youtube")
ACCOUNT_SOURCE = {"youtube": "youtube_music", "soundcloud": "soundcloud"}  # the source each account downloads


def _card_state(card: dict) -> str | None:
    if card["paused"]:
        return "paused"
    if card["allowance"] and card["used"] >= card["allowance"]:
        return "used_up"
    return None


def downloads(state: dict, settings: Settings, qobuz_signed_in: bool, profile_names: dict, today: date) -> dict:
    """Each download source's state and the library counted by rung: the source ladder and the account panels in
    Settings and Setup (spec settings-setup §4, §6.4). `profile_names`: service -> the display name of its saved
    browser profile (None when it has none or it can't be read)."""
    cards = {c["service"]: c for c in limit_cards(state, settings, today)}
    live = [e for e in state["tracks"].values() if e.get("in_playlists") and not e.get("hidden")]
    lossy = [e for e in live if e.get("status") == "not_lossless" and e.get("source") in STREAM_SOURCES]

    def premium(e: dict) -> bool:
        return (e.get("source_kbps") or 0) >= PREMIUM_MIN_KBPS

    qcheck = settings.qobuz_last_check
    if settings.qobuz_skipped:
        qstate = "skipped"
    elif not qobuz_signed_in or (qcheck and not qcheck["ok"]):
        qstate = "off"
    else:
        qstate = _card_state(cards["qobuz"]) or "on"
    out = {"qobuz": {"state": qstate, "last_check": dict(qcheck) if qcheck else None,
                     "tracks": sum(1 for e in live if e.get("source") == "qobuz")}}
    for service in ACCOUNTS:
        a = settings.accounts.get(service)
        check = dict(a.last_check) if a and a.last_check else None
        if a is None:
            st = "off"
        elif check and not check["ok"]:
            st = {"no_premium": "no_premium", "cookies_unreadable": "unreadable"}.get(check["problem"], "off")
        else:
            st = _card_state(cards[service]) or "on"
        out[service] = {"state": st, "browser": a.browser if a else None,
                        "browser_name": BROWSERS[a.browser] if a else None, "profile": a.profile if a else None,
                        "profile_name": profile_names.get(service) if a else None, "last_check": check,
                        "tracks": sum(1 for e in lossy if e["source"] == ACCOUNT_SOURCE[service] and premium(e))}
    out["library"] = {"lossless": sum(1 for e in live if e.get("status") == "lossless"),
                      "account": sum(1 for e in lossy if premium(e)),
                      "free": sum(1 for e in lossy if not premium(e))}
    return out


def _acquisitions(prep, state: dict) -> int | None:
    return sum(1 for a in planned(prep, state)[0] if a.kind == "acquire") if prep else None


def limits_what_if(service: str, limit: int, extra_today: int, state: dict, settings: Settings, prep,
                   today: date) -> dict:
    """What a daily limit (and a one-time extra) of one service would mean: assessment, days for the rest, run
    length. For an account behind Qobuz the days stay None: Qobuz decides them."""
    trial = settings.with_limit(service, limit, today.isoformat() if extra_today else None, extra_today)
    money = moneys(state, trial, today)
    rest = _acquisitions(prep, state)
    behind = "qobuz" in money and service != "qobuz"
    g = gate(money)
    per_run = min(limit, rest) if rest is not None else limit
    return {"limit": limit, "extra_today": extra_today, "assessment": assessment(limit, service),
            "allowance_today": money[service]["allowance"], "remaining_today": money[service]["remaining"],
            "days_to_load": None if rest is None or behind else days_to_load(rest, g["remaining"], g["limit"]),
            "run_minutes": run_minutes(per_run)}


def limits(service: str, state: dict, settings: Settings, prep, today: date) -> dict:
    """The Download limits page (spec §6): the three cards, and for a set-up service today's numbers, the last 14
    days, its setting, what it means and its warning signs."""
    cards = limit_cards(state, settings, today)
    if service not in services_of(settings):
        return {"service": service, "cards": cards, "usage": None}
    money = moneys(state, settings, today)
    own = money[service]
    u = state.get(f"{service}_usage", {})
    days = u.get("days", {})
    last14 = [{"date": (today - timedelta(days=i)).isoformat(),
               "used": days.get((today - timedelta(days=i)).isoformat(), 0)} for i in range(SIGNAL_DAYS - 1, -1, -1)]
    signals = _signals(state, today, service, settings.warnings_seen.get(service))
    summary = {k: 0 for k in SERVICE_SIGNALS[service]}
    for s in signals:
        if s.get("kind") in summary:
            summary[s["kind"]] += 1
    behind = "Qobuz" if "qobuz" in money and service != "qobuz" else None
    limit = settings.limit_of(service)
    return {"service": service, "cards": cards, "usage": {
        "service": service, "name": SERVICE_NAMES[service], "behind": behind,
        "today": own, "days": last14,
        "still_to_load": still_to_load(prep, gate(money), state) if behind is None
        else {"count": None, "days": None, "fits_today": None},
        "setting": {"limit": limit, "extra_today": settings.extra_of(service, today),
                    "recommended": DEFAULT_LIMITS[service], "zones": service_zones(service), "min": 1,
                    "max": MAX_LIMIT, "extra_max": 200},
        "assessment": assessment(limit, service),
        "what_if": limits_what_if(service, limit, settings.extra_of(service, today), state, settings, prep, today),
        "signals": signals, "signal_summary": summary, "last_download": u.get("last_download")}}


# --- one track ---

Url = Callable[[str, dict], "str | None"]  # (track id, entry) -> URL, or None
NOT_IN_PLAYLIST = "__not_in_playlist__"
CUE_TEXT = {"exact": "matches exactly, cues stay", "different": "doesn't match: would be a new rekordbox entry",
            "unknown": "could not compare the two versions"}


def is_own_file(e: dict) -> bool:
    """A file of the user's own that the import found (its file row is placed by "import"), not one bought through a
    sync: its source is "manual" like a bought file's, but it was never bought by Discjockey."""
    return e.get("source") == "manual" and e.get("placed_by") == "import"


def track_row(track_id: str, e: dict, cover: Url | None = None) -> dict:
    source = e.get("source")
    # an own file has no added day from a playlist: the day Discjockey first saw the file stands in
    added = e.get("added") or (e.get("first_seen") if is_own_file(e) else None)
    return {"track_id": track_id, "artist": e["artist"], "title": e["title"], "folder": e["folder"] or "",
            "duration_s": round((e.get("duration_ms") or 0) / 1000, 1), "status": e["status"],
            "quality": quality_class(e), "quality_label": quality_label(e), "cutoff_hz": e.get("cutoff_hz"),
            "source": source,
            "source_name": (SHORT_OWN if is_own_file(e) else SHORT_SOURCE.get(source)) if source else None,
            "in_playlists": bool(e.get("in_playlists")), "own": is_own_file(e), "hidden": bool(e.get("hidden")),
            "upgrade_ready": bool(e.get("upgrade")), "path": e.get("path"), "added": added,
            "cover_url": cover(track_id, e) if cover else None}


def cue_text(alignment: dict | None, can_swap: bool = True) -> str:
    """The line under a parked better version: what the measurement says about the cue points, and what that means
    for the way it goes in. Only a swap (AIFF only) keeps the rekordbox entry and its cues; a file that cannot be
    swapped goes in as a new file, which rekordbox sees as a new entry, so the old entry has to be relocated."""
    a = alignment or {}
    result = a.get("result")
    ms = abs(a.get("offset_ms") or 0)
    if result in ("exact", "shifted") and not can_swap:
        same = "same edit" if result == "exact" else f"same edit, {ms:.0f} ms apart"
        return f"{same}, but a new rekordbox entry: relocate the old one to the new file to keep its cues"
    if result == "shifted":
        return f"aligned by {ms:.0f} ms, cues stay"
    return CUE_TEXT.get(result, CUE_TEXT["unknown"])


def source_url(source: str | None, source_id: str | None) -> str | None:
    if not source or not source_id:
        return None
    if source == "qobuz":
        return f"https://open.qobuz.com/track/{source_id}"
    if source == "youtube_music":
        return f"https://music.youtube.com/watch?v={source_id}"
    if source == "youtube":
        return f"https://www.youtube.com/watch?v={source_id}"
    return None  # SoundCloud ids are numbers, not part of a link


def next_check(e: dict, today: date) -> str | None:
    """When Discjockey looks on Qobuz again: an ISO date, "next_sync" when due, None when it never does."""
    if not e.get("in_playlists") or e.get("upgrade") or e["status"] == "lossless":
        return None
    day = e.get("last_attempt") if e["status"] == "missing" else e.get("last_upgrade_check")
    if not day:
        return "next_sync"
    due = date.fromisoformat(day[:10]) + timedelta(days=WAIT_DAYS)
    return "next_sync" if due <= today else due.isoformat()


def buy_links(artist: str, title: str) -> dict:
    q = quote_plus(f"{artist} {title}")
    return {"beatport": f"https://www.beatport.com/search?q={q}", "bandcamp": f"https://bandcamp.com/search?q={q}"}


FORMAT_NAMES = {"opus": "Opus", "aac": "AAC", "mp3": "MP3", "flac": "FLAC", "vorbis": "Vorbis", "alac": "ALAC"}


def format_line(e: dict) -> str | None:
    """"Opus · 135 kbps", "FLAC": the format of the download (and its bitrate when lossy), None without a file."""
    f = e.get("source_format")
    if e["status"] == "missing" or not f:
        return None
    name = "uncompressed PCM" if f.startswith("pcm_") else FORMAT_NAMES.get(f, f.upper())
    kbps = e.get("source_kbps") if e["status"] == "not_lossless" else None
    return f"{name} · {kbps} kbps" if kbps else name


def free_downloads(e: dict) -> list[dict]:
    """The artists' free downloads found on SoundCloud (a gate page or SoundCloud's own button), while the track
    is not lossless."""
    if e["status"] == "lossless":
        return []
    keys = ("url", "host", "direct", "title", "uploader")
    return [{k: f.get(k) for k in keys} for f in e.get("free_downloads") or [] if f.get("url")]


def in_playlists(track_id: str, e: dict, fetched: list) -> list[str] | None:
    """Folders of the active playlists that contain the track (from the last playlist read), or None if unknown."""
    if not fetched:
        return None
    ids = {track_id, *(e.get("aliases") or [])}
    return [fp.line.folder for fp in fetched if any(t.key in ids for t in fp.tracks)]


def track_link(track_id: str, e: dict, fetched: list) -> dict | None:
    """{url, label} of the track's page on its service: the link of the first fetched track (playlist order) that is
    this song, else the link its key gives; None when neither has one."""
    ids = {track_id, *(e.get("aliases") or [])}
    link, service = next(((t.link, t.service) for fp in fetched for t in fp.tracks if t.key in ids and t.link),
                         (key_link(track_id), split_token(track_id)[0]))
    return {"url": link, "label": f"Open in {PLAYLIST_SERVICES[service]}"} if link else None


def upgrade_format(up: dict) -> str:
    """The parked version's quality in the words of the current file's `format_line`: "FLAC · lossless",
    "AAC · 256 kbps" (a better lossy stream), so the To-do panel's Now and New say the same kind of thing."""
    f = up.get("source_format") or "flac"
    name = "PCM" if f.startswith("pcm_") else FORMAT_NAMES.get(f, f.upper())
    if up.get("status", "lossless") == "lossless":
        return f"{name} · lossless"
    return f"{name} · {up['kbps']} kbps" if up.get("kbps") else name


def upgrade_status(up: dict, can_swap: bool) -> str:
    """The To-do row's short line for an upgrade: what is ready, and what replacing means for rekordbox (the panel
    says the rest). Same edit and an AIFF file: the cues can stay (Swap); same edit otherwise: rekordbox gets a new
    track; a different edit or no measurement: says so."""
    what = "Lossless" if up.get("status", "lossless") == "lossless" else f"{up.get('kbps') or '?'} kbps"
    result = (up.get("alignment") or {}).get("result")
    if result in ("exact", "shifted"):
        how = "cues can stay" if can_swap else "new rekordbox track"
    else:
        how = "different edit" if result == "different" else "not compared"
    return f"{what} ready · {how}"


def check_status(check: dict | None) -> str:
    """The To-do row's short line for a rekordbox check (report.check_text is the long one, the panel's)."""
    c = check or {}
    reason = c.get("reason")
    if reason == "swapped":
        return "relocate, Reload Tag, analyse again" if c.get("moved") else "Reload Tag, analyse again"
    if reason == "added_as_new":
        return "relocate, analyse again" if c.get("match") in ("exact", "shifted") else "analyse, set the cues again"
    if reason == "wrong_song":
        return "now the right song: analyse again"
    return "check it in rekordbox"


def check_view(check: dict | None) -> dict:
    """RekordboxCheck as the To-do panel reads it: the step that left it and what the two files measured as (its
    numbered steps follow them), `text` the whole instruction (report.check_text), `old_path` where the old file (an
    added file) or the copy of the old audio (a swap) is now, from the undo record (null without one)."""
    c = check or {}
    undo = c.get("undo") or {}
    return {"reason": c.get("reason"), "since": c.get("since"), "match": c.get("match"),
            "offset_ms": c.get("offset_ms"), "moved": bool(c.get("moved")), "text": check_text(c),
            "old_path": undo.get("old")}


def upgrade_block(up: dict | None, media: Url | None, track_id: str, e: dict) -> dict | None:
    if not up:
        return None
    alignment = up.get("alignment") or {"result": "unknown"}
    return {"file": up["file"], "source": up["source"], "source_name": SHORT_SOURCE.get(up["source"]),
            "source_id": up.get("source_id"), "found": up.get("found"),
            "what": upgrade_name(up),
            "quality_line": quality_line(up["source"], up.get("source_format") or "flac", up.get("status", "lossless"),
                                         up.get("cutoff_hz"), up.get("kbps")),
            "format_line": upgrade_format(up),
            "alignment": alignment, "cue_text": cue_text(alignment, swap_possible(e)),
            "swap_safe": alignment.get("result") in ("exact", "shifted"),
            "swap_possible": swap_possible(e),
            "audio_url": media(track_id, {**e, "path": up["file"]}) if media else None}


def file_state(e: dict, away: Mapping[str, str] | None = None, exists: bool = True) -> str:
    """Why the file of entry `e` is or is not there to play and act on right now:
    "offline" (its drive is not connected), "folder_missing" (its watched folder is not found: moved, renamed or
    deleted), "file_missing" (its folder is there, the file's path is not: it went since the last scan) or "here".
    `away`: import-folder root -> why it is not there now ("unmounted" | "missing", scanner.away_reason), as the api
    checks them live: an unplugged drive counts before any scan noticed. A row that says it was away at the last scan
    (`online`) stays "offline" while no root says otherwise. `exists`: whether the file is at its path (the api asks
    for the one track it builds the detail for). Entries without the keys (the old records) are there, and a track
    without a file has nothing to be away."""
    path = e.get("path")
    if not path:
        return "here"
    inside = [r for r in (away or ()) if path == r or path.startswith(r.rstrip("/") + "/")]
    if inside:  # the innermost watched folder holding it decides
        return "offline" if away[max(inside, key=len)] == "unmounted" else "folder_missing"
    if not e.get("online", True):
        return "offline"
    return "here" if exists else "file_missing"


def file_online(e: dict, away: Mapping[str, str] | None = None) -> bool:
    """Whether the file of entry `e` is in a watched folder that is there (file_state without the file check)."""
    return file_state(e, away) == "here"


def track_detail(track_id: str, e: dict, fetched: list, today: date, cover: Url | None = None,
                 media: Url | None = None, away: Mapping[str, str] | None = None, exists: bool = True,
                 place: str | None = None) -> dict:
    """`away`, `exists`: see file_state (HubApi._away_roots; whether the file is at its path). Whatever the state but
    "here", there is no `audio_url`: nothing to play. `place`: where the file sits (Sites.place, D11), the same words
    as the Folder column; None for a track without a file."""
    folders = in_playlists(track_id, e, fetched)
    state = file_state(e, away, exists)
    has_file = e["status"] != "missing" and e.get("source")
    return {**track_row(track_id, e, cover), "sound_checked": sound_checked(e), "isrc": e.get("isrc"),
            "file_state": state, "place": place,
            "playlists": folders, "in_playlist_count": len(folders) if folders is not None else None,
            "quality_line": quality_line(e["source"], e.get("source_format") or "?", e["status"], e.get("cutoff_hz"),
                                         e.get("source_kbps"), own=is_own_file(e),
                                         checked=sound_checked(e)) if has_file else None,
            "format_line": format_line(e) if has_file else None,
            "source_full": ((OWN_FILE if is_own_file(e) else "bought" if e["source"] == "manual"
                             else SOURCE_NAMES.get(e["source"])) if has_file else None),
            "source_url": source_url(e.get("source"), e.get("source_id")),
            "track_link": track_link(track_id, e, fetched),
            "next_qobuz_check": next_check(e, today), "rejected_sources": list(e.get("rejected_sources") or []),
            "buy_links": buy_links(e["artist"], e["title"]), "free_downloads": free_downloads(e),
            "bought_name": f"Library/{e['folder']}/{expected_stem(e['artist'], e['title'])}.wav",
            "audio_url": media(track_id, e) if media and e.get("path") and state == "here" else None,
            "upgrade": upgrade_block(e.get("upgrade"), media, track_id, e)}


# --- library ---

SORTS = {"title": lambda r: fold(r["title"]), "artist": lambda r: (fold(r["artist"]), fold(r["title"])),
         "length": lambda r: r["duration_s"], "source": lambda r: r["source_name"] or "",
         # files whose sound isn't checked yet have no real quality: they sort after every checked one
         "quality": lambda r: QUALITIES.index(r["quality"]) if r["sound_checked"] else len(QUALITIES),
         "added": lambda r: r["added"] or "",
         # a playlist's own order; a row without a place in it (a file the playlist doesn't hold) goes last, those by
         # artist, then title
         "order": lambda r: (r["position"] is None, r["position"] or 0, fold(r["artist"]), fold(r["title"])),
         # tracks in no playlist sit in their folder on disk, but read as "Not in a playlist": they sort last
         # (the user's own songs, from the import, have no folder: "")
         "folder": lambda r: (not r["in_playlists"], fold(r["folder"]), fold(r["artist"]), fold(r["title"]))}
LIBRARY_FILTERS = ("all", "lossless", "good_lossy", "weak", "fake", "upgrade_ready")


def _matches(row: dict, filt: str) -> bool:
    """A quality filter (and its chip) never holds a file whose sound isn't checked yet: only All does."""
    if filt == "all":
        return True
    return row["upgrade_ready"] if filt == "upgrade_ready" else row["sound_checked"] and row["quality"] == filt


LIBRARY_VIEWS = ("all", "unlisted", "playlist", "folder")
AWAY_WORDS = {"offline": "Offline: connect the drive", "folder_missing": "Folder not found"}


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _resolver(state: dict) -> Callable[[str], str]:
    """A fetched token -> the song it names: a song's key, else the alias a later relink added; a token no song has
    stays as it is (D2)."""
    by_token = {key: key for key in state["tracks"]}
    for key, e in state["tracks"].items():
        for alias in e.get("aliases") or []:
            by_token.setdefault(alias, key)
    return lambda token: by_token.get(token, token)


def _holders(lines: Sequence[pf.Row], records: Mapping[str, PlaylistRecord],
             resolve: Callable[[str], str]) -> dict[str, list[str]]:
    """Song key (or the token no song has) -> the names of the playlists whose read holds it, in playlists.txt order
    (a switched-off playlist keeps its record; a name used by two lines counts once)."""
    out: dict[str, list[str]] = {}
    for r in lines:
        record = records.get(r.ref)
        for t in record.tracks if record else ():
            names = out.setdefault(resolve(t.token), [])
            if r.folder not in names:
                names.append(r.folder)
    return out


@dataclass(frozen=True)
class Sites:
    """Where the files sit, in the words of the Folder / Subfolder columns (plan library stage 5, D8, D11, D12). Paths
    are NFC. `names`: a Library folder's folded name -> the playlist line's spelling; `roots`: each watched import
    folder -> its name; `crates`: each crate -> (its watched folder's name, its label); `crate_counts`: each watched
    folder -> how many crates lie under it."""
    names: Mapping[str, str]
    roots: Mapping[str, str]
    crates: Mapping[str, tuple[str, str]]
    crate_counts: Mapping[str, int]

    def library_folder(self, path: str) -> str | None:
        """The Library folder a file sits in (its directory's name as the disk spells it, `not_lossless/` included),
        None for a file elsewhere."""
        parts = PurePosixPath(_nfc(path)).parts
        return parts[1] if len(parts) > 2 and parts[0] == "Library" else None

    def place(self, path: str) -> str:
        """The physical folder of the file at `path`: a playlist's or Library folder's name ("Techno 2019"), for an
        import file its watched folder and crate ("Rekordbox Library › Hardtechno › 2019"; no wrapper folders, a file
        in the watched folder itself says just its name). `not_lossless/` is part of its Library folder."""
        p = PurePosixPath(_nfc(path))
        if (own := self.library_folder(path)) is not None:
            return self.names.get(fold(own), own)
        folder = str(p.parent)
        if folder in self.crates:
            root, label = self.crates[folder]
            return f"{root} › {label}"
        return self.roots.get(folder) or p.parent.name or folder


def sites(state: dict, lines: Sequence[pf.Row], watched: Iterable[WatchedFolder]) -> Sites:
    """The `Sites` of the files with a file now. `watched`: db.watched_folders (the Library among them is left out)."""
    imports = [str(f.path) for f in watched if f.kind == "import"]
    found = crates([e["path"] for e in tracks_with_file(state)], imports, {})
    roots = {_nfc(w): PurePosixPath(w).name or w for w in imports}
    return Sites({fold(r.folder): r.folder for r in lines}, roots,
                 {_nfc(c["path"]): (roots[_nfc(w)], c["label"]) for w, f in found.items() for c in f["crates"]},
                 {_nfc(w): f["crate_count"] for w, f in found.items()})


def _folder_state(away: Mapping[str, str] | None, path: str) -> str:
    """"here", "offline" or "folder_missing" for the folder at `path` (NFC): the innermost away import folder holding it
    decides (as file_state does for a file)."""
    norm = {_nfc(r).rstrip("/"): why for r, why in (away or {}).items()}
    inside = [r for r in norm if path == r or path.startswith(r + "/")]
    return FOLDER_STATE.get(norm[max(inside, key=len)], "here") if inside else "here"


def library(state: dict, view: str, key: str | None, query: str, filt: str, sort: str | None, cover: Url | None = None,
            away: Mapping[str, str] | None = None, *, lines: Sequence[pf.Row],
            records: Mapping[str, PlaylistRecord] | None = None, watched: Sequence[WatchedFolder] = ()) -> dict:
    """One view of the library (plan library stage 5, I4, D9-D12). `view`: LIBRARY_VIEWS; `key`: the playlist's folder
    name (as playlists.txt spells it, any case) for "playlist", a folder's snapshot path (`Library/<name>`, or the
    absolute path in an import folder) for "folder", else ignored. filt: LIBRARY_FILTERS. sort: a SORTS key, "-" in
    front for descending (None: "order" in a playlist, else "artist"). `away`: the import folders that are not there
    now (HubApi._away_roots, as track_detail gets it): each row's `file_state` says whether its file is "here",
    "offline" (its drive is not connected) or "folder_missing", decided per folder (file_state without the file
    check: no file is looked at per row, so "file_missing" stays the panel's). `lines`: the playlists.txt lines
    (playlists_file.load(...).rows); `records`: db.playlist_records; `watched`: db.watched_folders.

    All and Not in a playlist list the files. A playlist lists its read record's songs in order, each once (D9):
    one without a file is a row too (`file_state` "no_file", `wait` "waiting" or "not_found"), and `also` holds the
    files in the playlist's own Library folder whose song the playlist doesn't hold. A folder lists the files at or
    below its path (a path nothing is known by still has its view; a vanished one is `gone`). Only the rows with a
    file count in `summary` and `chips`; the search narrows the rows and `also`. `songs` (a read playlist, else
    None): `{"listed", "with_file"}`, its distinct songs and how many of them have a file, before any search or
    filter: the page words "13 of 18 downloaded" from it. `folder` keeps the old meaning
    (None, NOT_IN_PLAYLIST, the playlist's or the folder's key)."""
    records = records or {}
    with_file = {k: e for k, e in state["tracks"].items() if e["status"] != "missing" and e.get("path")}
    found = sites(state, lines, watched)
    resolve = _resolver(state)
    holders = _holders(lines, records, resolve)

    def row(k: str, e: dict, **extra) -> dict:
        return {**track_row(k, e, cover), "sound_checked": sound_checked(e), "file_state": file_state(e, away),
                "wait": None, "position": None, "place": found.place(e["path"]), "subfolder": None,
                "playlists": holders.get(k, []), **extra}

    rows: list[dict] = []
    also = folder_kind = read_at = enabled = service = songs = None
    gone = False
    title, shown_key, folder = "All tracks", None, None
    subtitle: Callable[[str], list[str]] = lambda n: [n, "every folder"]
    if view == "unlisted":
        title, folder = "Not in a playlist", NOT_IN_PLAYLIST
        rows = [row(k, e) for k, e in with_file.items() if not e.get("in_playlists")]
        subtitle = lambda n: [n, "in no playlist"]
    elif view == "all":
        rows = [row(k, e) for k, e in with_file.items()]
    elif view == "playlist":
        line = next((r for r in lines if fold(r.folder) == fold(key or "")), None)
        title = shown_key = folder = line.folder if line else key or ""
        gone = line is None
        if line is not None:
            record = records.get(line.ref)
            read_at, enabled, service = record.read_at if record else None, line.enabled, line.service
            label = f"{PLAYLIST_SERVICES[line.service]} playlist" if line.service else "playlist"
            subtitle = ((lambda n: [label, "not read yet"]) if record is None else
                        (lambda n: [n, label, *(["switched off"] if not line.enabled else []),
                                    f"Library › {line.folder}"]))
            held: set[str] = set()
            for t in record.tracks if record else ():
                k = resolve(t.token)
                if k in held:
                    continue
                held.add(k)
                e = state["tracks"].get(k)
                if e is not None and k in with_file:
                    own = fold(found.library_folder(e["path"]) or "") == fold(line.folder)
                    rows.append(row(k, e, position=t.position, place=None if own else found.place(e["path"])))
                    continue
                base = {**(e or {"artist": t.artist, "title": t.title, "folder": None, "duration_ms": t.duration_ms,
                                 "in_playlists": True}),
                        "status": "missing", "path": None, "source": None, "cutoff_hz": None, "upgrade": None}
                rows.append({**track_row(k, base, cover), "sound_checked": True, "file_state": "no_file",
                             "wait": "not_found" if e is not None and _group(e) == "not_found" else "waiting",
                             "position": t.position, "place": None, "subfolder": None,
                             "playlists": holders.get(k, [line.folder])})
            also = [row(k, e, place=None) for k, e in with_file.items()
                    if k not in held and fold(found.library_folder(e["path"]) or "") == fold(line.folder)]
            if record is not None:  # the playlist's songs (D5: what the sidebar counts) and how many have a file
                songs = {"listed": len(held), "with_file": sum(1 for r in rows if r["file_state"] != "no_file")}
    else:  # a folder
        shown_key = folder = key or ""
        nkey = _nfc(shown_key).rstrip("/")
        root = max((r for r in found.roots if nkey == r or nkey.startswith(r + "/")), key=len, default=None)
        folder_kind = ("watched" if root == nkey else "crate" if root is not None
                       else "library" if nkey.startswith("Library/") else None)
        inside = [(k, e) for k, e in with_file.items()
                  if folder_kind is not None and _nfc(e["path"]).startswith(nkey + "/")]
        title = (found.roots[nkey] if folder_kind == "watched" else found.crates[nkey][1] if nkey in found.crates
                 else PurePosixPath(nkey).name)
        name = PurePosixPath(nkey).name
        gone = folder_kind is None or (folder_kind != "watched" and not inside)
        away_part = [AWAY_WORDS[s]] if (s := _folder_state(away, nkey)) != "here" else []
        for k, e in inside:
            between = _nfc(e["path"])[len(nkey) + 1:].split("/")[:-1]  # the folders from the folder to the file
            sub = None
            if folder_kind == "crate":
                sub = " › ".join(between)
            elif folder_kind == "watched":
                sub = found.crates.get(_nfc(str(PurePosixPath(e["path"]).parent)), ("", " › ".join(between)))[1] \
                    if between else ""
            rows.append(row(k, e, subfolder=sub))
        if folder_kind == "watched":
            count = found.crate_counts[nkey]
            subtitle = lambda n: [n, *away_part, *([_plural(count, "1 folder with music", "{n} folders with music")]
                                                  if count else []), place(nkey)]
        elif folder_kind == "crate":
            tip = " › ".join([found.roots[root], *nkey[len(root) + 1:].split("/")])
            subtitle = lambda n: [n, *away_part, tip]
        elif folder_kind == "library":
            used = any(fold(r.folder) == fold(name) for r in lines)
            subtitle = lambda n: [n, *([] if used else ["no playlist uses it"]), f"Library › {name}"]
    have = [r for r in rows if r["file_state"] != "no_file"]
    entries = [state["tracks"][r["track_id"]] for r in have]
    # sound_checked: false while an imported file has only the codec's provisional quality: the page says "sound not
    # checked yet", and no count below holds the file (it still counts under All and in "tracks")
    by = quality_counts(entries)
    counted = sum(by.values())
    # the view at a glance (the panel's overview): unaffected by the search and the filter
    summary = {"tracks": len(have), "lossless_share": round(by["lossless"] / counted, 4) if counted else None,
               "by_quality": by, "upgrades_ready": sum(1 for r in have if r["upgrade_ready"]),
               # checked files that aren't lossless: the strip's "Not lossless yet" row
               "not_lossless": by["good_lossy"] + by["weak"] + by["fake"],
               "to_do": sum(1 for e in entries if e.get("in_playlists") and not e.get("hidden") and _group(e) is not None)}
    q = fold(query or "").strip()
    if q:
        rows = [r for r in rows if q in fold(f"{r['artist']} {r['title']}")]
        also = [r for r in also if q in fold(f"{r['artist']} {r['title']}")] if also is not None else None
    chips = {f: sum(1 for r in rows if r["file_state"] != "no_file" and _matches(r, f)) for f in LIBRARY_FILTERS}
    rows = [r for r in rows if _matches(r, filt or "all")]
    also = [r for r in also if _matches(r, filt or "all")] if also is not None else None
    order = (sort or ("order" if view == "playlist" else "artist")).lstrip("-")
    order = "artist" if order == "order" and view != "playlist" else order
    for lst in (rows, also or []):
        lst.sort(key=SORTS.get(order, SORTS["artist"]), reverse=(sort or "").startswith("-"))
    empty = ("gone" if gone else None if rows or also else "empty_library" if not with_file else "no_match")
    return {"title": title, "folder": folder, "view": view, "key": shown_key, "folder_kind": folder_kind,
            "subtitle": [] if gone else subtitle(_plural(len(have), "1 track", "{n} tracks")), "summary": summary, "chips": chips,
            "rows": rows, "also": also, "songs": songs, "read_at": read_at, "enabled": enabled, "service": service,
            "empty": empty}


def tracks_with_file(state: dict) -> list[dict]:
    """The entries that have a file: what "All tracks" counts."""
    return [e for e in state["tracks"].values() if e["status"] != "missing" and e.get("path")]


CRATE_LIMIT = 25  # more crates than this under one watched folder: the folder is one row, its crates hidden (D8)
FOLDER_STATE = {"unmounted": "offline", "missing": "folder_missing"}  # scanner.away_reason -> FolderState (not "here")


def _natural(text: str) -> list:
    """A sort key that reads numbers as numbers and ignores case ("Set 2" before "Set 10")."""
    return [int(part) if part.isdigit() else part for part in re.split(r"([0-9]+)", fold(text))]


def crates(files: Iterable[str], watched: Iterable[str], overrides: Mapping[str, bool]) -> dict[str, dict]:
    """The crates under each watched import folder (plan library stage 5, D8). `files`: the snapshot paths of the
    files that are there (absolute for an import folder); `watched`: the import folders' paths; `overrides`:
    db.crate_overrides (crate path -> shown). A crate is any folder below a watched folder that holds a file itself;
    wrapper folders get no row, and the files directly in the watched folder belong to no crate. A file under two
    watched folders belongs to the deeper one. Returns, for every watched path, `{"too_many", "crate_count",
    "crates"}` with the crates in label order (natural numbers, case-folded) as Crate shapes (I4): its `files` are
    the files at or below it, `hidden` is the user's switch or, without one, the default (shown; hidden under a
    folder with more than CRATE_LIMIT crates), `has_crates` says another crate lies below it. A label never depends
    on what is hidden: every crate of every watched folder counts for the same-name rule."""
    roots = {w: PurePosixPath(w) for w in watched}
    holding: dict[str, set[PurePosixPath]] = {w: set() for w in roots}
    below: dict[PurePosixPath, int] = {}
    for f in files:
        folder = PurePosixPath(f).parent
        inside = [w for w, r in roots.items() if folder != r and folder.is_relative_to(r)]
        if not inside:
            continue
        w = max(inside, key=lambda w: len(roots[w].parts))
        holding[w].add(folder)
        for d in (folder, *folder.parents):
            if d == roots[w]:
                break
            below[d] = below.get(d, 0) + 1
    outer = {w: {d: next((a for a in d.parents if a in dirs), None) for d in dirs} for w, dirs in holding.items()}
    same_name = Counter(fold(d.name) for w, found in outer.items() for d, anc in found.items() if anc is None)
    out = {}
    for w, found in outer.items():
        root = roots[w]
        too_many = len(found) > CRATE_LIMIT
        parents = {anc for anc in found.values() if anc is not None}  # a crate has crates when one has it nearest
        rows = []
        for d, anc in found.items():
            label = (f"{anc.name} › {d.name}" if anc is not None
                     else f"{d.name} · {d.parent.name}" if same_name[fold(d.name)] > 1 else d.name)
            rows.append({"path": str(d), "label": label, "name": d.name,
                         "tip": " › ".join([root.name or w, *d.relative_to(root).parts]), "files": below[d],
                         "hidden": not overrides.get(str(d), not too_many),
                         "has_crates": d in parents})
        rows.sort(key=lambda r: (_natural(r["label"]), r["path"]))
        out[w] = {"too_many": too_many, "crate_count": len(rows), "crates": rows}
    return out


def place(path: str) -> str:
    """A folder's path as the watched-folder list words it (hub-ui `filePlace`, whole): the home folder as "~", a
    folder on another drive as "Example Drive › Music/Old" (the drive's name first, a no-break blank before the "›")."""
    m = re.fullmatch(r"/Users/[^/]+(/.*)?", path)
    if m:
        return f"~{m.group(1)}" if m.group(1) and m.group(1) != "/" else "~"
    segs = path.rstrip("/").split("/")
    if len(segs) > 2 and segs[0] == "" and segs[1] == "Volumes" and segs[2]:
        rest = "/".join(s for s in segs[3:] if s)
        return f"{segs[2]} › {rest}" if rest else segs[2]
    return path


def sidebar(state: dict, lines: Sequence[pf.Row], todo_count: int, warnings: bool = False, *,
            records: Mapping[str, PlaylistRecord] | None = None, favourites: Sequence[str] = (),
            overrides: Mapping[str, bool] | None = None, watched: Sequence[WatchedFolder] = (),
            away: Mapping[int, str] | None = None) -> dict:
    """The sidebar's numbers (plan library stage 5, I4). `lines`: every playlist line of playlists.txt in file order,
    switched-off ones too (playlists_file.load(...).rows). A playlist's `songs` are the distinct songs of its read
    record (D5: a token resolves through a song's key or alias; one never read has None); `records`:
    db.playlist_records. `library_folders` are the folders of Library/ that no line uses, by name, with their path
    and the files at or below, found by the file's place (`Sites.library_folder`), as the folder view lists them. `watched`: db.watched_folders (the Library among them is left out), `away`: folder id
    -> why it isn't there (scanner.away_reason); `watched` entries come by name, each with its crates (`crates`,
    `overrides` = db.crate_overrides). `favourites`: db.favourites; a key whose playlist or folder is gone is left
    out (stored as it is), the rest come resolved in the stored order."""
    records = records or {}
    with_file = tracks_with_file(state)
    # the Library folders by the place of the file, as the folder view lists it (`Sites.library_folder`; D5)
    counts: dict[str, int] = {}
    site = Sites({}, {}, {}, {})
    for e in with_file:
        if (name := site.library_folder(e["path"])) is not None:
            counts[name] = counts.get(name, 0) + 1
    resolve = _resolver(state)

    def songs(ref: str) -> int | None:
        record = records.get(ref)
        return None if record is None else len({resolve(t.token) for t in record.tracks})

    used = {fold(r.folder) for r in lines}
    playlists = [{"name": r.folder, "ref": r.ref, "service": r.service, "enabled": r.enabled, "songs": songs(r.ref)}
                 for r in lines]
    library_folders = [{"path": f"Library/{n}", "name": n, "files": counts[n]}
                       for n in sorted((n for n in counts if fold(n) not in used), key=lambda n: (fold(n), n))]
    imports = sorted((f for f in watched if f.kind == "import"), key=lambda f: (fold(f.path.name or str(f.path)), str(f.path)))
    found = crates([e["path"] for e in with_file], [str(f.path) for f in imports], overrides or {})
    paths = [PurePosixPath(e["path"]) for e in with_file]
    entries = []
    for f in imports:
        root = PurePosixPath(str(f.path))
        entries.append({"path": str(f.path), "name": root.name or str(f.path), "place": place(str(f.path)),
                        "files": sum(1 for p in paths if p != root and p.is_relative_to(root)),
                        "state": FOLDER_STATE.get((away or {}).get(f.id), "here"), **found[str(f.path)]})
    targets: dict[str, dict] = {}
    for p in playlists:
        targets[f"playlist:{p['ref']}"] = {"kind": "playlist", "name": p["name"], "service": p["service"],
                                           "enabled": p["enabled"], "count": p["songs"], "path": None,
                                           "state": "here"}
    for lf in library_folders:
        targets[f"folder:{lf['path']}"] = {"kind": "folder", "name": lf["name"], "service": None, "enabled": True,
                                           "count": lf["files"], "path": lf["path"], "state": "here"}
    for w in entries:
        targets[f"folder:{w['path']}"] = {"kind": "folder", "name": w["name"], "service": None, "enabled": True,
                                          "count": w["files"], "path": w["path"], "state": w["state"]}
        for c in w["crates"]:
            targets[f"folder:{c['path']}"] = {"kind": "folder", "name": c["label"], "service": None, "enabled": True,
                                              "count": c["files"], "path": c["path"], "state": w["state"]}
    return {"todo": todo_count, "all_tracks": len(with_file),
            "not_in_playlist": sum(1 for e in with_file if not e.get("in_playlists")), "limits_warning": warnings,
            "favourites": [{"key": k, **targets[k]} for k in dict.fromkeys(favourites) if k in targets],
            "playlists": playlists, "watched": entries, "library_folders": library_folders}


# --- to-do ---

TODO_GROUPS = [("rekordbox_check", "Check in rekordbox", "the file changed; rekordbox needs a hand"),
               ("same_song", "Is this the same song?", "a file of yours might be a playlist song"),
               ("duplicate", "Duplicates", "the same song more than once"),
               ("upgrade_ready", "Upgrade ready", "a better version is waiting for you"),
               ("not_found", "Not found", "nothing usable anywhere"),
               ("weak", "Weak (≤ 17 kHz)", "audibly lossy"),
               ("good_lossy", "Good lossy (~20 kHz)", "hard to hear"),
               ("fake", "Fake lossless", "the Qobuz file is really lossy"),
               ("other", "Other", "something is in the way")]


FREE_GROUPS = ("not_found", "weak", "good_lossy", "fake")  # where an artist's free download is worth a tag


def _group(e: dict) -> str | None:
    if not sound_checked(e):  # its quality is only the codec's guess: nothing to do about it yet
        return None
    if e.get("upgrade"):
        return "upgrade_ready"
    return {"missing": "not_found", "weak": "weak", "good_lossy": "good_lossy", "fake": "fake"}.get(quality_class(e))


def _detail(group: str, e: dict, today: date, other: str | None) -> str:
    if group == "upgrade_ready":
        return upgrade_status(e["upgrade"], swap_possible(e))
    if group == "not_found":
        when = next_check(e, today)
        if when is None or when == "next_sync":
            return "tried again at the next sync"
        days = (date.fromisoformat(when) - today).days
        return f"next try in {days} day{'s' if days != 1 else ''}"
    if group == "other":
        return other or ""
    # the badge already says the kHz: where it came from, and how many kbps for a lossy download
    source = SHORT_OWN if is_own_file(e) else SHORT_SOURCE.get(e.get("source") or "", "")
    kbps = f"{e['source_kbps']} kbps" if e.get("source_kbps") and e["status"] == "not_lossless" else ""
    return " · ".join(x for x in (source, kbps) if x)


# W8 (plan library stage 4 I12): why a file of the user's own might be a playlist song, and what the duplicates are
QUESTION_ARTIST = "Same title, different artist"
QUESTION_NO_ARTIST = "Same title, no artist in your file"
QUESTION_LONGER = "Same artist and title, {s} s longer"
QUESTION_SHORTER = "Same artist and title, {s} s shorter"
QUESTION_NO_LENGTH = "Same artist and title, the length couldn't be read"
DUPLICATE_AUDIO = "The same audio in {n} files"
DUPLICATE_SONG = "{n} files of the same song"


def question_why(q: Question) -> str:
    """The words for a question's `why` (the file side's length is `delta_s` seconds longer or shorter)."""
    if q.why == "artist":
        return QUESTION_ARTIST
    if q.why == "no_artist":
        return QUESTION_NO_ARTIST
    if q.why == "no_length" or q.delta_s is None:
        return QUESTION_NO_LENGTH
    return (QUESTION_LONGER if q.delta_s > 0 else QUESTION_SHORTER).format(s=abs(q.delta_s))


def file_side(file_id: int, song_key: str | None, path: str, e: dict | None, quality_of: dict, online: bool,
              in_playlist: bool, audio: Url | None = None) -> dict:
    """FileSide: one file of a question or a duplicate group. `e`: the entry of its song (names and length; None when
    the file is linked to no song: the file's name stands in); `quality_of`: the file's own status and cutoff (a
    song's entry can describe another file)."""
    name = e if e is not None else {"artist": "", "title": PurePosixPath(path).stem, "duration_ms": None}
    q = {"status": quality_of.get("status"), "cutoff_hz": quality_of.get("cutoff_hz")}
    return {"file_id": file_id, "song_key": song_key, "path": path, "artist": name["artist"] or "",
            "title": name["title"] or "", "duration_s": round((name.get("duration_ms") or 0) / 1000, 1),
            "quality": quality_class(q), "quality_label": quality_label(q), "online": online,
            "audio_url": audio(song_key or "", {"path": path, "file_id": file_id}) if audio and online else None,
            "in_playlist": in_playlist}


def _question_item(q: Question, state: dict, cover: Url | None, audio: Url | None,
                   away: Mapping[str, str] | None = None) -> dict | None:
    """The To-do item of a question; None when its own song is gone from the records (answered or removed since)."""
    own = state["tracks"].get(q.own_key)
    if own is None or not own.get("path"):
        return None
    stored = state["tracks"].get(q.song_key)
    track = q.track
    e = stored if stored is not None else {
        "artist": track.first_artist, "title": track.title, "folder": q.folder, "duration_ms": track.duration_ms,
        "status": "missing", "cutoff_hz": None, "source": None, "in_playlists": True, "hidden": False, "upgrade": None,
        "path": None, "added": None}
    side = file_side(q.file_id, q.own_key, own["path"], own, own, file_online(own, away), False, audio)
    pair = {"song_key": q.song_key, "own_key": q.own_key, "why": q.why, "delta_s": q.delta_s,
            "track": {"artist": track.first_artist, "title": track.title,
                      "duration_s": round((track.duration_ms or 0) / 1000, 1), "folder": q.folder, "link": track.link},
            "file": side}
    return {**track_row(q.song_key, e, cover), "group": "same_song", "detail": question_why(q), "free": False,
            "pair": pair}


def _duplicate_item(g: DuplicateGroup, files: Sequence[DupFile], state: dict, cover: Url | None,
                    audio: Url | None, away: Mapping[str, str] | None = None) -> dict | None:
    """The To-do item of a duplicate group; None unless every file of it is there to act on (online now, not held)."""
    online = {f.file_id: file_online({"path": f.path, "online": f.online}, away) for f in files}
    if len(files) != len(g.file_ids) or len(files) < 2 or not all(online[f.file_id] and f.usable for f in files):
        return None
    sides = []
    for f in sorted(files, key=lambda f: f.file_id):
        e = state["tracks"].get(f.song_key) if f.song_key else None
        sides.append(file_side(f.file_id, f.song_key, f.path, e, {"status": f.status, "cutoff_hz": f.cutoff_hz},
                               online[f.file_id], f.in_playlists, audio))
    first = next((s for s in sides if s["in_playlist"]), sides[0])  # the playlist song's file names the group
    e = state["tracks"].get(first["song_key"]) if first["song_key"] else None
    row = {"track_id": g.id, "artist": first["artist"], "title": first["title"], "folder": (e or {}).get("folder") or "",
           "duration_s": first["duration_s"], "status": (e or {}).get("status") or "lossless",
           "quality": first["quality"], "quality_label": first["quality_label"],
           "cutoff_hz": (e or {}).get("cutoff_hz"), "source": None, "source_name": None,
           "in_playlists": first["in_playlist"], "hidden": False, "upgrade_ready": False, "path": first["path"],
           "added": None, "cover_url": cover(first["song_key"], {"path": first["path"]}) if cover and first["song_key"]
           else None}
    n = len(sides)
    keep, why = recommend(files)
    return {**row, "group": "duplicate", "detail": (DUPLICATE_AUDIO if g.why == "same_audio" else DUPLICATE_SONG).format(n=n),
            "free": False, "pair": {"group_id": g.id, "why": g.why, "files": sides, "recommended": keep,
                                     "recommended_why": why}}


RECOMMEND_QUALITY = "Recommended: best quality"
RECOMMEND_AIFF = "Recommended: AIFF keeps tags"


def _sound_rank(f: DupFile) -> tuple:
    """How good a duplicate's audio is, higher better: lossless before lossy, then the higher cutoff."""
    return (f.status == "lossless", f.cutoff_hz or 0)


def _is_aiff(f: DupFile) -> bool:
    return PurePosixPath(f.path).suffix.lower() in (".aiff", ".aif")


def recommend(files: Sequence[DupFile]) -> tuple[int | None, str | None]:
    """Which file of a duplicate group the panel picks for the user to keep, and why in one line; (None, None) when
    there is no clear winner. Only the files themselves decide: the better sound (lossless before lossy, then the
    higher cutoff), then AIFF before any other format (it keeps rekordbox's tags). Being in a playlist or inside
    Library/ breaks no tie: which copy rekordbox uses is the user's knowledge, not the app's."""
    if len(files) < 2:
        return None, None
    ranked = sorted(files, key=lambda f: (_sound_rank(f), _is_aiff(f)), reverse=True)
    best, second = ranked[0], ranked[1]
    if _sound_rank(best) != _sound_rank(second):
        return best.file_id, RECOMMEND_QUALITY
    if _is_aiff(best) and not _is_aiff(second):
        return best.file_id, RECOMMEND_AIFF
    return None, None


def todo(state: dict, filt: str, show_hidden: bool, others: dict[str, str], today: date,
         cover: Url | None = None, questions: Sequence[Question] = (), duplicates: Sequence[DuplicateGroup] = (),
         dup_files: Mapping[str, Sequence[DupFile]] | None = None, audio: Url | None = None,
         counted: Collection[str] = (), away: Mapping[str, str] | None = None) -> dict:
    """Groups in this order: Check in rekordbox, Is this the same song?, Duplicates, Upgrade ready, Not found, Weak,
    Good lossy, Fake lossless, Other. `others`: track id -> what blocks it (a move blocked by another file, several
    files that could be it). Hidden tracks are left out unless show_hidden. "Check in rekordbox" lists every track
    with a `rekordbox_check`, hidden or not, so a track can be in two groups; chips["all"] counts each track once.

    The import's (plan library stage 4): `questions` are the plan's "Is this the same song?" (a playlist song a file
    of the user's own might be; the song waits for the answer, so it is not listed as Not found meanwhile).
    `duplicates` are the plan's same-song groups and db.duplicate_groups' same-audio ones together, `dup_files` their
    files (db.group_files); a group in both shows once, as the same audio. D8: the user's own songs are only on
    To-do under Upgrade ready, in a question and in a duplicate group; their quality (Weak, Good lossy, Fake) is
    for the Library to show. `counted`: ids of duplicate groups that are known to be there to act on (every file
    online and not held, as db.duplicate_groups finds them): they count in chips["all"] but are not listed, so the
    sidebar's count needs no `dup_files` for them. `away`: root -> why for the import folders that are not there now
    (file_state). It decides everything that depends on a file being there: a question's side sends `online: false`
    and a duplicate group with a file in one is neither listed nor counted, even if the rows still say online (no
    scan has seen the drive go)."""
    items: dict[str, list] = {g: [] for g, _, _ in TODO_GROUPS}
    never = state.get("never") or {}  # "never download": not a to-do
    hidden = 0
    listed: set[str] = set()
    held: set[str] = set()  # playlist songs waiting for an answer: not Not found meanwhile
    for q in questions:
        if (item := _question_item(q, state, cover, audio, away)) is not None:  # none: the question went stale, no wait
            items["same_song"].append(item)
            listed.add(q.song_key)
            held.add(q.song_key)
    groups_by_id: dict[str, DuplicateGroup] = {}
    for g in duplicates:
        if g.id not in groups_by_id or g.why == "same_audio":
            groups_by_id[g.id] = g
    for g in groups_by_id.values():
        if g.id in counted:
            listed.add(g.id)
        elif (item := _duplicate_item(g, (dup_files or {}).get(g.id, ()), state, cover, audio, away)) is not None:
            items["duplicate"].append(item)
            listed.add(g.id)
    for k, e in state["tracks"].items():
        if e.get("rekordbox_check"):
            items["rekordbox_check"].append({**track_row(k, e, cover), "group": "rekordbox_check",
                                             "detail": check_status(e["rekordbox_check"]),
                                             "check": check_view(e["rekordbox_check"]), "can_undo": can_undo(e)})
            listed.add(k)
        if k in held or (not e.get("in_playlists") and not (is_own(k) and e.get("upgrade"))) \
                or (e["status"] == "missing" and k in never):
            continue
        group = _group(e) or ("other" if k in others else None)
        if group is None:
            continue
        if e.get("hidden"):
            hidden += 1
            if not show_hidden:
                continue
        items[group].append({**track_row(k, e, cover), "group": group,
                             "detail": _detail(group, e, today, others.get(k)),
                             "free": group in FREE_GROUPS and bool(free_downloads(e))})
        listed.add(k)
    for rows in items.values():
        rows.sort(key=lambda r: (fold(r["folder"]), fold(r["artist"]), fold(r["title"])))
    chips = {"all": len(listed), **{g: len(v) for g, v in items.items()}}
    groups = [{"key": g, "label": label, "hint": hint, "items": items[g]} for g, label, hint in TODO_GROUPS
              if items[g] and (filt in (None, "all") or filt == g)]
    empty = None
    if not chips["all"]:
        empty = "all_lossless" if not hidden else "all_hidden"
    elif not groups:
        empty = "nothing_here"
    return {"chips": chips, "hidden_count": hidden, "show_hidden": show_hidden, "groups": groups, "empty": empty}


def todo_others(prep, last_report: dict | None) -> dict[str, str]:
    """Track id -> what blocks it: conflicts of the last run, ambiguous files of the preview."""
    out = {}
    for r in (last_report or {}).get("results") or []:
        if r.get("section") == "conflicts" and r.get("track_id"):
            out[r["track_id"]] = "MOVE BLOCKED · a file is in the way"
    for key, _track, _folder, _files in (prep.plan.ambiguous if prep else []):
        out[key] = "SEVERAL FILES · could be this track, nothing done"
    return out


# --- sync screen, before the start ---

OWN_MUSIC = "Your own music"  # the name of an own song's folder when its file's place can't be told


def action_folder(a, e: dict | None, where: Callable[[str], str] | None = None) -> str:
    """The playlist or folder an action is listed under, never empty. A playlist song has its playlist's folder; an
    own song (an upgrade check of an imported file, no playlist) has none, so it goes by the folder its file sits in,
    named as the rest of the app names it (`Sites.place`: "Techno", "Rekordbox Library › Hardtechno")."""
    if a.folder:
        return a.folder
    path = e.get("path") if e else None
    return (where(path) if where and path else "") or OWN_MUSIC


def action_row(a, state: dict, cover: Url | None = None, where: Callable[[str], str] | None = None) -> dict:
    e = state["tracks"].get(a.track_id)
    artist, title = (e["artist"], e["title"]) if e else (a.track.first_artist, a.track.title)
    to_dir = a.dest_dir or f"Library/{a.folder}"
    return {"key": [a.kind, a.track_id, to_dir], "kind": a.kind, "reason": a.reason or None,
            "track_id": a.track_id, "artist": artist, "title": title, "folder": action_folder(a, e, where),
            "to_dir": to_dir, "to_not_lossless": to_dir.endswith("/not_lossless"),
            "src": a.src, "cover_url": cover(a.track_id, e) if cover and e else a.track.image_url}


def sync_preview(store, state: dict, settings: Settings, today: date, now: datetime, reading: bool,
                 cover: Url | None = None, logins: Sequence[tuple[str, bool]] = (),
                 where: Callable[[str], str] | None = None) -> dict:
    """The check before the start: every planned action in groups, each with the key the page sends back ticked.
    `where`: a file's path -> its folder's name (`Sites.place`), for the own songs that belong to no playlist."""
    prep = store.prep
    status = read_status(store, now, reading, logins)
    if prep is None:
        return {"read_status": status, "counts": None, "groups": [], "estimate": None, "never": [], "folders": [],
                "in_playlists": None, "ambiguous": [], "dropped": [], "notes": [], "empty": "no_preview",
                "waiting_answers": 0, "deferred_checks": 0}
    plan_state = prep.state
    m = moneys(state, settings, today)
    todo, never = planned(prep, state)
    groups: dict[str, list] = {}
    for a in todo:
        groups.setdefault(f"acquire:{a.reason}" if a.kind == "acquire" else a.kind, []).append(a)
    in_playlists = {t.key for fp in prep.fetched for t in fp.tracks}
    run_index = {id(a): i for i, a in enumerate(todo)}  # the order the sync works through them
    return {"read_status": status, "counts": plan_counts(todo),
            "groups": [{"key": key, "label": label,
                        "actions": [{**action_row(a, plan_state, cover, where), "run": run_index[id(a)]} for a in groups[key]]}
                       for key, label in PLAN_LABELS if key in groups],
            "estimate": sync_estimate(todo, m),
            "never": [action_row(a, plan_state, cover, where) for a in never],
            "folders": [line.folder for line in prep.lines],
            "in_playlists": len(in_playlists),
            "ambiguous": [{"track_id": key, "artist": t.first_artist, "title": t.title, "folder": folder,
                           "files": files} for key, t, folder, files in prep.plan.ambiguous],
            "dropped": [{"track_id": k, "artist": plan_state["tracks"][k]["artist"],
                         "title": plan_state["tracks"][k]["title"], "folder": plan_state["tracks"][k]["folder"]}
                        for k in prep.plan.dropped],
            "notes": list(prep.plan.notes), "empty": None if todo else "up_to_date",
            # W9: songs held for "Is this the same song?", first upgrade checks of imported music the cap left for later
            "waiting_answers": len({q.song_key for q in prep.plan.questions}),
            "deferred_checks": prep.plan.deferred_checks}


# --- watched folders (Settings, Setup; plan library stage 4 I11) ---

AWAY_STATE = {"unmounted": "offline", "missing": "missing"}  # scanner.away_reason -> a watched folder row's state


def watched_folders(folders: Sequence[WatchedFolder], counts: Mapping[int, ImportCounts], away: Mapping[int, str],
                    library_files: int, unreadable: Sequence[tuple[PurePosixPath, str]], waiting: int, stopped: bool,
                    phase: str | None, crates: Mapping[str, dict] | None = None) -> dict:
    """The watched folders and how far their import is. `folders`: db.watched_folders (the Library first); `counts`:
    db.import_counts; `away`: folder id -> why its path isn't there now ("unmounted" |
    "missing", scanner.away_reason); `library_files`: the Library's file
    count; `unreadable`: db.import_unreadable (path, reason); `waiting`: db.import_left, the files an import would work
    through now (offline drives' left out); `stopped`: the user stopped an import this session (Continue import);
    `phase`: the running import's phase (ImportProgress.phase), None when none runs; `crates`: `crates()`' answer by
    folder path (Settings' switches): each import row gets `crates` (all of them, label order) and `too_many`, the
    Library row none ([], False).

    Row state: offline (its drive isn't connected) or missing (the folder isn't found: moved, renamed or deleted),
    whatever else; the rows are kept either way. Then scanning (an import is looking for files), importing
    (one runs and this folder has files it hasn't finished), else online. Row `waiting`: files of the folder the
    import still works through (not read yet, or read and not yet sound-checked); `unreadable`: files it couldn't read.
    The Library row counts both the same way (`counts` holds its entry), its unreadable files are in the list with
    its id."""
    roots = {f.id: PurePosixPath(str(f.path)) for f in folders}
    rows = []
    for f in folders:
        c = counts.get(f.id) or ImportCounts(0, 0, 0, 0)
        left = c.waiting + c.identified
        if f.kind == "library":
            rows.append({"id": f.id, "path": str(f.path), "name": "Library", "kind": "library",
                         "state": "scanning" if phase == "scan" else "online", "files": library_files,
                         "waiting": left, "unreadable": c.unreadable, "crates": [], "too_many": False})
            continue
        state = (AWAY_STATE[away[f.id]] if f.id in away else "scanning" if phase == "scan"
                 else "importing" if phase is not None and left else "online")
        found = (crates or {}).get(str(f.path)) or {}
        rows.append({"id": f.id, "path": str(f.path), "name": roots[f.id].name or str(f.path), "kind": "import",
                     "state": state, "files": c.files, "waiting": left, "unreadable": c.unreadable,
                     "crates": found.get("crates", []), "too_many": found.get("too_many", False)})

    def owner(path: PurePosixPath) -> int | None:
        inside = [i for i, root in roots.items() if path.is_relative_to(root)]
        return max(inside, key=lambda i: len(roots[i].parts), default=None)

    return {"folders": rows,
            "unreadable": [{"folder_id": owner(PurePosixPath(str(p))), "path": str(p), "reason": reason}
                           for p, reason in unreadable],
            "waiting": waiting, "stopped": stopped}


# --- playlists ---

def _entries_by_id(state: dict) -> dict:
    """State entries by state key and by every alias (a Spotify id the entry also answers to)."""
    by_id = {}
    for k, e in state["tracks"].items():
        by_id[k] = e
        for alias in e.get("aliases") or []:
            by_id[alias] = e
    return by_id


def _spotify_row(track_id: str, t, e: dict | None, cover: Url | None, never: dict | None = None) -> dict:
    """A track of a Spotify playlist for the playlists panel: name, cover, and whether it has a file yet."""
    artist = e["artist"] if e else t.first_artist if t else ""
    title = e["title"] if e else t.title if t else track_id
    url = cover(track_id, e or {}) if cover else None
    return {"track_id": track_id, "artist": artist, "title": title, "cover_url": url or (t.image_url if t else None),
            "downloaded": bool(e and e.get("path")), "quality": quality_class(e) if e else "missing",
            "quality_label": quality_label(e) if e else None, "never": track_id in (never or {})}


def _quality_of_tracks(tracks: list, state: dict) -> dict:
    by_id = _entries_by_id(state)
    by = {q: 0 for q in QUALITIES}
    for t in tracks:
        e = by_id.get(t.key)
        by[quality_class(e) if e else "missing"] += 1
    return by


def info_dict(info) -> dict | None:
    """hint: the words of the playlist's service for a playlist it won't let Discjockey read (the page shows them
    next to a row it can't read)."""
    if info is None:
        return None
    return {"name": info.name, "owner_name": info.owner_name, "yours": info.yours,
            "collaborative": info.collaborative, "readable": info.readable, "image_url": info.image_url,
            "track_count": info.track_count, "hint": SOURCES[info.service].UNREADABLE_HINT}


# --- tidy-up: the words of the preview, the move log and the results (plan library stage 2, I5, I6) ---

SAVE_HEADLINE = "{n} files would sit in a different folder"
SAVE_HEADLINE_ONE = "1 file would sit in a different folder"
RENAME_OPTION = "Rename the folder on disk too"
TIDY_EMPTY = "Every file is where the playlist order puts it."
TIDY_ONLY_YOURS = "{n} files are where you put them, not where the playlist order puts them."
TIDY_ONLY_YOURS_ONE = "1 file is where you put it, not where the playlist order puts it."
TIDY_YOURS_MARK = "You put this here"
TIDY_YOURS_HEADER = "You put these here"
TIDY_YOURS_CONTROL = "Put these in playlist order too"
REKORDBOX_NOTES = ["rekordbox may show the moved tracks as missing.",
                   "Its Relocate finds them again by file name: Discjockey never renames them."]
UNDO_NOTE = "You can undo this on this page."
UNDO_WARN = ("{n} files go back to where they were. rekordbox may show them as missing again; Relocate finds them "
             "by file name.")
UNDO_WARN_ONE = ("1 file goes back to where it was. rekordbox may show it as missing again; Relocate finds it "
                 "by file name.")
UNDO_RENAME = "The folder goes back to its old name {old}, with everything in it, and the playlist is called {old} again."
FOLDER_TAKEN = "A folder called {new} is already in your Library."
FOLDER_IN_USE = "{old} is still the folder of another playlist."
# an undone rename finds `Library/{old}` taken or a playlist called {old}: tidy.py marks both `place_taken` and
# tells them apart in the detail (tidy.FOLDER_THERE, tidy.NAME_USED)
PLACE_TAKEN_FOLDER = "A folder called {old} is in your Library again."
PLACE_TAKEN_NAME = "Another playlist is called {old} now."
PLACE_TAKEN_EITHER = "A folder or another playlist is called {old} now."
BATCH_TITLES = {"tidy": "Tidy-up", "save": "Saved playlists"}


def folder_of(path: str) -> str:
    """The folder of a snapshot path relative to `Library/`: `Library/F/x` -> `F`, `Library/x` -> `` (the Library)."""
    return path.removeprefix("Library/").rpartition("/")[0]


def _rel(path: str) -> str:
    return path.removeprefix("Library/")


def _where(folder: str) -> str:
    return folder or "Library"


def skip_text(reason: str | None, detail: str | None, *, to: str, old: str | None = None,
              new: str | None = None, frm: str | None = None) -> str:
    """The words for a skip reason. `to` is the target folder (relative to `Library/`); a folder move passes the
    folder's `old` and `new` names (an undo's `old` is where it goes back to, `new` the name it has now) and `frm`,
    the folder it leaves. A refused folder rename carries `rename_offer`'s code in `detail` (`tidy.OFFER_SKIP`),
    worded here."""
    if frm is not None and detail == "folder_taken":
        return FOLDER_TAKEN.format(new=to)
    if frm is not None and detail == "folder_in_use":
        return FOLDER_IN_USE.format(old=frm)
    if reason == "offline":
        return "Offline, skipped"
    if reason == "not_found":
        return "Not where Discjockey last saw it"
    if reason == "name_taken":
        return f"A file with this name is already in {_where(to)}"
    if reason == "changed":
        return "Changed since the list was shown"
    if reason == "failed":
        return f"Couldn't move it: {detail}" if detail else "Couldn't move it"
    if reason == "stopped":
        return "Not moved: the moves were stopped first"
    if reason == "moved_on":
        return f"The folder {new} isn't there any more" if new is not None else "Moved or changed since"
    if reason == "place_taken":
        if old is None:
            return "Another file is in its old place now"
        return {"folder_there": PLACE_TAKEN_FOLDER, "name_used": PLACE_TAKEN_NAME}.get(
            detail or "", PLACE_TAKEN_EITHER).format(old=old)
    if reason == "playlist_renamed":
        return f"The playlist isn't called {new} any more"
    return "Not moved"


def _ends(kind: str, src: str, dst: str) -> tuple[str, str, str | None, str | None]:
    """(from, to, old, new) of a move for the words: folders for a file, the folder names for a folder move (old and
    new as an undo has them: where it goes back to, the name it has now)."""
    if kind == "folder":
        return _rel(src), _rel(dst), _rel(dst), _rel(src)
    return folder_of(src), folder_of(dst), None, None


def _skip_words(kind: str, src: str, dst: str, reason: str | None, detail: str | None) -> str:
    frm, to, old, new = _ends(kind, src, dst)
    return skip_text(reason, detail, to=to, old=old, new=new, frm=frm if kind == "folder" else None)


def tidy_row(row: TidyRow, e: dict, cover: Url | None = None, by_rename: str | None = None) -> dict:
    """One row of the tidy preview (I5 `TidyRowJSON`). `yours`: placed by the user or by an import."""
    frm, to = folder_of(row.src), folder_of(row.dst)
    return {**track_row(row.track_id, e, cover), "file_id": row.file_id, "from": frm, "to": to,
            "from_path": row.src, "placed_by": row.placed_by, "ticked": row.ticked,
            "yours": row.placed_by in ("user", "import"),
            "skip": {"reason": row.skip, "text": skip_text(row.skip, None, to=to)} if row.skip else None,
            "by_rename": by_rename}


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


def tidy_preview(rows: list[TidyRow], state: dict, cover: Url | None = None) -> dict:
    """The "Tidy up files" preview. Rows ticked by default are those a tidy-up moves for sure; `yours` rows
    (the user's own placement) are listed apart, with one control that ticks them all (plan P1)."""
    out = [tidy_row(r, state["tracks"][r.track_id], cover) for r in rows]
    ticked = sum(1 for r in out if r["ticked"])
    movable_yours = sum(1 for r in out if r["yours"] and not r["skip"])
    if not out:
        empty = TIDY_EMPTY
    elif not ticked and movable_yours:
        empty = _plural(movable_yours, TIDY_ONLY_YOURS_ONE, TIDY_ONLY_YOURS)
    else:
        empty = None
    yours = sum(1 for r in out if r["yours"])
    return {"rows": out, "ticked": ticked, "rekordbox": list(REKORDBOX_NOTES), "undo_note": UNDO_NOTE, "empty": empty,
            "yours": {"count": yours, "movable": movable_yours, "mark": TIDY_YOURS_MARK,
                      "header": TIDY_YOURS_HEADER, "control": TIDY_YOURS_CONTROL} if yours else None}


def batch_title(b: BatchRow, undone_title: str | None = None) -> str:
    """"Tidy-up", "Saved playlists", "Renamed A to B", "Undo of: <the title of the batch it undid>" (`undone_title`;
    "Undo" when it isn't known)."""
    if b.started_by == "rename":
        about = b.about
        return f"Renamed {about['from']} to {about['to']}" if about else "Renamed a folder"
    if b.started_by == "undo":
        return f"Undo of: {undone_title}" if undone_title else "Undo"
    return BATCH_TITLES.get(b.started_by, "Moves")


def _summary(moved: int, skipped: int) -> str:
    text = _plural(moved, "1 file moved", "{n} files moved")
    return f"{text} \u00b7 {skipped} not moved" if skipped else text


def move_batches(rows: list[BatchRow], total: int, titles: Mapping[int, str] | None = None) -> dict:
    """`titles`: batch id -> title for undone batches that are not among `rows` (older than the 20 listed)."""
    by_id = {b.id: b for b in rows}

    def title(b: BatchRow) -> str:
        if b.started_by != "undo":
            return batch_title(b)
        target = by_id.get(b.undoes)
        return batch_title(b, title(target) if target else (titles or {}).get(b.undoes))

    return {"batches": [{"id": b.id, "at": b.started, "title": title(b),
                         "moved": b.moved, "skipped": b.skipped, "undoable": b.undoable,
                         "undone_by": b.undone_by, "summary": _summary(b.moved, b.skipped)} for b in rows],
            "total": total}


def _skipped_item(m: MoveRow) -> dict:
    frm, to, _, _ = _ends(m.kind, m.src, m.dst)
    return {"label": m.label, "from": frm, "to": to, "reason": m.reason,
            "text": _skip_words(m.kind, m.src, m.dst, m.reason, m.detail)}


def batch_result(r: BatchResult, title: str) -> dict:
    """What a finished batch tells the page: "Moved 3 files." (undo: "... back."), then "2 not moved:" and the list."""
    back = " back" if r.started_by == "undo" else ""
    headline = _plural(r.moved, f"Moved 1 file{back}.", "Moved {n} files" + back + ".")
    if r.skipped:
        headline += f" {len(r.skipped)} not moved:"
    return {"batch_id": r.batch_id, "title": title, "moved": r.moved, "headline": headline,
            "skipped": [_skipped_item(m) for m in r.skipped], "stopped": r.stopped}


def undo_preview(batch: BatchRow, moves: list[PlannedMove], files: Iterable[str] = (),
                 title: str | None = None) -> dict:
    """What an undo would do (`moves` as `tidy.undo_preview` plans them, some already skipped with a reason).
    `files` are the snapshot paths on disk: a folder move carries every file under the folder it moves back.
    A row is `kind` "file" or "folder"; a folder row has `files`, how many files are in it now (else the count
    the move carried), a file row has `files` null."""
    on_disk = list(files)
    rows = []
    for m in moves:
        frm, to, _, _ = _ends(m.kind, m.src, m.dst)
        reason, detail = m.skip or (None, None)
        inside = sum(1 for f in on_disk if f.startswith(f"{m.src}/")) if m.kind == "folder" else 0
        rows.append({"label": m.label, "kind": m.kind, "from": frm, "to": to,
                     "files": (inside or m.files) if m.kind == "folder" else None,
                     "skip": {"reason": reason, "text": _skip_words(m.kind, m.src, m.dst, reason, detail)}
                     if reason else None})
    running = [m for m, r in zip(moves, rows) if r["skip"] is None]
    # a folder's files sit under its current name, `src`
    moving = sum(1 if m.kind == "file" else r["files"] or 0 for m, r in zip(moves, rows) if r["skip"] is None)
    warning = [_plural(moving, UNDO_WARN_ONE, UNDO_WARN)] if moving else []
    folder = next((m for m in running if m.kind == "folder"), None)
    if folder is not None:
        warning.append(UNDO_RENAME.format(old=_rel(folder.dst)))
    return {"batch_id": batch.id, "title": title if title is not None else batch_title(batch), "rows": rows,
            "moving": moving, "warning": warning, "nothing_left": not running}


def playlists(loaded: pf.Loaded, tracks_by_id: dict, infos: dict, state: dict, cover: Url | None = None) -> dict:
    rows = []
    for i, r in enumerate(loaded.rows):
        tracks = tracks_by_id.get(r.ref)
        info = infos.get(r.ref)
        rows.append({"index": i, "folder": r.folder, "link": r.link, "playlist_id": r.ref,
                     "service": r.service, "service_name": PLAYLIST_SERVICES[r.service], "enabled": r.enabled,
                     "info": info_dict(info),
                     "tracks": len(tracks) if tracks is not None else (info.track_count if info else None),
                     "quality": _quality_of_tracks(tracks, state) if tracks is not None else None})
    by_id = _entries_by_id(state)
    overlap = [{**_spotify_row(t.key, t, by_id.get(t.key), cover, state.get("never")), "folders": folders,
                "lands_in": lands}
               for t, folders, lands in pf.overlaps(loaded.rows, tracks_by_id)]
    return {"version": loaded.version, "problem": loaded.problem, "rows": rows, "overlaps": overlap,
            "empty": None if loaded.rows else "no_playlists", "tidy": {"waiting": out_of_place(state)}}


CHECK_NO_DOWNLOADS = "No downloads, no Qobuz quota used"
CHECK_NOTHING_DELETED = "Nothing is deleted"
CHECK_NEXT_SYNC = "Happens at the next sync, not right away"
CHECK_CHOICE = "Files move only if you choose to"
CHECK_UNDO = "Moves can be undone on this page"


# tidy.rename_offer(old, new, rows, library_dirs, *, pairs): None, or a reason code
RenameOffer = Callable[..., "str | None"]


def _rename_items(pairs: list[tuple[str, str]], rows: list, files: list[str], library_dirs: Collection[str],
                  rename_offer: RenameOffer) -> list[dict]:
    """The on-disk folder renames this save could do, with the files each would carry along. `pairs` go to the offer
    as well (all renames of the change), so what is offered is never refused when it runs. A folder that isn't in
    the Library (`no_folder`) has nothing to rename and is left out."""
    items = []
    for was, now in pairs:
        why = rename_offer(was, now, rows, library_dirs, pairs=pairs)
        if why == "no_folder":
            continue
        n = sum(1 for f in files if fold(f).startswith(fold(f"Library/{was}/")))  # the rename finds it case-blind too
        text = {"folder_taken": FOLDER_TAKEN.format(new=now), "folder_in_use": FOLDER_IN_USE.format(old=was)}
        items.append({"from": was, "to": now, "files": n, "offered": why is None,
                      "why_not": None if why is None else text.get(why), "option": RENAME_OPTION,
                      "detail": f"One folder move instead of {n} file move{'s' if n != 1 else ''}."})
    return items


def _by_rename(row: TidyRow, pairs: list[tuple[str, str]]) -> str | None:
    """The old folder name whose rename on disk would put this row's file at its target, else None."""
    src, dst = fold(row.src), fold(row.dst)
    for was, now in pairs:
        prefix = fold(f"Library/{was}/")
        if src.startswith(prefix) and dst == fold(f"Library/{now}/") + src[len(prefix):]:
            return was
    return None


def playlist_change(old: list, new: list, tracks_by_id: dict, state: dict, files: list[str], today: date,
                    money: dict | None, cover: Url | None = None, *, library_dirs: Collection[str],
                    rename_offer: RenameOffer, placement: Mapping[str, str],
                    retargeted: Mapping[str, str]) -> dict:
    """"What this change does", for unsaved edits of the playlist page. The api passes `placement` (key -> folder
    under `new`, `pf.placement`), `retargeted` (the keys whose folder changes, `pf.retargeted`), the folders of
    `Library/` and `tidy.rename_offer`, so this stays pure."""
    c = pf.preview_change(old, new, tracks_by_id, state, files, today)
    tidy_list = tidy_rows(state, placement, only=retargeted) if retargeted else []
    renames = pf.renames(old, new)
    rename_items = _rename_items(renames, new, files, library_dirs, rename_offer)
    folders = list(dict.fromkeys([r.folder for r in new + old if r.folder in c.before or r.folder in c.after] +
                                 sorted(set(c.before) | set(c.after), key=fold)))
    tracks = state["tracks"]
    spotify = {t.key: t for ts in tracks_by_id.values() for t in ts}

    def spotify_track(k: str):
        return next((spotify[i] for i in [k, *((tracks.get(k) or {}).get("aliases") or [])] if i in spotify), None)

    shown = {r.track_id for r in tidy_list}
    # a file on the tidy list (even one that can't move) is not also a track "without a file"
    kept = [(k, frm, to) for k, frm, to in c.reroutes if k not in shown]
    reroutes = [{**_spotify_row(k, spotify_track(k), tracks.get(k), cover, state.get("never")), "from": frm, "to": to}
                for k, frm, to in kept]
    renamed = set(renames)
    pairs = {(frm, to) for k, frm, to in [m for m in c.moves if m[0] in shown] + kept}
    days = (1 if c.new else 0) if money is None else days_to_load(len(c.new), money["remaining"], money["limit"])
    n_tracks = len(reroutes)
    tracks_will = f"{n_tracks} tracks will" if n_tracks != 1 else "1 track will"
    save_headline = _plural(len(tidy_list), SAVE_HEADLINE_ONE, SAVE_HEADLINE)
    if pairs and renamed and pairs <= renamed:
        kind = "rename"
        headline = save_headline if tidy_list else f"{tracks_will} go to the new folder name"
    elif tidy_list:
        kind, headline = "moves", save_headline
    elif reroutes:
        kind = "reroute"
        headline = (f"{tracks_will} go to {next(iter(pairs))[1]} instead of {next(iter(pairs))[0]}"
                    if len(pairs) == 1 else f"{tracks_will} go to another folder")
    elif c.new:
        kind = "add"
        headline = (f"{len(c.new)} new download{'s' if len(c.new) != 1 else ''}, about {days} "
                    f"day{'s' if days != 1 else ''} at the current limit")
    elif c.stopped:
        kind, headline = "switch_off", "Files stay, no more updates"
    elif c.unknown:
        kind, headline = "unknown", "Discjockey hasn't read the new playlist yet"
    else:
        kind, headline = "none", "Nothing changes in your library"
    checklist = [CHECK_NO_DOWNLOADS] if not c.new else [
        f"{len(c.new)} download{'s' if len(c.new) != 1 else ''}, counted toward your Qobuz limit"]
    checklist.append(CHECK_NOTHING_DELETED)
    checklist += [CHECK_CHOICE, CHECK_UNDO] if kind in ("moves", "rename") else [CHECK_NEXT_SYNC]
    tidy = {"headline": save_headline, "rows": [tidy_row(r, tracks[r.track_id], cover, _by_rename(r, renames))
                                                for r in tidy_list]} if tidy_list else None
    return {"kind": kind, "headline": headline,
            "folders": [{"folder": f, "before": c.before.get(f, 0), "after": c.after.get(f, 0)} for f in folders],
            "tidy": tidy, "renames": rename_items, "reroutes": reroutes, "new_downloads": len(c.new), "days": days,
            "stopped": len(c.stopped), "unknown": c.unknown, "checklist": checklist}
