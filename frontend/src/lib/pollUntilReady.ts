/**
 * Calls fetchFn (expected to update some reactive state as a side effect),
 * retrying up to `attempts` times total with `delayMs` between each, until
 * isReady() reports true or attempts run out.
 *
 * For masking a fire-and-forget background job's race: the job (e.g. a
 * Blink sync enqueued via an arq worker) may not have finished by the time
 * its result is first read, so give it a few seconds to catch up instead of
 * showing a stale/incomplete value on the very next read. If fetchFn throws,
 * that propagates immediately - only an empty/not-ready result is retried,
 * never a real failure.
 */
export async function pollUntilReady(
  fetchFn: () => Promise<void>,
  isReady: () => boolean,
  attempts: number,
  delayMs: number,
): Promise<void> {
  await fetchFn();
  for (let attempt = 1; attempt < attempts && !isReady(); attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, delayMs));
    await fetchFn();
  }
}
