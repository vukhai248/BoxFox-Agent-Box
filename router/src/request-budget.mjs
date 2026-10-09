/** Request deadlines are separate from a whole agent turn and HTTP body receipt. */
export const LARGE_OUTPUT_TOKENS = 8000;
// A big transcript is slow to its first token even when the output ceiling is small. The deadline
// used to key on `max_tokens` alone, so a ~108k-token owner turn asking for 4096 tokens took the
// 90s quick profile and died on provider latency (measured 2026-10-09: three `TIMEOUT`s at exactly
// 90000 ms on the long-task owner turns, while 8k-token children of the same provider answered in
// seconds). 200_000 characters of `messages`+`tools` is roughly 50k tokens — a fifth of the default
// 256k window. The agent side measures the same request in bytes before it picks its own read
// backstop (`agentbox.agent_core.limits.ROUTER_LARGE_INPUT_BYTES`); the two numbers are deliberately
// the same size so both sides take the large profile together.
export const LARGE_INPUT_CHARS = 200000;
export function serializedChars(value) {
  if (value === undefined || value === null) return 0;
  try {
    return JSON.stringify(value).length;
  } catch {
    return 0;
  }
}
export function largeInput(body) {
  if (!body || typeof body !== 'object') return false;
  return serializedChars(body.messages) + serializedChars(body.tools) >= LARGE_INPUT_CHARS;
}
export function largeRequestDeadline(value = process.env.BOXFOX_ROUTER_LARGE_REQUEST_MS) {
  const applied = value === undefined ? 180000 : Number(value);
  if (![90000, 180000, 240000].includes(applied)) {
    throw new Error('BOXFOX_ROUTER_LARGE_REQUEST_MS must be 90000, 180000 or 240000');
  }
  return applied;
}
