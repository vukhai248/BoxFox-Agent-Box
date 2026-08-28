/**
 * Trạng thái điện/mạng của box — DÙNG CHUNG mọi component (header, các panel).
 * Module-level cache ⇒ đóng/mở tab không mất trạng thái (fix "tắt tab là mất").
 */
import { useEffect, useState } from 'react'
import { resolveBoxApiKey, resolveBoxApiUrl } from '../lib/boxApi'

const API = resolveBoxApiUrl(import.meta.env)
const BOX_API_KEY = resolveBoxApiKey(import.meta.env)

export type OnOff = 'on' | 'off' | 'unknown'
export interface BoxState {
  power: OnOff
  network: OnOff
}

let cache: BoxState = { power: 'unknown', network: 'unknown' }
const listeners = new Set<(s: BoxState) => void>()

function apply(next: Partial<BoxState>) {
  cache = { ...cache, ...next }
  listeners.forEach((l) => l(cache))
}

async function refresh() {
  try {
    const r = await fetch(API + '/__box/status')
    const j = await r.json()
    apply({ power: j.power ?? 'unknown', network: j.network ?? 'unknown' })
  } catch {
    apply({ power: 'unknown', network: 'unknown' })
  }
}

export async function setBoxPower(v: 'on' | 'off') {
  apply({ power: v }) // optimistic
  try {
    const r = await fetch(API + '/__box/power', {
      method: 'POST',
      body: v,
      headers: { 'X-BoxFox-Api-Key': BOX_API_KEY },
    })
    const j = await r.json()
    apply({ power: j.power ?? v })
  } catch {
    /* giữ optimistic; poll sau sẽ chỉnh */
  }
}

export async function setBoxNetwork(v: 'on' | 'off') {
  apply({ network: v })
  try {
    const r = await fetch(API + '/__box/network', {
      method: 'POST',
      body: v,
      headers: { 'X-BoxFox-Api-Key': BOX_API_KEY },
    })
    const j = await r.json()
    apply({ network: j.network ?? v })
  } catch {
    /* idem */
  }
}

export function useBoxState(): BoxState & {
  togglePower: () => void
  toggleNetwork: () => void
} {
  const [s, setS] = useState(cache)
  useEffect(() => {
    listeners.add(setS)
    void refresh()
    const id = setInterval(refresh, 5000) // đồng bộ trạng thái thật định kỳ
    return () => {
      listeners.delete(setS)
      clearInterval(id)
    }
  }, [])
  return {
    ...s,
    togglePower: () => void setBoxPower(s.power === 'on' ? 'off' : 'on'),
    toggleNetwork: () => void setBoxNetwork(s.network === 'on' ? 'off' : 'on'),
  }
}
