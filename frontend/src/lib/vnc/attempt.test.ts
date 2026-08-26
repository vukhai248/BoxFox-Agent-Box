/**
 * Test vòng đời một lượt kết nối noVNC.
 *
 * Đây là chỗ dễ rò socket nhất, và cũng là chỗ test reducer không chạm tới
 * được. Dùng `RFB` giả + đồng hồ tay nên không cần trình duyệt, không cần
 * canvas, không cần socket thật.
 */
import { describe, expect, it } from 'vitest'
import { startVncAttempt, type RfbEventMap, type RfbLike } from './attempt'
import type { VncEvent } from './state'

/** Đồng hồ tay: `tick()` mới cho timer chạy, nên test kiểm được cả thứ tự. */
function manualTimer() {
  let nextId = 1
  const jobs = new Map<number, { fn: () => void; at: number }>()
  let now = 0
  return {
    timer: {
      set(fn: () => void, ms: number) {
        const id = nextId++
        jobs.set(id, { fn, at: now + ms })
        return id
      },
      clear(id: number) {
        jobs.delete(id)
      },
    },
    tick(ms: number) {
      now += ms
      for (const [id, job] of [...jobs.entries()]) {
        if (job.at <= now) {
          jobs.delete(id)
          job.fn()
        }
      }
    },
    pending() {
      return jobs.size
    },
  }
}

class FakeRfb implements RfbLike {
  static created = 0
  static live = 0

  viewOnly = false
  scaleViewport = false
  clipViewport = false
  resizeSession = false
  showDotCursor = false
  background = ''
  disconnectCalls = 0

  private handlers = new Map<string, Set<(event: unknown) => void>>()

  constructor() {
    FakeRfb.created += 1
    FakeRfb.live += 1
  }

  disconnect() {
    this.disconnectCalls += 1
    if (this.disconnectCalls === 1) FakeRfb.live -= 1
  }

  focus() {}
  blur() {}

  addEventListener<K extends keyof RfbEventMap>(
    type: K,
    listener: (event: RfbEventMap[K]) => void,
  ) {
    const set = this.handlers.get(type) ?? new Set()
    set.add(listener as (event: unknown) => void)
    this.handlers.set(type, set)
  }

  removeEventListener<K extends keyof RfbEventMap>(
    type: K,
    listener: (event: RfbEventMap[K]) => void,
  ) {
    this.handlers.get(type)?.delete(listener as (event: unknown) => void)
  }

  /** Số listener còn gắn — dùng để chứng minh `abort()` đã gỡ hết. */
  listenerCount() {
    let total = 0
    for (const set of this.handlers.values()) total += set.size
    return total
  }

  emit(type: keyof RfbEventMap, detail?: unknown) {
    for (const listener of [...(this.handlers.get(type) ?? [])]) listener({ detail })
  }
}

/** `Element` giả — controller chỉ truyền nó cho factory, không đọc gì. */
const target = {} as Element

interface Harness {
  events: VncEvent[]
  resolveImport: () => void
  rejectImport: () => void
  rfb: () => FakeRfb | null
  clock: ReturnType<typeof manualTimer>
  attempt: ReturnType<typeof startVncAttempt>
}

function harness(
  options: {
    getTarget?: () => Element | null
    /** Factory nổ TRƯỚC khi có instance ⇒ chưa có socket nào. */
    throwOnCreate?: boolean
    /** Setter nổ SAU khi instance đã dựng ⇒ socket đã mở, phải được đóng. */
    throwOnConfigure?: boolean
  } = {},
): Harness {
  const clock = manualTimer()
  const events: VncEvent[] = []
  let created: FakeRfb | null = null
  let resolveImport: (() => void) | undefined
  let rejectImport: (() => void) | undefined

  const gate = new Promise<void>((resolve, reject) => {
    resolveImport = resolve
    rejectImport = () => reject(new Error('chunk 404'))
  })

  const attempt = startVncAttempt({
    url: 'ws://localhost:6080/websockify',
    timeoutMs: 5000,
    timer: clock.timer,
    getTarget: options.getTarget ?? (() => target),
    loadRfb: async () => {
      await gate
      return () => {
        if (options.throwOnCreate) throw new Error('RFB nổ')
        created = new FakeRfb()
        return created
      }
    },
    configureRfb: (rfb) => {
      if (options.throwOnConfigure) throw new Error('setter nổ')
      rfb.scaleViewport = true
    },
    onEvent: (event) => events.push(event),
  })

  return {
    events,
    resolveImport: resolveImport!,
    rejectImport: rejectImport!,
    rfb: () => created,
    clock,
    attempt,
  }
}

/** Cho microtask của `loadRfb()` chạy xong. */
const flush = () => new Promise<void>((resolve) => setTimeout(resolve, 0))

describe('startVncAttempt', () => {
  it('nối xong → phát connected, xoá timer quá hạn', async () => {
    FakeRfb.created = 0
    FakeRfb.live = 0
    const h = harness()
    h.resolveImport()
    await flush()

    expect(FakeRfb.created).toBe(1)
    h.rfb()!.emit('connect')
    expect(h.events).toEqual([{ type: 'connected' }])
    expect(h.clock.pending()).toBe(0)
    // Cấu hình đã được áp lên instance mà controller đang sở hữu.
    expect(h.rfb()!.scaleViewport).toBe(true)

    // Quá hạn không được phát sau khi đã live.
    h.clock.tick(10_000)
    expect(h.events).toEqual([{ type: 'connected' }])
  })

  it('bỏ chờ TRƯỚC khi gói nạp xong → không tạo RFB nào', async () => {
    FakeRfb.created = 0
    const h = harness()
    h.attempt.abort()
    h.resolveImport()
    await flush()

    expect(FakeRfb.created).toBe(0)
    expect(h.events).toEqual([])
    expect(h.clock.pending()).toBe(0)
  })

  it('quá hạn TRƯỚC khi gói nạp xong → phát timeout một lần, rồi không tạo RFB', async () => {
    FakeRfb.created = 0
    const h = harness()
    h.clock.tick(5000)
    expect(h.events).toEqual([{ type: 'timeout' }])

    h.resolveImport()
    await flush()
    expect(FakeRfb.created).toBe(0)
    expect(h.events).toEqual([{ type: 'timeout' }])
  })

  it('quá hạn sau khi đã tạo RFB → đóng RFB và gỡ hết listener', async () => {
    const h = harness()
    h.resolveImport()
    await flush()
    const rfb = h.rfb()!
    expect(rfb.listenerCount()).toBeGreaterThan(0)

    h.clock.tick(5000)
    expect(h.events).toEqual([{ type: 'timeout' }])
    expect(rfb.disconnectCalls).toBe(1)
    expect(rfb.listenerCount()).toBe(0)
  })

  it('abort khi đang live → đóng kết nối và KHÔNG phát sự kiện nào', async () => {
    const h = harness()
    h.resolveImport()
    await flush()
    const rfb = h.rfb()!
    rfb.emit('connect')
    expect(h.events).toEqual([{ type: 'connected' }])

    h.attempt.abort()
    expect(rfb.disconnectCalls).toBe(1)
    expect(rfb.listenerCount()).toBe(0)
    // `disconnect()` của mình không được vọng lại thành `closed`.
    rfb.emit('disconnect', { clean: true })
    expect(h.events).toEqual([{ type: 'connected' }])
    expect(h.attempt.getRfb()).toBeNull()
  })

  it('sự kiện muộn của lượt đã bị abort không lọt vào reducer', async () => {
    const h = harness()
    h.resolveImport()
    await flush()
    const rfb = h.rfb()!
    h.attempt.abort()

    rfb.emit('connect')
    rfb.emit('disconnect', { clean: false })
    rfb.emit('securityfailure', { status: 1 })
    expect(h.events).toEqual([])
  })

  it('phía kia đóng kênh → phát đúng một closed, kể cả khi noVNC báo clean', async () => {
    const h = harness()
    h.resolveImport()
    await flush()
    const rfb = h.rfb()!
    rfb.emit('connect')
    rfb.emit('disconnect', { clean: true })
    rfb.emit('disconnect', { clean: true })

    expect(h.events).toEqual([{ type: 'connected' }, { type: 'closed' }])
  })

  it('phía kia đóng trước → KHÔNG gọi disconnect() lần nữa', async () => {
    // noVNC 1.7.0 đã ở trạng thái `disconnected` khi bắn event; gọi
    // `disconnect()` thêm chỉ để nó log "Bad transition to disconnecting state".
    const h = harness()
    h.resolveImport()
    await flush()
    const rfb = h.rfb()!
    rfb.emit('connect')
    rfb.emit('disconnect', { clean: true })

    expect(rfb.disconnectCalls).toBe(0)
    // Vẫn phải dọn sạch: listener gỡ hết, timer xoá, không còn giữ instance.
    expect(rfb.listenerCount()).toBe(0)
    expect(h.clock.pending()).toBe(0)
    expect(h.attempt.getRfb()).toBeNull()
  })

  it('cấu hình nổ SAU khi đã dựng RFB → đóng instance, không để socket mồ côi', async () => {
    // Ca nguy hiểm thật: `new RFB(...)` đã mở WebSocket rồi mới tới setter.
    FakeRfb.created = 0
    FakeRfb.live = 0
    const h = harness({ throwOnConfigure: true })
    h.resolveImport()
    await flush()

    expect(FakeRfb.created).toBe(1)
    expect(h.events).toEqual([{ type: 'failed', reason: 'error' }])
    expect(h.rfb()!.disconnectCalls).toBe(1)
    expect(FakeRfb.live).toBe(0)
    expect(h.rfb()!.listenerCount()).toBe(0)
    expect(h.clock.pending()).toBe(0)
    expect(h.attempt.getRfb()).toBeNull()
  })

  it('securityfailure / credentialsrequired → failed với lý do tương ứng', async () => {
    const a = harness()
    a.resolveImport()
    await flush()
    a.rfb()!.emit('securityfailure', { status: 1 })
    expect(a.events).toEqual([{ type: 'failed', reason: 'security' }])

    const b = harness()
    b.resolveImport()
    await flush()
    b.rfb()!.emit('credentialsrequired', { types: ['password'] })
    expect(b.events).toEqual([{ type: 'failed', reason: 'credentials' }])
  })

  it('gói noVNC lỗi → failed/error, không làm vỡ panel', async () => {
    const h = harness()
    h.rejectImport()
    await flush()
    expect(h.events).toEqual([{ type: 'failed', reason: 'error' }])
  })

  it('mất phần tử DOM đích → failed/error, không tạo RFB', async () => {
    FakeRfb.created = 0
    const h = harness({ getTarget: () => null })
    h.resolveImport()
    await flush()
    expect(FakeRfb.created).toBe(0)
    expect(h.events).toEqual([{ type: 'failed', reason: 'error' }])
  })

  it('constructor RFB nổ → failed/error, timer được xoá', async () => {
    const h = harness({ throwOnCreate: true })
    h.resolveImport()
    await flush()
    expect(h.events).toEqual([{ type: 'failed', reason: 'error' }])
    expect(h.clock.pending()).toBe(0)
  })

  it('abort nhiều lần chỉ đóng một lần', async () => {
    const h = harness()
    h.resolveImport()
    await flush()
    const rfb = h.rfb()!
    h.attempt.abort()
    h.attempt.abort()
    h.attempt.abort()
    expect(rfb.disconnectCalls).toBe(1)
  })

  it('nhiều lượt liên tiếp: bấm "thử lại" nhiều lần vẫn chỉ còn đúng một RFB sống', async () => {
    FakeRfb.created = 0
    FakeRfb.live = 0

    let current = harness()
    current.resolveImport()
    await flush()
    current.rfb()!.emit('connect')

    for (let i = 0; i < 3; i++) {
      current.attempt.abort() // mô phỏng hook dập lượt cũ trước khi mở lượt mới
      current = harness()
      current.resolveImport()
      await flush()
      current.rfb()!.emit('connect')
      expect(FakeRfb.live).toBe(1)
    }

    expect(FakeRfb.created).toBe(4)
    current.attempt.abort()
    expect(FakeRfb.live).toBe(0)
  })

  it('getRfb() chỉ trả instance khi đã live', async () => {
    const h = harness()
    expect(h.attempt.getRfb()).toBeNull()
    h.resolveImport()
    await flush()
    expect(h.attempt.getRfb()).toBeNull()
    h.rfb()!.emit('connect')
    expect(h.attempt.getRfb()).toBe(h.rfb())
  })
})
