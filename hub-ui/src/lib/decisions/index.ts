// The decisions a track can wait for, shared by To-do's and the Library's details (mockup todo-decisions): the
// upgrade, the rekordbox check a replace leaves, and duplicates. Each is its cards (the panel's head) and its foot,
// reading one flow (flows.svelte.ts), so the same choice does the same thing on both pages.
export { default as UpgradeCards } from './UpgradeCards.svelte';
export { default as UpgradeFoot } from './UpgradeFoot.svelte';
export { default as CheckCards } from './CheckCards.svelte';
export { default as CheckFoot } from './CheckFoot.svelte';
export { default as DuplicateChoice } from './DuplicateChoice.svelte';
export { default as DuplicateFoot } from './DuplicateFoot.svelte';
export { default as FilePlay } from './FilePlay.svelte';
export { DuplicateFlow, UpgradeFlow } from './flows.svelte';
export { canSwap, decisionFor, type Decision, type Way } from './decisionModel';
