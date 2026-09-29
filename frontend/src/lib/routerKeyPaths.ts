// The five key-ring routes of the BoxFox router, in one place.
//
// Round 29 gives one connection a *ring* of keys and five routes to manage it
// (`router/src/server.mjs`): add, replace one, remove one, try one now, and import the
// keys of another connection. The UI owns no route string of its own — a rename on the
// router side is a change in this file and nowhere else.
//
//   POST   {connection}/keys                    { label?, key? }  -> 201 connection
//   PATCH  {connection}/keys/{keyId}            { key?, label? }  -> 200 connection
//   DELETE {connection}/keys/{keyId}                              -> 200 connection
//   POST   {connection}/keys/{keyId}/try        {}                -> 200 { connection, probe }
//   POST   {connection}/keys/import             { fromConnectionId } -> 200 connection
//
// Deleting a *connection* that still holds keys is refused by the router with
// `409 KEYS_PRESENT`; that path stays `DELETE {connection}` and is not wrapped here.
const connectionPath = (connectionId: string) => `/api/router/connections/${encodeURIComponent(connectionId)}`

/** The ring itself: `GET` never exists — keys travel inside `GET /api/router/state`. */
export const connectionKeysPath = (connectionId: string) => `${connectionPath(connectionId)}/keys`

/** One key: replace its secret or its label, or delete it. */
export const connectionKeyPath = (connectionId: string, keyId: string) => `${connectionKeysPath(connectionId)}/${encodeURIComponent(keyId)}`

/** Take one key out of its cooldown and let the router test it once. */
export const connectionKeyTryPath = (connectionId: string, keyId: string) => `${connectionKeyPath(connectionId, keyId)}/try`

/** Move every key of another connection of the same provider to the end of this ring. */
export const connectionKeysImportPath = (connectionId: string) => `${connectionKeysPath(connectionId)}/import`

/** Reveal the decrypted API key / token so the user can inspect or copy it. */
export const connectionKeyRevealPath = (connectionId: string, keyId: string) => `${connectionKeyPath(connectionId, keyId)}/reveal`

