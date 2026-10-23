// What a page's body already says, so the shell's banner for it stays off there (spec §11: a state is said once, where
// the user looks for it). This is the one way a page takes over a banner: the view that says the state in its body
// sets it while it shows it and clears it when it goes (`sayInBody` returns the clear, an effect's teardown). The
// shell reads only this store, never a page's view logic (final review I2), and a view that doesn't say a state
// leaves its banner on, so no view loses the warning (I1).
import { writable } from 'svelte/store';

export type SaidInBody = { console?: boolean; spotify?: boolean };

export const bannersSaidInBody = writable<SaidInBody>({});

export function sayInBody(said: SaidInBody): () => void {
  // the clear withdraws only this claim: an outgoing view's teardown can run after the incoming view's claim
  const mine = { ...said };
  bannersSaidInBody.set(mine);
  return () => bannersSaidInBody.update((s) => (s === mine ? {} : s));
}
