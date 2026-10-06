/**
 * Hashing helpers shared by the runtime fetcher and the app builder.
 *
 * Everything is content-addressed by SHA-256:
 *   - artifacts   : the file itself (upstream-published digest where one exists);
 *   - blocks      : a manifest digest — sha256 over the sorted lines
 *                   `"<sha256>  <relative path>"` of every file in the block.
 *
 * The manifest digest is small to store (one line in the lock) yet detects any
 * added, removed or modified file in the block.
 */

import { createHash } from 'node:crypto'
import * as fs from 'node:fs'
import * as path from 'node:path'

export function sha256Buffer(buffer) {
  return createHash('sha256').update(buffer).digest('hex')
}

export function sha256Text(text) {
  return createHash('sha256').update(text, 'utf8').digest('hex')
}

export function sha256File(file) {
  return new Promise((resolve, reject) => {
    const hash = createHash('sha256')
    const stream = fs.createReadStream(file)
    stream.on('error', reject)
    stream.on('data', (chunk) => hash.update(chunk))
    stream.on('end', () => resolve(hash.digest('hex')))
  })
}

/** Sorted, relative, forward-slash file list of a directory tree. */
export function listFiles(root) {
  const files = []
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) walk(full)
      else if (entry.isFile()) files.push(full)
      else if (entry.isSymbolicLink()) files.push(full)
    }
  }
  walk(root)
  return files.sort()
}

/** `[{ path, sha256, size }]` for every file under `root` (path relative, `/`-separated). */
export async function fileManifest(root) {
  const entries = []
  for (const file of listFiles(root)) {
    const stat = fs.statSync(file)
    if (!stat.isFile()) continue
    entries.push({
      path: path.relative(root, file).split(path.sep).join('/'),
      sha256: await sha256File(file),
      size: stat.size,
    })
  }
  entries.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0))
  return entries
}

export function manifestDigest(entries) {
  const lines = entries.map((entry) => `${entry.sha256}  ${entry.path}`)
  return sha256Text(`${lines.join('\n')}\n`)
}

/** `{ files, bytes, sha256 }` — the summary stored per block in a lock file. */
export async function blockSummary(root) {
  const entries = await fileManifest(root)
  return {
    files: entries.length,
    bytes: entries.reduce((total, entry) => total + entry.size, 0),
    sha256: manifestDigest(entries),
  }
}

export function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KiB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MiB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GiB`
}
