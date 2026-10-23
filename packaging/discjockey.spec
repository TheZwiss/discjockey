# PyInstaller 6.22.3 spec for Discjockey.app (spec public-release §5). scripts/build_app.sh runs it and sets:
#   DISCJOCKEY_VERSION    discjockey.__version__
#   DISCJOCKEY_TOOLS_BIN  the checked ffmpeg, ffprobe, deno (packaging/fetch_tools.py)
#   DISCJOCKEY_LICENSES   where to write the licences folder; this spec fills it (packaging/collect_licenses.py)
#                         from what Analysis collected, then bundles it as Contents/Resources/licenses
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

HERE = Path(SPECPATH)  # noqa: F821 (PyInstaller provides SPECPATH)
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import app_info  # noqa: E402
import collect_licenses  # noqa: E402

VERSION = os.environ["DISCJOCKEY_VERSION"]
TOOLS_BIN = Path(os.environ["DISCJOCKEY_TOOLS_BIN"])
LICENSES = Path(os.environ["DISCJOCKEY_LICENSES"])

datas = [(str(ROOT / "discjockey" / "hub" / "static"), "discjockey/hub/static"),
         (str(ROOT / "discjockey" / "hub" / "icon"), "discjockey/hub/icon")]
# The programs go in as data (as in the spike): PyInstaller leaves them unchanged, BUNDLE moves them to
# Contents/Frameworks/bin with Contents/Resources/bin pointing there, and sign_app.py signs them.
datas += [(str(TOOLS_BIN / name), "bin") for name in ("ffmpeg", "ffprobe", "deno")]
binaries = []
hiddenimports = ["webview.platforms.cocoa", *collect_submodules("discjockey")]
d, b, h = collect_all("streamrip")
datas += d
binaries += b
hiddenimports += h
datas += collect_data_files("certifi")
hiddenimports += ["yt_dlp", "yt_dlp_ejs"]

a = Analysis([str(HERE / "launch.py")], pathex=[str(ROOT)], datas=datas, binaries=binaries,
             hiddenimports=hiddenimports, excludes=["tkinter", "pytest", "_pytest"],
             # plain files: tools.package_version() reads version.py from disk, and an update folder can win (§6.4)
             module_collection_mode={"yt_dlp": "py", "yt_dlp_ejs": "py"})
# The licences of exactly what Analysis collected (spec §6.5): the source path of every collected file goes to a list,
# and collect_licenses maps each to the distribution that installed it. The venv holds more than the app (pytest
# arrives as a runtime dependency of streamrip), so it can't be the list.
BUNDLED = LICENSES.with_name("bundled-sources.txt")
BUNDLED.write_text("".join(f"{src}\n" for src in collect_licenses.toc_sources(a.pure, a.binaries, a.datas)))
if collect_licenses.main(["--out", str(LICENSES), "--bundled", str(BUNDLED)]) != 0:
    raise SystemExit("the licences folder could not be made (see the lines above)")
licenses = Tree(str(LICENSES), prefix="licenses")  # noqa: F821 (PyInstaller provides Tree)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=app_info.NAME, console=False, target_arch="arm64",
          argv_emulation=False, upx=False)
coll = COLLECT(exe, a.binaries, a.datas + licenses, name=app_info.NAME, upx=False)
app = BUNDLE(coll, name=f"{app_info.NAME}.app", icon=str(ROOT / "discjockey" / "hub" / "icon" / "discjockey.icns"),
             bundle_identifier=app_info.BUNDLE_ID, version=VERSION, info_plist=app_info.info_plist(VERSION))
