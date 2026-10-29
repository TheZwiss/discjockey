<script lang="ts">
  // ▶ on one file of an import to-do (a question's file, a duplicate group's copies; plan library stage 4, 7.2/7.3).
  // It plays through the player as a queue of the item's playable files, starting at this one, so the foot shows it
  // (position, ⏭ to the next copy) and its link selects the item again (`file:<id>`, selectFromTrack). Pressed again
  // while it is the one playing, it pauses or resumes. Off (grey ring) when the file can't play: offline, no address.
  import type { FileSide } from '$lib/bridge/types';
  import { PlayButton } from '$lib/components';
  import { player } from '$lib/stores/player';
  import { fileName, fileQueue, fileQueueId, fileState } from './todoModel';

  let { files, file, cover = null, test }: {
    /** every file of the item, in the order shown (the queue) */
    files: FileSide[]; file: FileSide; cover?: string | null; test?: string;
  } = $props();

  const state = $derived(fileState($player, file));
  const off = $derived(!file.online || !file.audio_url);

  function press() {
    if ($player.track_id === fileQueueId(file)) { player.toggle(); return; }
    const q = fileQueue(files, file.file_id, cover);
    if (!q) return;
    player.playQueue({ items: q.items, start: q.start, source: { label: 'To-do', href: '#/todo' },
      resolve: async (id) => q.urls.get(id) ?? null });
  }
</script>

<PlayButton {state} size={22} disabled={off} onclick={press} {test} subject={fileName(file.path)} />
