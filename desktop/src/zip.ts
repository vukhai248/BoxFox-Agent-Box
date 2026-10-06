/**
 * Minimal, dependency-free ZIP writer used by the diagnostics archive (D3).
 *
 * The build scripts have their own reader/writer (`scripts/lib/zip.mjs`), but that is an
 * ES module and the Electron main process is CommonJS, so it cannot be required from
 * here. This file is the write-only subset the app needs: store (0) or deflate (8)
 * entries, no ZIP64 (the archive holds text and small JSON only), no encryption.
 */

import { deflateRawSync } from 'node:zlib'
import * as fs from 'node:fs'
import * as path from 'node:path'

const EOCD_SIGNATURE = 0x06054b50
const CENTRAL_SIGNATURE = 0x02014b50
const LOCAL_SIGNATURE = 0x04034b50

export interface ZipEntryInput {
  /** Entry name, always written with forward slashes. */
  name: string
  data: Buffer | string
}

export interface ZipWriteOptions {
  /** Deflate entries (default true). Store-only makes the archive byte-stable. */
  compress?: boolean
  /** Timestamp stamped on every entry; defaults to now. */
  date?: Date
}

const CRC_TABLE = (() => {
  const table = new Int32Array(256)
  for (let index = 0; index < 256; index += 1) {
    let value = index
    for (let bit = 0; bit < 8; bit += 1) value = value & 1 ? 0xedb88320 ^ (value >>> 1) : value >>> 1
    table[index] = value
  }
  return table
})()

export function crc32(buffer: Buffer): number {
  let crc = -1
  for (let index = 0; index < buffer.length; index += 1) {
    crc = CRC_TABLE[(crc ^ buffer[index]) & 0xff] ^ (crc >>> 8)
  }
  return (crc ^ -1) >>> 0
}

/** DOS date/time pair (`(date << 16) | time`), as every zip entry header carries it. */
export function dosDateTime(date: Date): number {
  const year = Math.max(1980, date.getFullYear())
  const dosDate = ((year - 1980) << 9) | ((date.getMonth() + 1) << 5) | date.getDate()
  const dosTime = (date.getHours() << 11) | (date.getMinutes() << 5) | (date.getSeconds() >> 1)
  return ((dosDate & 0xffff) << 16) | (dosTime & 0xffff)
}

export function buildZip(entries: ZipEntryInput[], options: ZipWriteOptions = {}): Buffer {
  const compress = options.compress ?? true
  const stamp = dosDateTime(options.date ?? new Date())
  const localParts: Buffer[] = []
  const centralParts: Buffer[] = []
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
    local.writeUInt32LE(stamp, 10)
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
    central.writeUInt32LE(stamp, 12)
    central.writeUInt32LE(crc, 16)
    central.writeUInt32LE(stored.length, 20)
    central.writeUInt32LE(raw.length, 24)
    central.writeUInt16LE(name.length, 28)
    central.writeUInt16LE(0, 30)
    central.writeUInt16LE(0, 32)
    central.writeUInt16LE(0, 34)
    central.writeUInt16LE(0, 36)
    // POSIX mode in the high 16 bits, as `zip` writes it (regular file, 0644).
    central.writeUInt32LE(((0o100644 & 0xffff) << 16) >>> 0, 38)
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
  return Buffer.concat([...localParts, ...centralParts, eocd])
}

export function writeZipFile(file: string, entries: ZipEntryInput[], options: ZipWriteOptions = {}): string {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, buildZip(entries, options))
  return file
}
