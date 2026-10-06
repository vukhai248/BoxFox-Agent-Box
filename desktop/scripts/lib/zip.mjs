/**
 * Minimal, dependency-free ZIP reader/writer.
 *
 * The runtime fetcher has to unpack the Node win-x64 zip, the CPython embeddable zip
 * and the downloaded wheels on the build machine — with no npm dependency and no
 * assumption that `unzip` exists (it does not on Windows). Store (0) and deflate (8)
 * are the only methods a wheel or a Python/Node distribution uses; ZIP64 is rejected
 * loudly instead of silently producing a truncated file.
 */

import { deflateRawSync, inflateRawSync } from 'node:zlib'
import * as fs from 'node:fs'
import * as path from 'node:path'

const EOCD_SIGNATURE = 0x06054b50
const CENTRAL_SIGNATURE = 0x02014b50
const LOCAL_SIGNATURE = 0x04034b50

const CRC_TABLE = (() => {
  const table = new Int32Array(256)
  for (let index = 0; index < 256; index += 1) {
    let value = index
    for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
    table[index] = value
  }
  return table
})()

export function crc32(buffer) {
  let crc = -1
  for (let index = 0; index < buffer.length; index += 1) {
    crc = CRC_TABLE[(crc ^ buffer[index]) & 0xff] ^ (crc >>> 8)
  }
  return (crc ^ -1) >>> 0
}

function findEocd(buffer) {
  const minimum = Math.max(0, buffer.length - 0xffff - 22)
  for (let offset = buffer.length - 22; offset >= minimum; offset -= 1) {
    if (buffer.readUInt32LE(offset) === EOCD_SIGNATURE) return offset
  }
  throw new Error('Not a ZIP file (end-of-central-directory not found).')
}

/** Central directory of a zip buffer: `[{ name, method, compressedSize, size, offset, mode }]`. */
export function readZipEntries(buffer) {
  const eocd = findEocd(buffer)
  const entryCount = buffer.readUInt16LE(eocd + 10)
  let pointer = buffer.readUInt32LE(eocd + 16)
  const entries = []
  for (let index = 0; index < entryCount; index += 1) {
    if (buffer.readUInt32LE(pointer) !== CENTRAL_SIGNATURE) {
      throw new Error(`Corrupt central directory at entry ${index}.`)
    }
    const flags = buffer.readUInt16LE(pointer + 8)
    const method = buffer.readUInt16LE(pointer + 10)
    const compressedSize = buffer.readUInt32LE(pointer + 20)
    const size = buffer.readUInt32LE(pointer + 24)
    const nameLength = buffer.readUInt16LE(pointer + 28)
    const extraLength = buffer.readUInt16LE(pointer + 30)
    const commentLength = buffer.readUInt16LE(pointer + 32)
    const externalAttributes = buffer.readUInt32LE(pointer + 38)
    const offset = buffer.readUInt32LE(pointer + 42)
    const name = buffer.toString('utf8', pointer + 46, pointer + 46 + nameLength)
    const extra = buffer.subarray(pointer + 46 + nameLength, pointer + 46 + nameLength + extraLength)
    let extraPointer = 0
    while (extraPointer + 4 <= extra.length) {
      const fieldId = extra.readUInt16LE(extraPointer)
      const fieldSize = extra.readUInt16LE(extraPointer + 2)
      if (fieldId === 0x0001) throw new Error(`ZIP64 entries are not supported (${name}).`)
      extraPointer += 4 + fieldSize
    }
    if ((flags & 0x1) !== 0) throw new Error(`Encrypted zip entry is not supported (${name}).`)
    entries.push({
      name,
      method,
      compressedSize,
      size,
      offset,
      mode: (externalAttributes >>> 16) & 0xffff,
    })
    pointer += 46 + nameLength + extraLength + commentLength
  }
  return entries
}

/** Extract a zip buffer into `destDir`. Returns `{ files, bytes }`. */
export function extractZipBuffer(buffer, destDir, options = {}) {
  const filter = options.filter ?? (() => true)
  /** Optional remap: (entryName) => absolute destination file path | null to skip. */
  const map = options.map ?? null
  const entries = readZipEntries(buffer)
  let files = 0
  let bytes = 0
  for (const entry of entries) {
    const name = entry.name.replace(/\\/g, '/')
    if (name.endsWith('/')) continue
    if (!filter(name)) continue
    if (name.includes('\0') || name.split('/').includes('..')) throw new Error(`Unsafe zip entry: ${entry.name}`)
    if (buffer.readUInt32LE(entry.offset) !== LOCAL_SIGNATURE) throw new Error(`Corrupt local header for ${entry.name}`)
    const localNameLength = buffer.readUInt16LE(entry.offset + 26)
    const localExtraLength = buffer.readUInt16LE(entry.offset + 28)
    const dataStart = entry.offset + 30 + localNameLength + localExtraLength
    const compressed = buffer.subarray(dataStart, dataStart + entry.compressedSize)
    let data
    if (entry.method === 0) data = Buffer.from(compressed)
    else if (entry.method === 8) data = inflateRawSync(compressed)
    else throw new Error(`Unsupported zip method ${entry.method} for ${entry.name}`)
    if (data.length !== entry.size) throw new Error(`Size mismatch for ${entry.name} (${data.length} != ${entry.size})`)
    let target = path.join(destDir, ...name.split('/'))
    if (map) {
      const mapped = map(name)
      if (mapped === null) continue
      target = mapped
    }
    fs.mkdirSync(path.dirname(target), { recursive: true })
    fs.writeFileSync(target, data)
    if (process.platform !== 'win32' && entry.mode && (entry.mode & 0o111) !== 0) {
      try {
        fs.chmodSync(target, (entry.mode & 0o777) || 0o644)
      } catch {
        // Best effort only.
      }
    }
    files += 1
    bytes += data.length
  }
  return { files, bytes }
}

export function extractZipFile(zipFile, destDir, options = {}) {
  return extractZipBuffer(fs.readFileSync(zipFile), destDir, options)
}

/** Raw (decompressed) bytes of a single entry, or `null` when it is absent. */
export function readZipEntryBuffer(buffer, wantedName) {
  for (const entry of readZipEntries(buffer)) {
    if (entry.name !== wantedName) continue
    if (buffer.readUInt32LE(entry.offset) !== LOCAL_SIGNATURE) throw new Error(`Corrupt local header for ${entry.name}`)
    const localNameLength = buffer.readUInt16LE(entry.offset + 26)
    const localExtraLength = buffer.readUInt16LE(entry.offset + 28)
    const dataStart = entry.offset + 30 + localNameLength + localExtraLength
    const compressed = buffer.subarray(dataStart, dataStart + entry.compressedSize)
    if (entry.method === 0) return Buffer.from(compressed)
    if (entry.method === 8) return inflateRawSync(compressed)
    throw new Error(`Unsupported zip method ${entry.method} for ${entry.name}`)
  }
  return null
}

/** Entry names of a zip buffer, in central-directory order. */
export function zipEntryNames(buffer) {
  return readZipEntries(buffer).map((entry) => entry.name)
}

/**
 * `node-v24.9.0-win-x64/` — the single top-level directory every entry shares, or `null`
 * when the archive is already flat (e.g. the CPython embeddable zip). Distribution
 * archives nest everything one level deep; the runtime layout must not.
 */
export function topLevelPrefix(buffer) {
  const names = readZipEntries(buffer)
    .map((entry) => entry.name.replace(/\\/g, '/'))
    .filter((name) => name !== '' && !name.endsWith('/'))
  if (names.length === 0) return null
  const first = names[0].split('/')[0]
  if (first === names[0]) return null
  return names.every((name) => name.startsWith(`${first}/`)) ? `${first}/` : null
}

/** Remap that drops the leading directory segment of a nested archive. */
export function stripPrefixMap(destDir, prefix) {
  const depth = prefix.split('/').filter(Boolean).length
  return (name) => path.join(destDir, ...name.split('/').slice(depth))
}

/**
 * Write a store/deflate zip. Used by tests (and by anything that needs to produce a
 * deterministic archive) — the runtime fetcher itself only reads zips.
 */
export function writeZipFile(zipFile, entries, options = {}) {
  const compress = options.compress ?? true
  const localParts = []
  const centralParts = []
  let offset = 0
  for (const entry of entries) {
    const name = Buffer.from(entry.name.replace(/\\/g, '/'), 'utf8')
    const raw = Buffer.isBuffer(entry.data) ? entry.data : Buffer.from(entry.data, 'utf8')
    const stored = compress ? deflateRawSync(raw) : raw
    const method = compress ? 8 : 0
    const crc = crc32(raw)
    const local = Buffer.alloc(30)
    local.writeUInt32LE(LOCAL_SIGNATURE, 0)
    local.writeUInt16LE(20, 4)
    local.writeUInt16LE(0, 6)
    local.writeUInt16LE(method, 8)
    local.writeUInt16LE(0, 10)
    local.writeUInt16LE(0, 12)
    local.writeUInt32LE(crc, 14)
    local.writeUInt32LE(stored.length, 18)
    local.writeUInt32LE(raw.length, 22)
    local.writeUInt16LE(name.length, 26)
    local.writeUInt16LE(0, 28)
    localParts.push(local, name, stored)
    const central = Buffer.alloc(46)
    central.writeUInt32LE(CENTRAL_SIGNATURE, 0)
    central.writeUInt16LE(20, 4)
    central.writeUInt16LE(20, 6)
    central.writeUInt16LE(0, 8)
    central.writeUInt16LE(method, 10)
    central.writeUInt16LE(0, 12)
    central.writeUInt16LE(0, 14)
    central.writeUInt32LE(crc, 16)
    central.writeUInt32LE(stored.length, 20)
    central.writeUInt32LE(raw.length, 24)
    central.writeUInt16LE(name.length, 28)
    central.writeUInt16LE(0, 30)
    central.writeUInt16LE(0, 32)
    central.writeUInt16LE(0, 34)
    central.writeUInt16LE(0, 36)
    // External attributes: the POSIX mode lives in the high 16 bits (as `zip` writes it).
    central.writeUInt32LE((((entry.mode ?? 0o100644) & 0xffff) << 16) >>> 0, 38)
    central.writeUInt32LE(offset, 42)
    centralParts.push(central, name)
    offset += local.length + name.length + stored.length
  }
  const centralSize = centralParts.reduce((total, part) => total + part.length, 0)
  const eocd = Buffer.alloc(22)
  eocd.writeUInt32LE(EOCD_SIGNATURE, 0)
  eocd.writeUInt16LE(0, 4)
  eocd.writeUInt16LE(0, 6)
  eocd.writeUInt16LE(entries.length, 8)
  eocd.writeUInt16LE(entries.length, 10)
  eocd.writeUInt32LE(centralSize, 12)
  eocd.writeUInt32LE(offset, 16)
  eocd.writeUInt16LE(0, 20)
  fs.mkdirSync(path.dirname(zipFile), { recursive: true })
  fs.writeFileSync(zipFile, Buffer.concat([...localParts, ...centralParts, eocd]))
  return zipFile
}
