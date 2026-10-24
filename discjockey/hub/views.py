"""Pure functions: state, run reports, settings and the preview plan -> the JSON of each hub screen (spec "hub" 6.9).

No file access and no clock here: the API passes everything in (today, now, and helpers that turn a track into a
cover or audio URL). Every number on the screens comes from these functions.
"""
from __future__ import annotations

import math
from collections.abc import Collection, Iterable, Mapping
from datetime import date, datetime, timedelta
from typing import Callable
from urllib.parse import quote_plus

from .. import playlists_file as pf
from ..accounts import (ACCOUNTS, BROWSERS, DEFAULT_LIMITS, MAX_LIMIT, PREMIUM_MIN_KBPS, SERVICES, SERVICE_NAMES,
                        SERVICE_SIGNALS)
from ..accounts import assessment as service_assessment, zones as service_zones
from ..names import expected_stem, fold
from ..models import SOURCE_NAMES, BatchResult, BatchRow, MoveRow, PlannedMove
from ..pacing import KEEP_SIGNALS, Budget
from ..planner import KIND_RANK, WAIT_DAYS, TidyRow, out_of_place, tidy_rows
from ..quality import quality_line
from ..report import PLAN_LABELS, check_text
from ..settings import Settings
from ..upgrades import upgrade_name

SECONDS_PER_DOWNLOAD = 70  # average per acquisition or upgrade check: pause, download, conversion, long breaks
WEAK_HZ = 17_000  # a lossy cutoff at or below this is audible: "weak"
QUALITIES = ("lossless", "good_lossy", "weak", "fake", "missing")
SIGNAL_DAYS = 14
SHORT_SOURCE = {"qobuz": "Qobuz", "youtube_music": "YT Music", "soundcloud": "SoundCloud", "youtube": "YouTube",
                "manual": "bought"}
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


# --- formulas (spec 6.9) ---

def lossless_share(state: dict) -> dict:
    """Lossless tracks ÷ tracks in playlists (hidden ones count). share is None when there are none ("—")."""
    entries = [e for e in state["tracks"].values() if e.get("in_playlists")]
    by = {q: 0 for q in QUALITIES}
    for e in entries:
        by[quality_class(e)] += 1
    total = len(entries)
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


def spotify_status(store, now: datetime, reading: bool) -> dict:
    """"Spotify read 2 min ago · ↻". problem: the last read's problem kind (offline: the data shown is older).
    auto_read: the hub's one automatic read of this session has started (the Sync page then never reads by itself)."""
    read_at = store.read_at
    return {"read_at": read_at.isoformat(timespec="seconds") if read_at else None,
            "minutes_ago": int((now - read_at).total_seconds() // 60) if read_at else None,
            "problem": store.problem, "message": store.message, "stale": store.stale, "reading": reading,
            "offline": store.problem == "offline", "auto_read": store.auto_read}


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
        by = {q: 0 for q in QUALITIES}
        for e in entries:
            by[quality_class(e)] += 1
        out.append({"folder": folder, "tracks": len(entries),
                    "lossless_share": round(by["lossless"] / len(entries), 4) if entries else None,
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
              setup: dict, today: date, now: datetime, reading: bool) -> dict:
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
    return {"greeting": greeting(now), "spotify": spotify_status(store, now, reading),
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


def track_row(track_id: str, e: dict, cover: Url | None = None) -> dict:
    source = e.get("source")
    return {"track_id": track_id, "artist": e["artist"], "title": e["title"], "folder": e["folder"],
            "duration_s": round((e.get("duration_ms") or 0) / 1000, 1), "status": e["status"],
            "quality": quality_class(e), "quality_label": quality_label(e), "cutoff_hz": e.get("cutoff_hz"),
            "source": source, "source_name": SHORT_SOURCE.get(source) if source else None,
            "in_playlists": bool(e.get("in_playlists")), "hidden": bool(e.get("hidden")),
            "upgrade_ready": bool(e.get("upgrade")), "path": e.get("path"), "added": e.get("added"),
            "cover_url": cover(track_id, e) if cover else None}


def cue_text(alignment: dict | None) -> str:
    a = alignment or {}
    if a.get("result") == "shifted":
        return f"aligned by {abs(a.get('offset_ms') or 0):.0f} ms, cues stay"
    return CUE_TEXT.get(a.get("result"), CUE_TEXT["unknown"])


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
    """Folders of the active playlists that contain the track (from the last Spotify read), or None if unknown."""
    if not fetched:
        return None
    ids = {track_id, *(e.get("aliases") or [])}
    return [fp.line.folder for fp in fetched if any(t.id in ids for t in fp.tracks)]


def upgrade_block(up: dict | None, media: Url | None, track_id: str, e: dict) -> dict | None:
    if not up:
        return None
    alignment = up.get("alignment") or {"result": "unknown"}
    return {"file": up["file"], "source": up["source"], "source_name": SHORT_SOURCE.get(up["source"]),
            "source_id": up.get("source_id"), "found": up.get("found"),
            "what": upgrade_name(up),
            "quality_line": quality_line(up["source"], up.get("source_format") or "flac", up.get("status", "lossless"),
                                         up.get("cutoff_hz"), up.get("kbps")),
            "alignment": alignment, "cue_text": cue_text(alignment),
            "swap_safe": alignment.get("result") in ("exact", "shifted"),
            "swap_possible": (e.get("path") or "").lower().endswith((".aiff", ".aif")),
            "audio_url": media(track_id, {**e, "path": up["file"]}) if media else None}


def track_detail(track_id: str, e: dict, fetched: list, today: date, cover: Url | None = None,
                 media: Url | None = None) -> dict:
    folders = in_playlists(track_id, e, fetched)
    has_file = e["status"] != "missing" and e.get("source")
    return {**track_row(track_id, e, cover), "isrc": e.get("isrc"),
            "playlists": folders, "in_playlist_count": len(folders) if folders is not None else None,
            "quality_line": quality_line(e["source"], e.get("source_format") or "?", e["status"], e.get("cutoff_hz"),
                                         e.get("source_kbps")) if has_file else None,
            "format_line": format_line(e) if has_file else None,
            "source_full": (("bought" if e["source"] == "manual" else SOURCE_NAMES.get(e["source"]))
                            if has_file else None),
            "source_url": source_url(e.get("source"), e.get("source_id")),
            "spotify_url": f"https://open.spotify.com/track/{track_id}",
            "next_qobuz_check": next_check(e, today), "rejected_sources": list(e.get("rejected_sources") or []),
            "buy_links": buy_links(e["artist"], e["title"]), "free_downloads": free_downloads(e),
            "bought_name": f"Library/{e['folder']}/{expected_stem(e['artist'], e['title'])}.wav",
            "audio_url": media(track_id, e) if media and e.get("path") else None,
            "upgrade": upgrade_block(e.get("upgrade"), media, track_id, e)}


# --- library ---

SORTS = {"title": lambda r: fold(r["title"]), "artist": lambda r: (fold(r["artist"]), fold(r["title"])),
         "length": lambda r: r["duration_s"], "source": lambda r: r["source_name"] or "",
         "quality": lambda r: QUALITIES.index(r["quality"]), "added": lambda r: r["added"] or "",
         # tracks in no playlist sit in their folder on disk, but read as "Not in a playlist": they sort last
         "folder": lambda r: (not r["in_playlists"], fold(r["folder"]), fold(r["artist"]), fold(r["title"]))}
LIBRARY_FILTERS = ("all", "lossless", "good_lossy", "weak", "fake", "upgrade_ready")


def _matches(row: dict, filt: str) -> bool:
    return filt == "all" or (row["upgrade_ready"] if filt == "upgrade_ready" else row["quality"] == filt)


def library(state: dict, folder: str | None, query: str, filt: str, sort: str, cover: Url | None = None) -> dict:
    """folder: None (all tracks), NOT_IN_PLAYLIST, or a folder name. filt: LIBRARY_FILTERS. sort: a SORTS key,
    "-" in front for descending. Only tracks with a file (not found ones are in the to-do list)."""
    with_file = {k: e for k, e in state["tracks"].items() if e["status"] != "missing" and e.get("path")}
    if folder is None:
        chosen, title = with_file, "All tracks"
    elif folder == NOT_IN_PLAYLIST:
        chosen, title = {k: e for k, e in with_file.items() if not e.get("in_playlists")}, "Not in a playlist"
    else:
        chosen, title = {k: e for k, e in with_file.items() if fold(e["folder"]) == fold(folder)}, folder
    rows = [track_row(k, e, cover) for k, e in chosen.items()]
    in_folder = len(rows)
    by = {q: 0 for q in QUALITIES}
    for r in rows:
        by[r["quality"]] += 1
    # the folder at a glance (the panel's overview): unaffected by the search and the filter
    summary = {"tracks": in_folder, "lossless_share": round(by["lossless"] / in_folder, 4) if in_folder else None,
               "by_quality": by, "upgrades_ready": sum(1 for r in rows if r["upgrade_ready"]),
               "to_do": sum(1 for e in chosen.values()
                            if e.get("in_playlists") and not e.get("hidden") and _group(e) is not None)}
    q = fold(query or "").strip()
    if q:
        rows = [r for r in rows if q in fold(f"{r['artist']} {r['title']}")]
    chips = {f: sum(1 for r in rows if _matches(r, f)) for f in LIBRARY_FILTERS}
    rows = [r for r in rows if _matches(r, filt or "all")]
    key = (sort or "artist").lstrip("-")
    rows.sort(key=SORTS.get(key, SORTS["artist"]), reverse=(sort or "").startswith("-"))
    empty = "empty_library" if not with_file else ("no_match" if not rows else None)
    return {"title": title, "folder": folder, "summary": summary, "chips": chips, "rows": rows, "empty": empty}


def sidebar(state: dict, folder_order: list[str], todo_count: int, warnings: bool = False) -> dict:
    with_file = [e for e in state["tracks"].values() if e["status"] != "missing" and e.get("path")]
    counts: dict[str, int] = {}
    for e in with_file:
        counts[e["folder"]] = counts.get(e["folder"], 0) + 1
    order = list(folder_order) + sorted((f for f in counts if fold(f) not in {fold(x) for x in folder_order}),
                                        key=fold)
    return {"todo": todo_count, "all_tracks": len(with_file),
            "folders": [{"folder": f, "tracks": counts.get(f, 0), "in_playlists_txt": f in folder_order}
                        for f in order],
            "not_in_playlist": sum(1 for e in with_file if not e.get("in_playlists")), "limits_warning": warnings}


# --- to-do ---

TODO_GROUPS = [("rekordbox_check", "Check in rekordbox", "the file changed; rekordbox needs a hand"),
               ("upgrade_ready", "Upgrade ready", "a better version is waiting for you"),
               ("not_found", "Not found", "nothing usable anywhere"),
               ("weak", "Weak (≤ 17 kHz)", "audibly lossy"),
               ("good_lossy", "Good lossy (~20 kHz)", "hard to hear"),
               ("fake", "Fake lossless", "the Qobuz file is really lossy"),
               ("other", "Other", "something is in the way")]


FREE_GROUPS = ("not_found", "weak", "good_lossy", "fake")  # where an artist's free download is worth a tag


def _group(e: dict) -> str | None:
    if e.get("upgrade"):
        return "upgrade_ready"
    return {"missing": "not_found", "weak": "weak", "good_lossy": "good_lossy", "fake": "fake"}.get(quality_class(e))


def _detail(group: str, e: dict, today: date, other: str | None) -> str:
    if group == "upgrade_ready":
        return cue_text(e["upgrade"].get("alignment"))
    if group == "not_found":
        when = next_check(e, today)
        if when is None or when == "next_sync":
            return "tried again at the next sync"
        days = (date.fromisoformat(when) - today).days
        return f"next try in {days} day{'s' if days != 1 else ''}"
    if group == "other":
        return other or ""
    # the badge already says the kHz: where it came from, and how many kbps for a lossy download
    source = SHORT_SOURCE.get(e.get("source") or "", "")
    kbps = f"{e['source_kbps']} kbps" if e.get("source_kbps") and e["status"] == "not_lossless" else ""
    return " · ".join(x for x in (source, kbps) if x)


def todo(state: dict, filt: str, show_hidden: bool, others: dict[str, str], today: date,
         cover: Url | None = None) -> dict:
    """Groups in this order: Upgrade ready, Not found, Weak, Good lossy, Fake lossless, Other. `others`: track id ->
    what blocks it (a move blocked by another file, several files that could be it). Hidden tracks are left out
    unless show_hidden. "Check in rekordbox" lists every track with a `rekordbox_check`, hidden or not, so a track
    can be in two groups; chips["all"] counts each track once."""
    items: dict[str, list] = {g: [] for g, _, _ in TODO_GROUPS}
    never = state.get("never") or {}  # "never download": not a to-do
    hidden = 0
    listed: set[str] = set()
    for k, e in state["tracks"].items():
        if e.get("rekordbox_check"):
            items["rekordbox_check"].append({**track_row(k, e, cover), "group": "rekordbox_check",
                                             "detail": check_text(e["rekordbox_check"])})
            listed.add(k)
        if not e.get("in_playlists") or (e["status"] == "missing" and k in never):
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
    for track, _folder, _files in (prep.plan.ambiguous if prep else []):
        out[track.id] = "SEVERAL FILES · could be this track, nothing done"
    return out


# --- sync screen, before the start ---

def action_row(a, state: dict, cover: Url | None = None) -> dict:
    e = state["tracks"].get(a.track_id)
    artist, title = (e["artist"], e["title"]) if e else (a.track.first_artist, a.track.title)
    to_dir = a.dest_dir or f"Library/{a.folder}"
    return {"key": [a.kind, a.track_id, to_dir], "kind": a.kind, "reason": a.reason or None,
            "track_id": a.track_id, "artist": artist, "title": title, "folder": a.folder,
            "to_dir": to_dir, "to_not_lossless": to_dir.endswith("/not_lossless"),
            "src": a.src, "cover_url": cover(a.track_id, e) if cover and e else a.track.image_url}


def sync_preview(store, state: dict, settings: Settings, today: date, now: datetime, reading: bool,
                 cover: Url | None = None) -> dict:
    """The check before the start: every planned action in groups, each with the key the page sends back ticked."""
    prep = store.prep
    status = spotify_status(store, now, reading)
    if prep is None:
        return {"spotify": status, "counts": None, "groups": [], "estimate": None, "never": [], "folders": [],
                "in_playlists": None, "ambiguous": [], "dropped": [], "notes": [], "empty": "no_preview"}
    plan_state = prep.state
    m = moneys(state, settings, today)
    todo, never = planned(prep, state)
    groups: dict[str, list] = {}
    for a in todo:
        groups.setdefault(f"acquire:{a.reason}" if a.kind == "acquire" else a.kind, []).append(a)
    in_playlists = {t.id for fp in prep.fetched for t in fp.tracks}
    run_index = {id(a): i for i, a in enumerate(todo)}  # the order the sync works through them
    return {"spotify": status, "counts": plan_counts(todo),
            "groups": [{"key": key, "label": label,
                        "actions": [{**action_row(a, plan_state, cover), "run": run_index[id(a)]} for a in groups[key]]}
                       for key, label in PLAN_LABELS if key in groups],
            "estimate": sync_estimate(todo, m),
            "never": [action_row(a, plan_state, cover) for a in never],
            "folders": [line.folder for line in prep.lines],
            "in_playlists": len(in_playlists),
            "ambiguous": [{"track_id": t.id, "artist": t.first_artist, "title": t.title, "folder": folder,
                           "files": files} for t, folder, files in prep.plan.ambiguous],
            "dropped": [{"track_id": k, "artist": plan_state["tracks"][k]["artist"],
                         "title": plan_state["tracks"][k]["title"], "folder": plan_state["tracks"][k]["folder"]}
                        for k in prep.plan.dropped],
            "notes": list(prep.plan.notes), "empty": None if todo else "up_to_date"}


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
        e = by_id.get(t.id)
        by[quality_class(e) if e else "missing"] += 1
    return by


def info_dict(info) -> dict | None:
    if info is None:
        return None
    return {"name": info.name, "owner_name": info.owner_name, "yours": info.yours,
            "collaborative": info.collaborative, "readable": info.readable, "image_url": info.image_url,
            "track_count": info.track_count}


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
    `files` are the snapshot paths on disk: a folder move carries every file under the folder it moves back."""
    rows = []
    for m in moves:
        frm, to, _, _ = _ends(m.kind, m.src, m.dst)
        reason, detail = m.skip or (None, None)
        rows.append({"label": m.label, "from": frm, "to": to,
                     "skip": {"reason": reason, "text": _skip_words(m.kind, m.src, m.dst, reason, detail)}
                     if reason else None})
    running = [m for m, r in zip(moves, rows) if r["skip"] is None]
    on_disk = list(files)
    moving = sum(1 for m in running if m.kind == "file")
    for m in running:
        if m.kind == "folder":  # the files sit under the folder's current name, `src`
            moving += sum(1 for f in on_disk if f.startswith(f"{m.src}/"))
    warning = [_plural(moving, UNDO_WARN_ONE, UNDO_WARN)] if moving else []
    folder = next((m for m in running if m.kind == "folder"), None)
    if folder is not None:
        warning.append(UNDO_RENAME.format(old=_rel(folder.dst)))
    return {"batch_id": batch.id, "title": title if title is not None else batch_title(batch), "rows": rows,
            "moving": moving, "warning": warning, "nothing_left": not running}


def playlists(loaded: pf.Loaded, tracks_by_id: dict, infos: dict, state: dict, cover: Url | None = None) -> dict:
    rows = []
    for i, r in enumerate(loaded.rows):
        tracks = tracks_by_id.get(r.playlist_id)
        info = infos.get(r.playlist_id)
        rows.append({"index": i, "folder": r.folder, "link": r.link, "playlist_id": r.playlist_id,
                     "enabled": r.enabled, "info": info_dict(info),
                     "tracks": len(tracks) if tracks is not None else (info.track_count if info else None),
                     "quality": _quality_of_tracks(tracks, state) if tracks is not None else None})
    by_id = _entries_by_id(state)
    overlap = [{**_spotify_row(t.id, t, by_id.get(t.id), cover, state.get("never")), "folders": folders, "lands_in": lands}
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
        n = sum(1 for f in files if f.startswith(f"Library/{was}/"))
        text = {"folder_taken": FOLDER_TAKEN.format(new=now), "folder_in_use": FOLDER_IN_USE.format(old=was)}
        items.append({"from": was, "to": now, "files": n, "offered": why is None,
                      "why_not": None if why is None else text.get(why), "option": RENAME_OPTION,
                      "detail": f"One folder move instead of {n} file move{'s' if n != 1 else ''}."})
    return items


def _by_rename(row: TidyRow, pairs: list[tuple[str, str]]) -> str | None:
    """The old folder name whose rename on disk would put this row's file at its target, else None."""
    for was, now in pairs:
        prefix = f"Library/{was}/"
        if row.src.startswith(prefix) and row.dst == f"Library/{now}/{row.src[len(prefix):]}":
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
    spotify = {t.id: t for ts in tracks_by_id.values() for t in ts}

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
