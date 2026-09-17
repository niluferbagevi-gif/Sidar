/**
 * Shared "turn a caught value into a display string" helper.
 *
 * Previously copy-pasted into 6 files under 3 slightly different signatures
 * (a bare `(error) => error instanceof Error ? error.message : String(error)`,
 * a hardcoded-fallback variant, and a caller-supplied-fallback variant) that
 * had quietly drifted apart. `fallback` defaults to `String(error)`, so
 * omitting it reproduces the first variant exactly; passing it reproduces the
 * other two.
 */
export function errorMessage(error: unknown, fallback: string = String(error)): string {
  return error instanceof Error ? error.message : fallback;
}
