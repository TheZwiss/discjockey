// The screenshot script waits for [data-page-ready]. Pages call markReady('<page>') once their first data shows.
export function markReady(page: string): void {
  if (typeof document !== 'undefined') document.body.dataset.pageReady = page;
}
export function clearReady(): void {
  if (typeof document !== 'undefined') delete document.body.dataset.pageReady;
}
