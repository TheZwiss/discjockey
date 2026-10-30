<script lang="ts">
  // Which service a playlist is read from (plan library stage 5 D7): the service's own logo in its own colours, 14 px,
  // unchanged (serviceLogos.ts). It is the colour rule's one exception: an image that names a service, not a signal,
  // so it never takes a quality, accent or dim colour of its own. `dim` halves it for a mark that stands alone beside
  // something switched off; inside a row that dims as a whole (a switched-off playlist at half strength) it dims with
  // the row, so the row never passes `dim` as well (that would be a quarter). `label` names it for VoiceOver
  // ("{Service} playlist" by default). `data-service-mark` marks it for the rule checker and for reviews.
  import { LOGO_NAMES, SERVICE_LOGOS, type LogoKey } from './serviceLogos';

  let { service, dim = false, label }: { service: LogoKey; dim?: boolean; label?: string } = $props();
</script>

<span class="mark" class:dim role="img" aria-label={label ?? `${LOGO_NAMES[service]} playlist`}
  data-service-mark={service}>{@html SERVICE_LOGOS[service]}</span>

<style>
  .mark { display: inline-grid; place-items: center; flex: none; width: 14px; height: 14px; line-height: 0; }
  .mark :global(svg) { display: block; }
  .dim { opacity: var(--dim-locked); }
</style>
