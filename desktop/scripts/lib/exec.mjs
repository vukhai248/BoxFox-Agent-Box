/**
 * Small command runner for the build scripts (fetch-runtime / build-app).
 * Never throws; always resolves with `{ code, stdout, stderr, timedOut }`.
 */

import { spawn } from 'node:child_process'

export function runCommand(command, args, options = {}) {
  const timeoutMs = options.timeoutMs ?? 120_000
  return new Promise((resolve) => {
    let stdout = ''
    let stderr = ''
    let timedOut = false
    let settled = false
    const child = spawn(command, args, { cwd: options.cwd, windowsHide: true, stdio: ['ignore', 'pipe', 'pipe'] })
    const timer = setTimeout(() => {
      timedOut = true
      child.kill('SIGKILL')
    }, timeoutMs)
    const feed = (chunk, stream) => {
      const text = chunk.toString('utf8')
      if (stream === 'stdout') stdout += text
      else stderr += text
      if (options.onLine) {
        for (const line of text.split(/\r?\n/)) {
          if (line.trim() !== '') options.onLine(line, stream)
        }
      }
    }
    child.stdout?.on('data', (chunk) => feed(chunk, 'stdout'))
    child.stderr?.on('data', (chunk) => feed(chunk, 'stderr'))
    const finish = (code) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve({ code, stdout, stderr, timedOut })
    }
    child.on('error', (error) => {
      stderr += `${error.message}\n`
      finish(null)
    })
    child.on('close', (code) => finish(code))
  })
}
