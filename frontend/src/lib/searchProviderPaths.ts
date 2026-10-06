// The seven search-provider routes of the BoxFox router, in one place.
//
// Settings → Provider → Web Search lets the owner pick one search source, store its
// key, try it, reveal it and delete it (`router/src/server.mjs`). The UI owns no route
// string of its own — a rename on the router side is a change in this file and nowhere
// else. All of them sit behind the router's `admin(req)` gate.
//
//   GET    {search}                      -> { activeProviderId, revision, providers[] }
//   POST   {search}/providers            { providerId, apiKey?, endpoint?, accountId? } -> 201 view
//   PATCH  {search}/providers/{id}       { apiKey?, endpoint?, accountId? }             -> 200 view
//   DELETE {search}/providers/{id}                                                      -> 200 { deleted: true }
//   PUT    {search}/active               { providerId | null }                          -> 200 { activeProviderId, revision }
//   POST   {search}/providers/{id}/reveal                                               -> 200 { id, key }
//   POST   {search}/providers/{id}/test                                                 -> 200 test result
//
// `GET {search}/resolve` exists for the Python harness only and is deliberately not
// wrapped here: the browser must never hold the raw key that route returns.

/** The whole search section of the router snapshot. */
export const searchPath = () => '/api/router/search'

/** The provider collection: `POST` creates the one entry for a provider id. */
export const searchProvidersPath = () => `${searchPath()}/providers`

/** One provider entry: `PATCH` edits it (`apiKey: ""` clears the key), `DELETE` removes it. */
export const searchProviderPath = (providerId: string) => `${searchProvidersPath()}/${encodeURIComponent(providerId)}`

/** Reveal the stored key of one entry — the only call that ever returns the raw secret. */
export const searchProviderRevealPath = (providerId: string) => `${searchProviderPath(providerId)}/reveal`

/** Ask the router to call the provider once and record the verdict. */
export const searchProviderTestPath = (providerId: string) => `${searchProviderPath(providerId)}/test`

/** Which entry is in use; `null` means the built-in default. */
export const searchActivePath = () => `${searchPath()}/active`
