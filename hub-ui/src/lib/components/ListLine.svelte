<script lang="ts">
  // One quiet line among a list's rows where a group's rows would be (design system §7, beside `ListSection`): the
  // group has nothing to list and says so in one line, at a section head's height (`--h-section`) and inset, in the
  // muted grey at the small size, so the list keeps its rhythm and the next head follows in place. Library: a
  // playlist's own part is empty above its folder's other files ("This playlist is empty." over `Also in this folder`).
  // A whole list with nothing in it is an `EmptyState`, never this.
  let { text, test }: { text: string; test?: string } = $props();
</script>

<div class="line" data-test={test}>{text}</div>

<style>
  /* a block, not a flex box, so a line too long for a narrow list ends in "…" */
  .line { height: var(--h-section); line-height: var(--h-section); padding: 0 var(--s-4); min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted); font-size: var(--fs-small); }
</style>
