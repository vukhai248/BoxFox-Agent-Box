/**
 * Where the app finds its bundled blocks (UI, router, harness, runtime).
 *
 * Packaged (NSIS install): electron-builder copies every `extraResources` entry into
 * `process.resourcesPath`, so the layout there is:
 *
 *   resources/ui/            built frontend
 *   resources/router/        router sources (node_modules-free by design)
 *   resources/harness/       scripts/run-harness.py + backend/src (+ AGENT.md)
 *   resources/runtime/       bundled Node + CPython + wheels
 *   resources/docker-context/  build context of the sandbox image (docker mode)
 *   resources/build-manifest.json
 *
 * In development the same layout is produced by `node scripts/build-app.mjs` under
 * `desktop/build/`; when that directory is absent we fall back to the checkout
 * layout so `npm run pack:linux` can still smoke-test the supervisor.
 */

import * as fs from 'node:fs'
import * as path from 'node:path'

export interface ResourcesInput {
  isPackaged: boolean
  resourcesPath: string
  /** Directory of the compiled app (`dist/`), used for the development fallback. */
  appDir: string
}

export function resolveResourcesDir(input: ResourcesInput): string {
  if (input.isPackaged) return input.resourcesPath
  const staged = path.join(input.appDir, '..', 'build')
  return fs.existsSync(staged) ? path.resolve(staged) : path.resolve(input.appDir, '..')
}

export function uiDir(resourcesDir: string): string {
  return path.join(resourcesDir, 'ui')
}

export function routerDir(resourcesDir: string): string {
  return path.join(resourcesDir, 'router')
}

export function harnessDir(resourcesDir: string): string {
  return path.join(resourcesDir, 'harness')
}

export function runtimeDir(resourcesDir: string): string {
  return path.join(resourcesDir, 'runtime')
}

export function dockerContextDir(resourcesDir: string): string {
  return path.join(resourcesDir, 'docker-context')
}

export function manifestPath(resourcesDir: string): string {
  return path.join(resourcesDir, 'build-manifest.json')
}

export function readBuildManifest(resourcesDir: string): Record<string, unknown> | null {
  try {
    return JSON.parse(fs.readFileSync(manifestPath(resourcesDir), 'utf8')) as Record<string, unknown>
  } catch {
    return null
  }
}
