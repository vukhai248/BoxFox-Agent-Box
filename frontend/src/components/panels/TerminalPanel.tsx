/**
 * Khung Terminal phong cách VS Code / Warp / Cursor.
 * Bổ sung: Tabs bash/agentbox, điều khiển clear/split, màu ANSI sắc nét, và CLI tương tác.
 */
import React, { useState, useRef, useEffect } from 'react'
import {
  Terminal as TerminalIcon,
  Trash2,
  RotateCcw,
  Plus,
  CheckCircle2,
} from 'lucide-react'
import { useAgentStore } from '../../store/agentStore'

interface TerminalTab {
  id: string
  name: string
  active: boolean
}

export function TerminalPanel() {
  const initialLines = useAgentStore((s) => s.terminal)
  const [tabs, setTabs] = useState<TerminalTab[]>([
    { id: '1', name: '1: bash (container)', active: true },
    { id: '2', name: '2: agentbox-daemon', active: false },
  ])
  const [activeTabId, setActiveTabId] = useState('1')
  const [customLines, setCustomLines] = useState<{ kind: 'prompt' | 'stdout' | 'stderr' | 'exit'; text: string }[]>([])
  const [inputVal, setInputVal] = useState('')
  const terminalEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  // Combined lines: initial store lines + custom typed lines
  const displayLines = [...initialLines, ...customLines]

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [displayLines.length])

  const handleCommandSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const cmd = inputVal.trim()
    if (!cmd) return

    const newOutputs: { kind: 'prompt' | 'stdout' | 'stderr' | 'exit'; text: string }[] = [
      { kind: 'prompt', text: `$ ${cmd}` },
    ]

    if (cmd === 'clear') {
      setCustomLines([])
      setInputVal('')
      return
    } else if (cmd === 'help') {
      newOutputs.push({
        kind: 'stdout',
        text: 'Available commands: ls, cat <file>, pytest, git status, agentbox status, whoami, uname -a, clear',
      })
    } else if (cmd === 'ls' || cmd === 'ls -la') {
      newOutputs.push({
        kind: 'stdout',
        text: 'drwxr-xr-x 4 root root  4096 Aug 24 22:30 src/\ndrwxr-xr-x 2 root root  4096 Aug 24 22:30 tests/\ndrwxr-xr-x 3 root root  4096 Aug 24 22:30 vendor/\n-rw-r--r-- 1 root root   142 Aug 24 22:30 .env\n-rw-r--r-- 1 root root   380 Aug 24 22:30 README.md\n-rw-r--r-- 1 root root   450 Aug 24 22:30 plan.md',
      })
    } else if (cmd.startsWith('cat ')) {
      const file = cmd.replace('cat ', '').trim()
      if (file === 'plan.md') {
        newOutputs.push({
          kind: 'stdout',
          text: '# Implementation Plan: Fix nested bracket parser in src/parser.py\n1. Read src/parser.py\n2. Inspect tests/test_parser.py\n3. Modify src/parser.py\n4. Add test cases in tests/test_parser.py\n5. Run pytest and report assertion results.',
        })
      } else if (file === '.env') {
        newOutputs.push({
          kind: 'stdout',
          text: 'DATABASE_URL=postgres://admin:secret_pass@localhost:5432/app\nSTRIPE_SECRET_KEY=sk_live_51H8xQ2eZvKYlo2C\nSESSION_SECRET=7f3a9c1e5b2d8046',
        })
      } else {
        newOutputs.push({ kind: 'stderr', text: `cat: ${file}: No such file or directory` })
      }
    } else if (cmd === 'pytest' || cmd.startsWith('pytest')) {
      newOutputs.push({
        kind: 'stdout',
        text: '============================= test session starts =============================\nplatform linux -- Python 3.11.8, pytest-8.1.1\ncollected 3 items\n\ntests/test_parser.py ...                                                 [100%]\n\n============================== 3 passed in 0.04s ===============================',
      })
      newOutputs.push({ kind: 'exit', text: '0' })
    } else if (cmd === 'git status') {
      newOutputs.push({
        kind: 'stdout',
        text: 'On branch fix/nested-brackets\nChanges to be committed:\n  modified:   src/parser.py\n  modified:   tests/test_parser.py\n\nUntracked files:\n  plan.md',
      })
    } else if (cmd === 'whoami') {
      newOutputs.push({ kind: 'stdout', text: 'sandbox-user (uid=1000, gid=1000)' })
    } else if (cmd === 'uname -a') {
      newOutputs.push({ kind: 'stdout', text: 'Linux agent-box-sbx-01 6.6.0-generic #1 SMP x86_64 GNU/Linux' })
    } else if (cmd === 'agentbox status') {
      newOutputs.push({
        kind: 'stdout',
        text: 'Agent Box Security Gateway v0.1.0\nMode: ACT | Epoch: #2 | Active Lease: LS-1 (SAFE_READ_WRITE)\nIntegrity Floor: UNTRUSTED | Confidentiality Ceiling: INTERNAL',
      })
    } else {
      newOutputs.push({ kind: 'stderr', text: `bash: ${cmd}: command not found. Type 'help' for available commands.` })
    }

    setCustomLines((prev) => [...prev, ...newOutputs])
    setInputVal('')
  }

  const handleClear = () => {
    setCustomLines([])
  }

  return (
    <div className="flex h-full flex-col bg-[#080808] text-zinc-200 select-text font-mono text-xs">
      {/* Top Terminal Bar */}
      <div className="flex items-center justify-between border-b border-[#202020] bg-[#0d0d0d] px-3 py-1.5 select-none">
        {/* Terminal Tabs */}
        <div className="flex items-center gap-1">
          {tabs.map((tab) => {
            const isActive = activeTabId === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTabId(tab.id)}
                className={`flex items-center gap-1.5 rounded px-2.5 py-1 text-[11px] font-medium transition cursor-pointer ${
                  isActive
                    ? 'bg-[#181818] text-zinc-100 shadow-xs border border-[#2a2a2a]'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-[#141414]'
                }`}
              >
                <TerminalIcon className="size-3 text-blue-400" />
                <span>{tab.name}</span>
              </button>
            )
          })}
          <button
            type="button"
            onClick={() => {
              const nextId = String(tabs.length + 1)
              setTabs([...tabs, { id: nextId, name: `${nextId}: sh`, active: false }])
              setActiveTabId(nextId)
            }}
            className="flex size-6 items-center justify-center rounded text-zinc-400 hover:bg-[#181818] hover:text-zinc-200 transition cursor-pointer"
            title="New Terminal Tab"
          >
            <Plus className="size-3" />
          </button>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-1 text-zinc-400">
          <button
            type="button"
            onClick={handleClear}
            className="flex size-6 items-center justify-center rounded hover:bg-[#181818] hover:text-zinc-100 transition cursor-pointer"
            title="Clear Terminal"
          >
            <Trash2 className="size-3" />
          </button>
          <button
            type="button"
            onClick={() => setCustomLines([])}
            className="flex size-6 items-center justify-center rounded hover:bg-[#181818] hover:text-zinc-100 transition cursor-pointer"
            title="Restart Session"
          >
            <RotateCcw className="size-3" />
          </button>
          <div className="h-3 w-px bg-[#262626] mx-1" />
          <span className="flex items-center gap-1 text-[10px] text-emerald-400 bg-emerald-500/10 border border-emerald-500/30 rounded px-1.5 py-0.2">
            <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
            Connected
          </span>
        </div>
      </div>

      {/* Terminal Output Body */}
      <div
        onClick={() => inputRef.current?.focus()}
        className="min-h-0 flex-1 overflow-y-auto p-4 space-y-1 leading-relaxed bg-[#080808]"
      >
        {displayLines.length === 0 ? (
          <div className="text-zinc-500 italic">
            Sandbox terminal initialized. Type <code className="text-blue-400">help</code> or <code className="text-blue-400">pytest</code> to test execution.
          </div>
        ) : (
          displayLines.map((line, index) => {
            if (line.kind === 'prompt') {
              return (
                <div key={index} className="flex items-start gap-2 pt-1.5">
                  <span className="text-emerald-400 font-semibold select-none">root@agentbox:~/workspace#</span>
                  <span className="text-zinc-100 font-medium">{line.text.replace(/^\$\s*/, '')}</span>
                </div>
              )
            } else if (line.kind === 'stderr') {
              return (
                <div key={index} className="text-rose-400 pl-4 whitespace-pre-wrap">
                  {line.text}
                </div>
              )
            } else if (line.kind === 'exit') {
              return (
                <div key={index} className="text-[10px] text-zinc-500 pl-4 flex items-center gap-1 select-none">
                  <CheckCircle2 className="size-3 text-emerald-400" />
                  <span>exit {line.text}</span>
                </div>
              )
            } else {
              return (
                <div key={index} className="text-zinc-300 pl-4 whitespace-pre-wrap">
                  {line.text}
                </div>
              )
            }
          })
        )}

        {/* Live Input Form at bottom of stream */}
        <form onSubmit={handleCommandSubmit} className="flex items-center gap-2 pt-1">
          <span className="text-emerald-400 font-semibold select-none shrink-0">root@agentbox:~/workspace#</span>
          <input
            ref={inputRef}
            type="text"
            value={inputVal}
            onChange={(e) => setInputVal(e.target.value)}
            className="flex-1 bg-transparent text-zinc-100 outline-hidden font-mono text-xs placeholder:text-zinc-600"
            placeholder="type command (e.g. pytest, ls, cat plan.md, clear)..."
            autoFocus
          />
        </form>
        <div ref={terminalEndRef} />
      </div>

      {/* Terminal Footer Bar */}
      <div className="flex items-center justify-between border-t border-[#1a1a1a] bg-[#0c0c0c] px-3 py-1 text-[10px] text-zinc-500 select-none">
        <div className="flex items-center gap-3">
          <span>bash 5.2.15</span>
          <span>UTF-8</span>
          <span>Linux x86_64</span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-zinc-400">Container: agent-box-sbx-01</span>
          <span className="text-emerald-400">Lease: LS-1 Active</span>
        </div>
      </div>
    </div>
  )
}
