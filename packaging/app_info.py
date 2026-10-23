"""Info.plist of Discjockey.app (spec public-release §5, §6.6). discjockey.spec imports it; tests pin it."""
NAME = "Discjockey"
BUNDLE_ID = "io.github.thezwiss.discjockey"
MIN_MACOS = "12.0"  # the highest minimum of the bundled parts (ffmpeg, deno: 12.0); machos.py fails the build above it

# The text macOS shows when it asks once for a folder (spec §6.3). No Info.plist key exists for the keychain prompt
# ("Chrome Safe Storage") or Full Disk Access (Safari logins): macOS words those itself, with the app's name.
USAGE = {
    "NSDownloadsFolderUsageDescription": "Discjockey reads the music files you drop onto its window from Downloads.",
    "NSDesktopFolderUsageDescription": "Discjockey reads the music files you drop onto its window from the Desktop.",
    "NSDocumentsFolderUsageDescription": ("Discjockey keeps your library in your music folder in Documents, and reads "
                                          "music files you drop onto its window from there."),
    "NSRemovableVolumesUsageDescription": "Discjockey keeps your library in your music folder on this drive.",
    "NSNetworkVolumesUsageDescription": "Discjockey keeps your library in your music folder on this network drive.",
}


def info_plist(version: str) -> dict:
    return {
        "CFBundleName": NAME, "CFBundleDisplayName": NAME, "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleShortVersionString": version, "CFBundleVersion": version,
        "LSMinimumSystemVersion": MIN_MACOS, "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.music",
        "NSHumanReadableCopyright": "Discjockey is free software under the GPL-3.0.",
        **USAGE,
    }
