# dmgbuild settings for Discjockey-<version>.dmg (spec public-release §7): the app, an arrow, an Applications link.
# dmgbuild writes the window layout itself (no Finder, no AppleScript, so no Automation prompt and it works headless).
# scripts/build_app.sh: dmgbuild -s packaging/dmg_settings.py -D app=<Discjockey.app> Discjockey <out.dmg>
import os.path

application = defines["app"]  # noqa: F821 (dmgbuild provides `defines`)
appname = os.path.basename(application)

format = "UDZO"
filesystem = "HFS+"
files = [application]
symlinks = {"Applications": "/Applications"}
icon_locations = {appname: (140, 120), "Applications": (500, 120)}
background = "builtin-arrow"
window_rect = ((100, 100), (640, 280))
default_view = "icon-view"
show_status_bar = False
show_tab_view = False
show_toolbar = False
show_pathbar = False
show_sidebar = False
icon_size = 128
text_size = 13
