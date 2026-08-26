import { describe, expect, it } from 'vitest'
import {
  DEFAULT_SANDBOX_VNC_URL,
  describeVncContextProblem,
  resolveScreenSource,
  resolveVncUrl,
} from './config'

describe('resolveVncUrl', () => {
  it('dùng mặc định khi không đặt biến môi trường', () => {
    expect(resolveVncUrl(undefined)).toBe(DEFAULT_SANDBOX_VNC_URL)
    expect(resolveVncUrl({})).toBe(DEFAULT_SANDBOX_VNC_URL)
  })

  it('dùng mặc định khi giá trị chỉ có khoảng trắng', () => {
    expect(resolveVncUrl({ VITE_SANDBOX_VNC_URL: '   ' })).toBe(DEFAULT_SANDBOX_VNC_URL)
  })

  it('tôn trọng giá trị người dùng đặt và cắt khoảng trắng', () => {
    expect(resolveVncUrl({ VITE_SANDBOX_VNC_URL: ' ws://10.0.0.5:6080/websockify ' })).toBe(
      'ws://10.0.0.5:6080/websockify',
    )
  })
})

describe('resolveScreenSource', () => {
  it('mặc định là mô phỏng — không đặt gì thì demo VPI không bị màn hình thật chiếm chỗ', () => {
    expect(resolveScreenSource(undefined)).toBe('mock')
    expect(resolveScreenSource({})).toBe('mock')
    expect(resolveScreenSource({ VITE_TRANSPORT: 'mock' })).toBe('mock')
  })

  it('bật màn hình thật khi được yêu cầu tường minh', () => {
    expect(resolveScreenSource({ VITE_SANDBOX_SCREEN_SOURCE: 'novnc' })).toBe('novnc')
    expect(resolveScreenSource({ VITE_SANDBOX_SCREEN_SOURCE: ' NOVNC ' })).toBe('novnc')
  })

  it('transport thật ⇒ ngầm hiểu là muốn xem máy thật', () => {
    expect(resolveScreenSource({ VITE_TRANSPORT: 'live' })).toBe('novnc')
  })

  it('yêu cầu mô phỏng tường minh thắng cả transport thật', () => {
    expect(
      resolveScreenSource({ VITE_SANDBOX_SCREEN_SOURCE: 'mock', VITE_TRANSPORT: 'live' }),
    ).toBe('mock')
  })

  it('giá trị lạ ⇒ về mô phỏng, không đoán', () => {
    expect(resolveScreenSource({ VITE_SANDBOX_SCREEN_SOURCE: 'webrtc' })).toBe('mock')
  })
})

describe('describeVncContextProblem', () => {
  const secureLocalhost = { pageProtocol: 'http:', isSecureContext: true }

  it('localhost qua http là hợp lệ', () => {
    expect(
      describeVncContextProblem({ ...secureLocalhost, url: 'ws://localhost:6080/websockify' }),
    ).toBeNull()
  })

  it('trang HTTPS + ws:// là mixed content', () => {
    expect(
      describeVncContextProblem({
        pageProtocol: 'https:',
        isSecureContext: true,
        url: 'ws://localhost:6080/websockify',
      }),
    ).toBe('mixedContent')
  })

  it('trang HTTPS + wss:// thì không sao', () => {
    expect(
      describeVncContextProblem({
        pageProtocol: 'https:',
        isSecureContext: true,
        url: 'wss://localhost:6080/websockify',
      }),
    ).toBeNull()
  })

  it('mở qua IP LAN (ngữ cảnh không an toàn) là lý do riêng, không phải mixed content', () => {
    expect(
      describeVncContextProblem({
        pageProtocol: 'http:',
        isSecureContext: false,
        url: 'ws://10.0.0.5:6080/websockify',
      }),
    ).toBe('insecureContext')
  })

  it('mixed content được báo trước vì cách sửa khác nhau', () => {
    expect(
      describeVncContextProblem({
        pageProtocol: 'https:',
        isSecureContext: false,
        url: 'ws://localhost:6080/websockify',
      }),
    ).toBe('mixedContent')
  })
})
