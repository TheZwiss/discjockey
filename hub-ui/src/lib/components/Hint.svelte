<script lang="ts">
  // The short explanation under a control (design system §6): at most one line. Longer text is cut with an ellipsis
  // and readable in full on hover (`title`); anything that needs more than a line belongs in an InfoTip or a
  // NoteCard, and the rule checker flags a hint over 90 characters outside a surface. `data-hint` marks it. Other
  // attributes (`data-test`) go onto the line.
  // `tone="problem"`: the error the user's own action just caused, beside that control (Stop safely's refusal): red,
  // announced at once (`role=alert`), the backend's message verbatim. Its length is the backend's, not the page's, and
  // it stays one cut line, so the block marks it `data-note` (a page never writes the marker itself, final review I5).
  import type { HTMLAttributes } from 'svelte/elements';

  type Props = Omit<HTMLAttributes<HTMLParagraphElement>, 'children' | 'title'> & { text: string; tone?: 'muted' | 'problem';
    /** up to three lines instead of one: only for a refusal that says what to do instead (FolderField) */
    wrap?: boolean };
  let { text, tone = 'muted', wrap = false, class: className, ...rest }: Props = $props();
  const problem = $derived(tone === 'problem');
</script>

<p {...rest} class="hint {className ?? ''}" class:problem class:wrap data-hint role={problem ? 'alert' : rest.role}
  data-note={problem ? 'problem' : undefined} title={text}>{text}</p>

<style>
  .hint {
    margin: 0; min-width: 0; font-size: var(--fs-small); line-height: 1.4; color: var(--text-muted);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .problem { color: var(--q-weak); }
  .wrap { white-space: normal; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 3; line-clamp: 3; }
</style>
