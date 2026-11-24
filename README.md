# Discjockey

**Discjockey is a free, open-source Mac app for DJs. It turns your Spotify, Qobuz, SoundCloud and YouTube Music
playlists into a library of verified lossless AIFF files, ready for rekordbox, and keeps that library in step as your
playlists change.**

[**Download for Mac**](https://github.com/TheZwiss/discjockey/releases/latest) &nbsp;·&nbsp; Apple Silicon, macOS 12 or
later &nbsp;·&nbsp; Free, GPL-3.0 &nbsp;·&nbsp; [Manual](docs/manual.md)

<img src="docs/readme/app-dashboard.png" alt="The Discjockey dashboard: 54 % of the library lossless, three things that need you, every playlist folder with its quality, and the last runs">

You find music in streaming apps, but you play sets from files. Discjockey does the work in between: it finds each
track in the best quality available, checks that a "lossless" file really is lossless, names it `Artist - Title`, puts
it in the folder of its playlist and does it again every time a playlist changes.

## What it does

- **Reads your playlists.** Spotify, Qobuz, SoundCloud (sets and likes) and YouTube Music. Each playlist becomes a
  folder, and a track that sits in several playlists is downloaded once.
- **Shows the plan first.** Before anything downloads you see what is new and what is missing, untick what should wait
  and choose how much to do today.
- **Gets the best version it can.** Qobuz first, saved as 16-bit AIFF. If Qobuz doesn't have a track: the artist's own
  file, then a premium stream (YouTube Premium or SoundCloud Go+), then a free stream.
- **Checks every file.** It measures the spectrum and tells real lossless apart from good lossy, audibly weak and
  "fake lossless" (a lossless file made from a lossy source). Each track shows its quality and where it came from.
- **Upgrades without losing your cues.** When a lossless version of a lossy track turns up, you listen to both and
  swap it in; rekordbox keeps your cue points, loops and beatgrid.
- **Converts your own music to AIFF** (16-bit, 44.1 kHz, the format every CDJ plays) when you ask, with undo.
- **Never deletes a music file.** Anything it replaces goes to `Superseded/`.

## Screenshots

<table>
  <tr>
    <td width="50%" valign="top"><img src="docs/readme/app-sync.png" alt="The Sync page: playlists with switches on the left, the plan with 228 tracks in five kinds in the middle, today's amount, the weekly checks and Start sync on the right"><br><sub><b>Sync</b>: the whole plan before anything downloads.</sub></td>
    <td width="50%" valign="top"><img src="docs/readme/app-sync-running.png" alt="A sync running: track 3 of 5 downloading from YouTube Music, with the steps search, download, check, convert and analyse"><br><sub><b>A sync you can follow</b>, and stop safely at any time.</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/readme/app-library.png" alt="The Library: a playlist's tracks with their quality badges, and the details of a lossless track with its spectrum, player, format and source"><br><sub><b>Library</b>: every track with its quality, spectrum and source.</sub></td>
    <td width="50%" valign="top"><img src="docs/readme/app-todo.png" alt="The To-do page: upgrades ready, songs not found and weak versions, with an upgrade open on the right comparing the current file and the lossless one"><br><sub><b>To-do</b>: upgrades ready, songs not found, weak versions.</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/readme/app-playlists.png" alt="The Playlists page with ten playlists in priority order and the Tidy up files panel listing the files that would move"><br><sub><b>Playlists</b>: drag to set the priority; tidy up with a preview.</sub></td>
    <td width="50%" valign="top"><img src="docs/readme/app-library-folders.png" alt="The Library showing a watched folder of the user's own music with its subfolders as crates"><br><sub><b>Music you already have</b>: your own folders, read where they are.</sub></td>
  </tr>
  <tr>
    <td width="50%" valign="top"><img src="docs/readme/app-settings.png" alt="Settings: where your music comes from, best first: Qobuz lossless, the artist's own file, premium streams at about 256 kbps, free streams at about 130 kbps"><br><sub><b>Settings</b>: the order it tries for every song, and your logins.</sub></td>
    <td width="50%" valign="top"><img src="docs/readme/app-limits.png" alt="The Download limits page: Qobuz at 37 of 80 today, the daily limit of 60 and the last 14 days"><br><sub><b>Download limits</b>: your own daily limit per service.</sub></td>
  </tr>
</table>

## Questions DJs ask

**Does it work with rekordbox?** Yes, rekordbox is what it is built for. You import the `Library` folder into
rekordbox, and the comment column says where each file came from and how good it is. Upgrades and AIFF conversions
update rekordbox's library itself (only while rekordbox is closed) and keep your cues, loops, beatgrid, key, BPM,
ratings and playlists. See [rekordbox](docs/manual.md#rekordbox).

**Is it really lossless?** Only what it can verify. Tracks from Qobuz come as lossless 16-bit AIFF, and every file is
checked and labelled. If a track is only available as a stream, you get a good file, not a lossless one, and Discjockey
says so and looks again later for a lossless version. Without a Qobuz subscription, only an artist's own file can come
in lossless.

**Does it delete my files?** Never. A file that is replaced moves to `Superseded/`, and every replace can be undone.

**Can I use music I already have?** Yes. Add your folders and Discjockey reads them where they are, never downloads a
song you already own and points out duplicates. See [Your existing music](docs/manual.md#your-existing-music).

**Does it need a Qobuz subscription?** For lossless files, yes. Spotify Premium is needed only to sync Spotify
playlists; Qobuz, SoundCloud and YouTube Music playlists don't need it.

**Does it run on Windows or an Intel Mac?** No. It is a Mac app for Apple Silicon (M1 or later), macOS 12 Monterey or
later.

## Install

1. Download `Discjockey-<version>.dmg` from the [latest release](https://github.com/TheZwiss/discjockey/releases/latest),
   open it and drag **Discjockey** onto **Applications**.
2. Open Discjockey. Discjockey isn't registered with Apple, so macOS shows a warning and doesn't open it. Click
   **Done**.

   <img src="docs/readme/open-anyway-1-warning.png" width="274" alt="The warning: Discjockey Not Opened, with Move to Trash and Done">

3. Open **System Settings**, then **Privacy & Security**, scroll to the line about Discjockey.

   <img src="docs/readme/open-anyway-2-privacy.png" width="560" alt="Privacy &amp; Security: Discjockey was blocked to protect your Mac, with Open Anyway">

4. Click **Open Anyway**. Confirm with your password or Touch ID. You do this once for every version you download.

   <img src="docs/readme/open-anyway-3-confirm.png" width="269" alt="The second warning, with Open Anyway"> <img src="docs/readme/open-anyway-4-password.png" width="278" alt="macOS asks for Touch ID or the password">

What to do if the line is gone is in the
[manual](docs/manual.md#install-and-open-anyway).

## Quick start

1. Open Discjockey. **Setup** guides you: choose your music folder, sign in to Qobuz (or choose **I don't have Qobuz**)
   and connect Spotify if you use it.
2. Paste the link of a playlist and click **Add to the list**. Add more later; their order decides which folder a
   shared track goes to.
3. Open **Sync**, look at the plan and click **Start sync**.
4. Import the `Library` folder of your music folder into rekordbox.
5. Sync again whenever your playlists change.

More in [One-time setup](docs/manual.md#one-time-setup) and [Daily use](docs/manual.md#daily-use).

## Use with an AI agent

Discjockey also has a command-line interface that an AI agent (Claude, ChatGPT or another) can run for you: see what
needs doing, preview a sync, upgrade tracks. It comes with safety rules an agent must keep. Point your agent at
[AGENTS.md](https://github.com/TheZwiss/discjockey/blob/main/AGENTS.md), and tell it to run
`/Applications/Discjockey.app/Contents/MacOS/Discjockey help --json` to list every command.

## Manual

The [full manual](docs/manual.md) covers everything, section by section:
[Requirements](docs/manual.md#requirements) · [Setup](docs/manual.md#one-time-setup) ·
[Settings](docs/manual.md#settings) · [playlists.txt](docs/manual.md#playliststxt) ·
[Your existing music](docs/manual.md#your-existing-music) · [Daily use](docs/manual.md#daily-use) ·
[The Library page](docs/manual.md#the-library-page) · [Upgrades](docs/manual.md#upgrades) ·
[Making files AIFF](docs/manual.md#making-files-aiff) · [rekordbox](docs/manual.md#rekordbox) ·
[When something breaks](docs/manual.md#when-something-breaks)

## Legal note and account risk

Discjockey is a tool that runs on your Mac. It reads your Spotify, Qobuz, SoundCloud and YouTube Music playlists and
downloads their tracks with your own accounts. It comes with no music and no accounts. You need your own accounts for
the services you use, and you are responsible for following their terms of use. Downloading from Qobuz with streamrip
is against Qobuz's terms of use: the pauses, the daily limit and the automatic pause after repeated failures reduce the
risk that Qobuz notices, but can't remove it. More in [Account risk](docs/manual.md#account-risk).

Spotify, Qobuz, SoundCloud and YouTube names and logos are trademarks of their owners, used only to show where a
playlist comes from; Discjockey isn't affiliated with them.

## Licence and contributing

Free software under the GNU General Public License, version 3 (GPL-3.0); the full text is in [LICENSE](LICENSE).
The programs it includes (ffmpeg, ffprobe, deno, yt-dlp and others) come with their own licences: Settings → This Mac
→ **Show licences** opens them. To run Discjockey from its source code or help with it, see
[CONTRIBUTING.md](CONTRIBUTING.md).
