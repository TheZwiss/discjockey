// The clipboard for CopyCode (and anything else that copies text).

/** Copies text to the clipboard. false = not allowed (then the caller selects the text and says "Press ⌘C"). */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (!navigator.clipboard?.writeText) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
