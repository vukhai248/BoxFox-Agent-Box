import test from 'node:test'
import assert from 'node:assert/strict'
import { DesktopCleanup } from '../dist/lifecycle.js'

test('quit cleans up services before releasing the instance record, once only', async () => {
  const cleanup = new DesktopCleanup()
  const calls = []
  cleanup.add(() => calls.push('lock'))
  cleanup.add(async () => { await Promise.resolve(); calls.push('services') })
  cleanup.add(() => calls.push('gateway'))
  await Promise.all([cleanup.run(assert.fail), cleanup.run(assert.fail)])
  assert.deepEqual(calls, ['gateway', 'services', 'lock'])
})

test('startup failure still runs all registered cleanup despite a cleanup error', async () => {
  const cleanup = new DesktopCleanup()
  const calls = []
  cleanup.add(() => calls.push('lock'))
  cleanup.add(() => { throw new Error('gateway failed') })
  await cleanup.run((error) => calls.push(error.message))
  assert.deepEqual(calls, ['gateway failed', 'lock'])
})
