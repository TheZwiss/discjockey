"""discjockey setup (one-time logins) and discjockey update (the newest yt-dlp, tool_updates)."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from . import REPO, library, qobuz, spotify, tool_updates, tools
from .library import Paths

TEMPLATE = """\
# Your Spotify playlists for Discjockey.
#
# One playlist per line:   Folder name = Spotify playlist link
# Highest priority first: a track that is in several playlists goes into the
# folder of the playlist that comes first here.
#
# Get a link in Spotify: open the playlist -> ... -> Share -> Copy link to playlist
# Lines starting with # are ignored.

# Hard_Bounce = https://open.spotify.com/playlist/...
"""

SPOTIFY_STEPS = """\
Spotify: you need a free "app" in Spotify's developer dashboard (one time only).
  1. Open https://developer.spotify.com/dashboard and log in with your Spotify account.
  2. Click "Create app". Name and description: anything, e.g. "Discjockey".
  3. Redirect URI: http://127.0.0.1:8888/callback  (click Add)
  4. Tick "Web API", accept the terms, click Save.
  5. Open the app's Settings and copy the "Client ID".
"""

# For a Qobuz account made with Google, Apple or Facebook sign-in (no Qobuz password): give it a password once. The
# web player no longer keeps a login the app could read (spec settings-setup §13); the hub shows the same steps.
QOBUZ_PASSWORD_URL = "https://www.qobuz.com/signin/forget-password"
QOBUZ_PASSWORD_STEPS = f"""\
Qobuz with Google, Apple or Facebook: give your Qobuz account a password once (your Google sign-in keeps working).
  1. Open {QOBUZ_PASSWORD_URL} and enter your account's e-mail.
  2. Open the e-mail from Qobuz and choose a password.
  3. Then log in here with that e-mail and password.
"""

TOOL_HINTS = {"ffmpeg": "brew install ffmpeg", "ffprobe": "brew install ffmpeg", "deno": "brew install deno"}


def check_tools() -> list[str]:
    return [tool for tool in TOOL_HINTS if shutil.which(tool) is None]


def _ask_client_id(paths: Paths) -> str:
    saved = None
    if paths.spotify_app.exists():
        saved = json.loads(paths.spotify_app.read_text(encoding="utf-8")).get("client_id")
    print(SPOTIFY_STEPS)
    while True:
        prompt = "Paste the Client ID" + (" (or press Enter to keep the saved one)" if saved else "") + ": "
        value = input(prompt).strip() or saved or ""
        if re.fullmatch(r"[0-9a-fA-F]{32}", value):
            paths.spotify_app.write_text(json.dumps({"client_id": value}), encoding="utf-8")
            return value
        print("That does not look like a Client ID (32 letters and digits). Try again.")


def _show_login_link(url: str) -> None:
    print("Opening Spotify in your browser. If nothing opens, copy this link into your browser:")
    print(url)


def run_setup(paths: Paths) -> int:
    print("Discjockey setup\n")
    missing = check_tools()
    for tool in missing:
        print(f"Missing program: {tool}. Install it with: {TOOL_HINTS[tool]}")

    client_id = _ask_client_id(paths)
    try:
        spotify.login(client_id, paths.spotify_token, on_url=_show_login_link)
        me = spotify.api_get(spotify.load_session(paths), f"{spotify.API}/me")
    except spotify.SpotifyError as e:
        print(e)
        return 2
    print(f"Spotify login works ({me.get('display_name') or me.get('id')}).\n")

    try:
        _qobuz_login(paths)
    except Exception as e:
        print(f"Qobuz login failed: {qobuz.login_problem(e)}")
        return 2
    print("Qobuz login works.\n")

    if not paths.playlists_file.exists():
        paths.playlists_file.write_text(TEMPLATE, encoding="utf-8")
        print(f"Created {paths.playlists_file}. Add your playlist links there.")

    launcher = REPO / "bin" / "discjockey"  # the console Setup runs in a checkout only
    print("\nTip: to start Discjockey by typing just 'discjockey', run this once:")
    print(f"  echo \"alias discjockey='\\\"{launcher}\\\"'\" >> ~/.zshrc")
    return 2 if missing else 0


def _qobuz_login(paths: Paths) -> None:
    print("Qobuz: how do you log in to Qobuz?")
    print("  1  with e-mail and password")
    print("  2  with Google, Apple or Facebook (no Qobuz password)")
    while (choice := input("Type 1 or 2: ").strip()) not in ("1", "2"):
        pass
    if choice == "2":
        print()
        print(QOBUZ_PASSWORD_STEPS)
        input("Press Enter when your Qobuz account has a password. ")
    qobuz.interactive_login(paths)


def run_update(support: Path) -> int:
    """discjockey update: the newest yt-dlp into the support folder (tool_updates); streamrip comes with Discjockey
    and is updated with it."""
    try:
        before, after, restart = tool_updates.update(support)
    except tool_updates.ToolsError as e:
        print(e)
        return 2
    print(tool_updates.update_line(before, after))
    if restart:
        print("Start Discjockey again to use it.")
    return 0


MUSIC_FOLDER_INTRO = """\
Your music folder: Discjockey keeps your library here (Library/, Superseded/, Upgrades ready/ and playlists.txt).
Point rekordbox at its Library folder. A new folder is made for you; an existing one is used as it is.
"""


def ask_music_folder(support: Path, home: Path | None = None, ask=None) -> Paths:
    """discjockey setup's first question. Saves the folder in config.json (and makes it when it is new) only after
    the user agreed; returns its Paths."""
    ask = ask or input  # looked up now, so a test can replace builtins.input
    home = home or Path.home()
    suggested = home / "Music" / "Discjockey"
    print(MUSIC_FOLDER_INTRO)
    while True:
        raw = ask(f"Music folder (press Enter for {suggested}): ").strip()
        check = library.check_music_folder(raw or suggested, support=support, program=tools.program_dir(), home=home)
        if not check.usable:
            print(library.FOLDER_PROBLEMS[check.problem])
            continue
        if check.kind == "other_files" and ask(
                "Other files are in that folder. Discjockey adds its folders next to them. Use it? [y/N] "
        ).strip().lower() not in ("y", "yes"):
            continue
        check.path.mkdir(parents=True, exist_ok=True)
        library.write_music_folder(support, check.path)
        print(f"Music folder: {check.path}\n")
        return Paths(check.path, support=support)
