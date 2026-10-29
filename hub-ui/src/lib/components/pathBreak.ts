/**
 * Where a file or folder path may break across lines: only after a "/" (a folder's name and its slash stay together),
 * and after the "›" that follows a drive's name ("Example Drive › Music/Sets": the blank before "›" is a no-break one,
 * see `fitPath`, so a line never starts with "›"). Everything else, spaces inside a name included, stays on one line
 * while the name fits; `PathText` renders each piece as one unit and lets a piece break inside itself only when it
 * alone is wider than the box. The pieces joined give the path back, so copying a path copies nothing extra.
 */
export function pathSegments(path: string): string[] {
  return path.split(/(?<=\/|›[  ])/).filter((s) => s !== '');
}
