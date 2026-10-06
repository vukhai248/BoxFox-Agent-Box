/**
 * Downloads for the runtime fetcher: streaming to disk with SHA-256 verification.
 * No npm dependency; `fetch` is the Node 24 global.
 */

import { createHash } from 'node:crypto'
import * as fs from 'node:fs'
import * as path from 'node:path'
import { Readable } from 'node:stream'
import { pipeline } from 'node:stream/promises'
import { sha256File } from './hash.mjs'

export async function fetchText(url, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch
  const response = await fetchImpl(url, { redirect: 'follow' })
  if (!response.ok) throw new Error(`GET ${url} failed with HTTP ${response.status}`)
  return response.text()
}

/**
 * Stream `url` into `dest` (atomically, via `<dest>.part`) and verify its SHA-256.
 * Returns `{ file, sha256, bytes }`. A mismatch deletes the partial file and throws.
 */
export async function downloadFile(url, dest, options = {}) {
  const fetchImpl = options.fetchImpl ?? fetch
  const expected = options.expectedSha256 ? options.expectedSha256.toLowerCase() : null
  fs.mkdirSync(path.dirname(dest), { recursive: true })
  if (options.useCache !== false && fs.existsSync(dest)) {
    const cached = await sha256File(dest)
    if (expected !== null && cached === expected) {
      return { file: dest, sha256: cached, bytes: fs.statSync(dest).size, cached: true }
    }
    if (expected === null && options.trustCache) {
      return { file: dest, sha256: cached, bytes: fs.statSync(dest).size, cached: true }
    }
  }
  const part = `${dest}.part`
  const response = await fetchImpl(url, { redirect: 'follow' })
  if (!response.ok || response.body === null) {
    throw new Error(`GET ${url} failed with HTTP ${response.status}`)
  }
  const total = Number(response.headers.get('content-length') ?? '0')
  const hash = createHash('sha256')
  let bytes = 0
  const source = Readable.fromWeb(response.body)
  source.on('data', (chunk) => {
    hash.update(chunk)
    bytes += chunk.length
    options.onProgress?.(bytes, total)
  })
  await pipeline(source, fs.createWriteStream(part))
  const sha256 = hash.digest('hex')
  if (expected !== null && sha256 !== expected) {
    fs.rmSync(part, { force: true })
    throw new Error(`SHA-256 mismatch for ${url}\n  expected ${expected}\n  actual   ${sha256}`)
  }
  fs.renameSync(part, dest)
  return { file: dest, sha256, bytes }
}
