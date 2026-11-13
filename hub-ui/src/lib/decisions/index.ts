// The decisions a track can wait for, shared by To-do's and the Library's details (mockup todo-decisions): the
// upgrade, the rekordbox check a replace leaves, duplicates and, since stage D, the AIFF card
// (Convert, clean names). Each is its cards (the panel's head) and its foot, reading one flow (flows.svelte.ts), so the same choice does the same thing on both pages.
export { default as UpgradeCards } from './UpgradeCards.svelte';
export { default as UpgradeFoot } from './UpgradeFoot.svelte';
export { default as CheckCards } from './CheckCards.svelte';
export { default as CheckFoot } from './CheckFoot.svelte';
export { default as DuplicateChoice } from './DuplicateChoice.svelte';
export { default as DuplicateFoot } from './DuplicateFoot.svelte';
export { default as AiffCard } from './AiffCard.svelte';
export { default as AiffFoot } from './AiffFoot.svelte';
export { default as FilePlay } from './FilePlay.svelte';
export { default as UpgradeSelection } from './UpgradeSelection.svelte';
export { default as BatchCheckCards } from './BatchCheckCards.svelte';
export { default as BatchCheckFoot } from './BatchCheckFoot.svelte';
export { BATCH_JOBS, AiffFlow, ChecksFlow, DuplicateFlow, UpgradeBatchFlow, UpgradeFlow, upgradeBatch, type BatchView } from './flows.svelte';
export { aiffAction, aiffBlocked, aiffLabel, aiffShown, aiffVariant } from './aiffModel';
export { canSwap, decisionFor, upgradeWays, type Decision, type Way } from './decisionModel';
export { default as AiffBatchPanel } from './AiffBatchPanel.svelte';
export { AiffBatchFlow, aiffBatch, type AiffPlanRead, type AiffRunView } from './flows.svelte';
export { scopeKey as aiffScopeKey, type AiffOrigin } from './aiffBatchModel';
