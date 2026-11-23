"""The words of changes to playlists.txt (issue 39 V4.2a): the rules of the list (`playlists_file`), the refusals of one
change and of a save, and what `history` says of a change. Kept apart from `words.py`: `playlists_file` is imported by
`config`, which must not pull in yt-dlp before `tools.activate()`, and `words.py` imports `convert`, which does."""
from __future__ import annotations

# One sentence for each way a folder name, a link or a change can be wrong. The first four are the window's own
# (`addRowModel.ts` `folderProblem`).
FOLDER_NEEDED = "A folder name is needed."
FOLDER_SLASH = 'A folder name can\'t contain "/".'
FOLDER_PICK_ANOTHER = "Pick another folder name."
FOLDER_USED = "Another playlist already uses the folder {folder}."
PLAYLIST_LISTED = "This playlist is already in your list."
PLAYLIST_NOT_FOUND = "None of your playlists is called {name}."
PLAYLIST_TWO = "{name} names more than one of your playlists: say its folder name."
PLAYLIST_OP_NEEDS = "A {op} change needs {fields}."
PLAYLIST_OP_UNKNOWN = "Discjockey can't make the change {op} to your playlists."
PLAYLIST_OP_FIELD = "{field} is not part of a {op} change."
PLAYLIST_OP_TYPE = "{field} in a playlist change takes {kind}."
PLAYLIST_OP_KINDS = {"int": "a whole number", "bool": "true or false", "str": "text"}  # the words of PLAYLIST_OP_TYPE's kind
PLAYLIST_PLACE = "A place in your playlists goes from 1 to {n}."
PLAYLIST_FILE_FULL_PATH = "Give the playlists file as a full path."
PLAYLIST_FILE_MISSING = "There is no file at {path}."
# What a change to playlists.txt says in `history` (`playlists_file.change_log`), by the operation's name in the log;
# `{folder}`, `{at}`, `{old}`, `{new}`, `{to}` and `{file}` are filled from the change.
PLAYLIST_LOGGED = {
    "playlist_add": "Added the playlist {folder} at place {at}.",
    "playlist_remove": "Removed the playlist {folder}. Its files stay in your library.",
    "playlist_rename": "Renamed the playlist {old} to {new}.",
    "playlist_move": "Moved the playlist {folder} from place {old} to place {to}.",
    "playlist_enable": "Switched the playlist {folder} on.",
    "playlist_disable": "Switched the playlist {folder} off. Its files stay.",
    "playlist_edit": "Replaced your playlists with the list in {file}.",
    "playlist_saved": "Saved your playlists in the window.",
    "liked_music_add": "Added Liked music as the playlist {folder}.",
}
PLAYLIST_ADD_LINK = ("This isn't a full playlist link. Check it first: its answer has the link to add.")
PLAYLIST_ADD_NEEDS_FOLDER = ("Discjockey hasn't read this playlist yet, so it has no name for its folder. Check the "
                             "link first, or give a folder name.")
PLAYLIST_CHECK_LINK_WHY = "reads the link, so you have the full link to add"
PLAYLIST_CHECK_NAME_WHY = "reads the playlist, so Discjockey knows its name for the folder"
PLAYLIST_CHECK_COUNT_WHY = "reads the playlist once, so this preview counts its songs"
SAVE_LINES_OR_OP = "Send the playlist rows or one change, not both."
SAVE_NOTHING = "Send the playlist rows or one change to save."
PLAYLISTS_VERSION_CHANGED = "playlists.txt changed since that version, so nothing was done."
PLAYLISTS_LIST_WHY = "your playlists as they are now, with their version"
SAVE_NEEDS_CHOICE_ONE = ("This change puts 1 file in another folder: say whether to move it or leave it where it is. "
                         "Nothing was done.")
SAVE_NEEDS_CHOICE = ("This change puts {n} files in another folder: say whether to move them or leave them where they "
                     "are. Nothing was done.")
PLAYLIST_LOGGED_ADD_OFF = "Added the playlist {folder} at place {at}, switched off."
