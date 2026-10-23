"""User settings that the hub (and `discjockey --extra`) can change: settings.json
in the support folder."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Mapping

from .accounts import ACCOUNTS, BROWSERS, DEFAULT_LIMITS

DEFAULT_DAILY_LIMIT = 60
MAX_DAILY_LIMIT = 500
MAX_EXTRA = 200


class SettingsError(Exception):
    pass


CHECK_KEYS = frozenset({"ok", "problem", "kbps", "at"})  # a saved login check (spec settings-setup §6.2)


@dataclass(frozen=True)
class Account:
    """A YouTube Premium or SoundCloud Go+ login: which browser and browser profile hold it (never a cookie), its own
    daily limit, and the last check's outcome (Settings shows it without checking again)."""
    browser: str
    daily_limit: int
    extra_date: str | None = None
    extra_amount: int = 0
    profile: str | None = None  # the browser profile's folder (Chrome "Profile 2", a Firefox profile); None: default
    last_check: Mapping | None = field(default=None, hash=False)  # {ok, problem, kbps, at}


@dataclass(frozen=True)
class Settings:
    daily_qobuz_limit: int = DEFAULT_DAILY_LIMIT
    extra_date: str | None = None  # the day the one-time extra applies to (ISO date)
    extra_amount: int = 0
    accounts: Mapping[str, Account] = field(default_factory=dict, hash=False)  # missing: not set up
    qobuz_skipped: bool = False  # "I don't have Qobuz" in setup
    # "Got it" on the Download limits page: per service, the time up to which its warning signs were seen
    warnings_seen: Mapping[str, str] = field(default_factory=dict, hash=False)
    qobuz_last_check: Mapping | None = field(default=None, hash=False)  # {ok, problem, kbps, at} of the last login

    def extra_for(self, day: date) -> int:
        return self.extra_amount if self.extra_date == day.isoformat() else 0

    def limit_of(self, service: str) -> int:
        return self.daily_qobuz_limit if service == "qobuz" else self.accounts[service].daily_limit

    def extra_of(self, service: str, day: date) -> int:
        if service == "qobuz":
            return self.extra_for(day)
        a = self.accounts[service]
        return a.extra_amount if a.extra_date == day.isoformat() else 0

    def with_limit(self, service: str, limit: int, extra_date: str | None, extra_amount: int) -> Settings:
        if service == "qobuz":
            return replace(self, daily_qobuz_limit=limit, extra_date=extra_date, extra_amount=extra_amount)
        a = replace(self.accounts[service], daily_limit=limit, extra_date=extra_date, extra_amount=extra_amount)
        return replace(self, accounts={**self.accounts, service: a})

    def with_seen(self, service: str, until: str) -> Settings:
        return replace(self, warnings_seen={**self.warnings_seen, service: until})

    def with_account(self, service: str, browser: str | None, profile: str | None = None) -> Settings:
        """browser None forgets the login (its limit goes with it; the usage history in state.json stays). Another
        browser or profile keeps the limit and drops the last check (it was about the old login)."""
        accounts = {k: v for k, v in self.accounts.items() if k != service}
        if browser is not None:
            old = self.accounts.get(service)
            accounts[service] = (replace(old, browser=browser, profile=profile, last_check=None) if old
                                 else Account(browser, DEFAULT_LIMITS[service], profile=profile))
        return replace(self, accounts=accounts)

    def with_check(self, service: str, check: Mapping) -> Settings:
        """The last login check of Qobuz or of a set-up account."""
        if service == "qobuz":
            return replace(self, qobuz_last_check=dict(check))
        return replace(self, accounts={**self.accounts,
                                       service: replace(self.accounts[service], last_check=dict(check))})


def _extra(data: dict) -> tuple[str | None, int]:
    extra = data.get("extra_today") or {}
    return extra.get("date"), int(extra.get("amount", 0))


def _check(path: Path, name: str, limit: int, amount: int) -> None:
    if not 1 <= limit <= MAX_DAILY_LIMIT:
        raise SettingsError(f"{path.name}: {name} must be between 1 and {MAX_DAILY_LIMIT}.")
    if not 0 <= amount <= MAX_EXTRA:
        raise SettingsError(f"{path.name}: the extra amount must be between 0 and {MAX_EXTRA}.")


def _last_check(path: Path, raw: object) -> dict | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != CHECK_KEYS or not isinstance(raw["ok"], bool):
        raise SettingsError(f"{path.name}: a last check must have ok, problem, kbps and at.")
    return dict(raw)


def load_settings(path: Path) -> Settings:
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        limit = int(data.get("daily_qobuz_limit", DEFAULT_DAILY_LIMIT))
        day, amount = _extra(data)
        accounts = {}
        for service, a in (data.get("accounts") or {}).items():
            a_day, a_amount = _extra(a)
            profile = a.get("profile")
            if profile is not None and not isinstance(profile, str):
                raise SettingsError(f"{path.name}: accounts.{service}.profile must be a name.")
            accounts[str(service)] = Account(str(a["browser"]), int(a["daily_limit"]), a_day, a_amount, profile,
                                             _last_check(path, a.get("last_check")))
        skipped = data.get("qobuz_skipped", False)
        if not isinstance(skipped, bool):
            raise SettingsError(f"{path.name}: qobuz_skipped must be true or false.")
        seen = data.get("warnings_seen") or {}
        if not isinstance(seen, dict) or not all(isinstance(v, str) for v in seen.values()):
            raise SettingsError(f"{path.name}: warnings_seen must map services to times.")
        s = Settings(limit, day, amount, accounts, skipped, {str(k): v for k, v in seen.items()},
                     _last_check(path, data.get("qobuz_last_check")))
    except SettingsError:
        raise
    except (ValueError, TypeError, AttributeError, KeyError) as e:
        raise SettingsError(f"{path.name} is not valid ({e}). Fix or delete it.") from None
    _check(path, "daily_qobuz_limit", s.daily_qobuz_limit, s.extra_amount)
    for service, a in s.accounts.items():
        if service not in ACCOUNTS:
            raise SettingsError(f"{path.name}: unknown account {service!r} (Discjockey knows {', '.join(ACCOUNTS)}).")
        if a.browser not in BROWSERS:
            raise SettingsError(f"{path.name}: unknown browser {a.browser!r} for {service} "
                                f"(use one of {', '.join(BROWSERS)}).")
        _check(path, f"accounts.{service}.daily_limit", a.daily_limit, a.extra_amount)
    return s


def _extra_json(day: str | None, amount: int) -> dict | None:
    return {"date": day, "amount": amount} if day else None


def save_settings(path: Path, s: Settings) -> None:
    data = {"daily_qobuz_limit": s.daily_qobuz_limit, "extra_today": _extra_json(s.extra_date, s.extra_amount),
            "qobuz_skipped": s.qobuz_skipped, "warnings_seen": dict(s.warnings_seen),
            "qobuz_last_check": dict(s.qobuz_last_check) if s.qobuz_last_check else None,
            "accounts": {k: {"browser": a.browser, "profile": a.profile, "daily_limit": a.daily_limit,
                             "extra_today": _extra_json(a.extra_date, a.extra_amount),
                             "last_check": dict(a.last_check) if a.last_check else None}
                         for k, a in s.accounts.items()}}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(tmp, path)
