/**
 * mode.ts — host/docker decision, the docker probe and the per-profile compose override.
 * Plan §6 PR-2 / D2: "host|docker; kiểm Docker sống + image có sẵn; (alpha) build image một
 * lần từ build context đi kèm, có tiến độ/lỗi/retry".
 */

import test from 'node:test'
import assert from 'node:assert/strict'
import * as fs from 'node:fs'
import * as os from 'node:os'
import * as path from 'node:path'

import {
  SANDBOX_IMAGE,
  composeOverrideYaml,
  decideMode,
  ensureSandboxImage,
  probeDocker,
  selectStartupMode,
  runCommand,
  startBoxContainer,
  stopBoxContainer,
  writeComposeOverride,
} from '../dist/mode.js'

test('host startup does not run a single Docker command', async () => {
  const result = await selectStartupMode('host', { runner: () => assert.fail('host probed Docker') })
  assert.equal(result.probe, null)
  assert.equal(result.decision.mode, 'host')
})

function tempDir(t, prefix = 'boxfox-mode-') {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), prefix))
  t.after(() => fs.rmSync(dir, { recursive: true, force: true }))
  return dir
}

const PORTS = { gateway: 44001, router: 44002, harness: 44003, box: 44004 }

function runner(responses) {
  const calls = []
  const impl = async (command, args) => {
    calls.push([command, ...args].join(' '))
    const match = responses.find(([pattern]) => args.join(' ').includes(pattern))
    return match ? match[1] : { code: 1, stdout: '', stderr: `unexpected: ${args.join(' ')}`, timedOut: false }
  }
  impl.calls = calls
  return impl
}

test('runCommand never throws and reports a missing binary as a failed run', async () => {
  const ok = await runCommand(process.execPath, ['-e', 'console.log("hi")'])
  assert.equal(ok.code, 0)
  assert.equal(ok.stdout.trim(), 'hi')

  const lines = []
  await runCommand(process.execPath, ['-e', 'console.error("boom"); process.exit(3)'], { onLine: (line) => lines.push(line) })
  assert.ok(lines.includes('boom'))

  const missing = await runCommand('boxfox-does-not-exist-xyz', [])
  assert.notEqual(missing.code, 0)
  assert.ok(missing.stderr.length > 0)
  assert.equal(missing.timedOut, false)

  const slow = await runCommand(process.execPath, ['-e', 'setTimeout(() => {}, 5000)'], { timeoutMs: 300 })
  assert.equal(slow.timedOut, true)
  assert.notEqual(slow.code, 0)
})

test('probeDocker distinguishes cli, engine and image failures', async () => {
  const none = await probeDocker({ runner: runner([]) })
  assert.equal(none.cli, false)
  assert.equal(none.engine, false)
  assert.equal(none.image, false)
  assert.match(none.detail, /Docker CLI not found/)

  const noEngine = await probeDocker({
    runner: runner([['--version', { code: 0, stdout: 'Docker version 27.0.0\n', stderr: '', timedOut: false }]]),
  })
  assert.equal(noEngine.cli, true)
  assert.equal(noEngine.engine, false)
  assert.match(noEngine.detail, /engine|daemon|running/i)

  const noImage = await probeDocker({
    runner: runner([
      ['--version', { code: 0, stdout: 'Docker version 27.0.0\n', stderr: '', timedOut: false }],
      ['info', { code: 0, stdout: '27.0.0\n', stderr: '', timedOut: false }],
    ]),
  })
  assert.equal(noImage.engine, true)
  assert.equal(noImage.image, false)
  assert.equal(noImage.imageName, SANDBOX_IMAGE)

  const ready = await probeDocker({
    runner: runner([
      ['--version', { code: 0, stdout: 'Docker version 27.0.0\n', stderr: '', timedOut: false }],
      ['info', { code: 0, stdout: '27.0.0\n', stderr: '', timedOut: false }],
      ['image', { code: 0, stdout: 'sha256:abc\n', stderr: '', timedOut: false }],
    ]),
  })
  assert.deepEqual(ready, {
    cli: true,
    engine: true,
    engineVersion: '27.0.0',
    image: true,
    imageName: SANDBOX_IMAGE,
    detail: `Docker 27.0.0 ready, ${SANDBOX_IMAGE} present.`,
  })
})

test('decideMode always explains a fallback instead of switching silently', async () => {
  assert.deepEqual(decideMode('host', await probeDocker({ runner: runner([]) })), { mode: 'host', reason: 'host mode selected.' })

  const unavailable = await probeDocker({ runner: runner([]) })
  const decision = decideMode('docker', unavailable)
  assert.equal(decision.mode, 'host')
  assert.ok(decision.reason.length > 0)
  assert.match(decision.reason, /host/i)

  const ready = { cli: true, engine: true, engineVersion: '27.0.0', image: true, imageName: SANDBOX_IMAGE, detail: 'Docker 27.0.0 ready.' }
  assert.deepEqual(decideMode('docker', ready), { mode: 'docker', reason: ready.detail })
})

test('ensureSandboxImage retries and surfaces the build log on failure', async (t) => {
  const context = tempDir(t)
  fs.writeFileSync(path.join(context, 'Dockerfile'), 'FROM scratch\n')

  let attempts = 0
  const flaky = runner([])
  const built = await ensureSandboxImage({
    contextDir: context,
    retries: 2,
    runner: async (command, args, options) => {
      attempts += 1
      return attempts < 2
        ? { code: 1, stdout: '', stderr: 'transient', timedOut: false }
        : { code: 0, stdout: '', stderr: '', timedOut: false }
    },
  })
  assert.equal(built.built, true)
  assert.equal(built.attempts, 2)
  assert.equal(attempts, 2)

  const progress = []
  await assert.rejects(
    () => ensureSandboxImage({ contextDir: context, retries: 0, runner: flaky, onProgress: (line) => progress.push(line) }),
    /Could not build agentbox-sandbox:latest after 1 attempt/,
  )
  assert.ok(progress.some((line) => line.includes('building')))
  assert.ok(flaky.calls.some((call) => call.includes('build --tag')))

  await assert.rejects(() => ensureSandboxImage({ contextDir: path.join(context, 'missing'), retries: 0 }), /build context is missing/)
})

test('the compose override isolates container, volume, ports and secret per profile', (t) => {
  const yaml = composeOverrideYaml({ profileKey: 'a1b2c3d4e5f6', ports: PORTS, adminToken: 'f'.repeat(64), skillsDir: 'C:\\BoxFox\\skills' })
  assert.match(yaml, /container_name: boxfox-desktop-a1b2c3d4e5f6/)
  assert.match(yaml, /boxfox-desktop-a1b2c3d4e5f6-workspace:\/home\/agent\/workspace/)
  assert.match(yaml, /name: boxfox-desktop-a1b2c3d4e5f6-workspace/)
  assert.match(yaml, new RegExp(`"127\\.0\\.0\\.1:${PORTS.box}:8081"`))
  assert.match(yaml, /BOXFOX_API_KEY: "f{64}"/)
  assert.match(yaml, new RegExp(`BOXFOX_UI_ORIGINS: "http://127\\.0\\.0\\.1:${PORTS.gateway},http://localhost:${PORTS.gateway}"`))
  assert.match(yaml, /skills:\/opt\/boxfox-skills:ro/)
  assert.ok(!yaml.includes('3100'), 'the development ports must not leak into the override')

  const input = { profileKey: 'a1b2c3d4e5f6', ports: PORTS, adminToken: 'f'.repeat(64), skillsDir: '/skills' }
  const file = writeComposeOverride(tempDir(t), input)
  assert.equal(path.basename(file), 'docker-compose.override.yml')
  assert.equal(fs.readFileSync(file, 'utf8'), composeOverrideYaml(input))
})

test('start/stop compose the container with the bundled compose file plus the override', async () => {
  const calls = []
  const capture = async (command, args) => {
    calls.push([command, ...args].join(' '))
    return { code: 0, stdout: '', stderr: '', timedOut: false }
  }
  const options = { composeFile: '/resources/docker-context/docker-compose.yml', overrideFile: '/profile/docker-compose.override.yml', runner: capture }
  const up = await startBoxContainer(options)
  assert.equal(up.code, 0)
  assert.equal(calls[0], 'docker compose -f /resources/docker-context/docker-compose.yml -f /profile/docker-compose.override.yml up -d')
  await stopBoxContainer(options)
  assert.equal(calls[1], 'docker compose -f /resources/docker-context/docker-compose.yml -f /profile/docker-compose.override.yml down')
})
