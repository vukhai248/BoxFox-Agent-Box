/** Lost HTTP responses retry the same owner intent, never a fresh admission. */
const invocations = new Map<string, string>()
export function continuityInvocation(binding: unknown): string {
  const key = JSON.stringify(binding)
  let id = invocations.get(key)
  if (!id) { id = crypto.randomUUID(); invocations.set(key, id) }
  return id
}
