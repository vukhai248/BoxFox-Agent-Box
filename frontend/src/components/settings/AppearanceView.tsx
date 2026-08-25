import { Sun, Moon, Laptop } from 'lucide-react'
import { useUiStore } from '../../store/uiStore'
import { CustomRadio } from './CustomRadio'

export function AppearanceView() {
  const theme = useUiStore((s) => s.theme)
  const setTheme = useUiStore((s) => s.setTheme)

  return (
    <div className="p-8 max-w-4xl mx-auto space-y-6 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>General</span>
        <span>›</span>
        <span className="text-fg font-semibold">Appearance</span>
      </div>

      {/* Header */}
      <div className="space-y-1 border-b border-line pb-4">
        <h1 className="text-xl font-bold text-fg">Appearance</h1>
        <p className="text-xs text-muted">
          Choose how BoxFox looks to you. Select a light or dark theme, or sync with your system.
        </p>
      </div>

      {/* Theme Cards Grid (Matching Screenshot 4) */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5 pt-2">
        {/* 1. Light Theme */}
        <div
          onClick={() => setTheme('light')}
          className={`group rounded-2xl border bg-panel p-3.5 space-y-3 transition cursor-pointer shadow-xs ${
            theme === 'light'
              ? 'border-brand ring-2 ring-brand/20'
              : 'border-line hover:border-brand/40'
          }`}
        >
          {/* Wireframe Preview Box */}
          <div className="h-32 w-full rounded-xl border border-zinc-200 bg-white p-3 shadow-inner flex gap-2 overflow-hidden">
            <div className="w-8 space-y-1.5 border-r border-zinc-200 pr-1.5">
              <div className="h-1.5 w-full rounded-full bg-zinc-300" />
              <div className="h-1.5 w-4/5 rounded-full bg-zinc-300" />
              <div className="h-1.5 w-3/5 rounded-full bg-zinc-300" />
            </div>
            <div className="flex-1 space-y-2">
              <div className="h-2 w-2/3 rounded-full bg-blue-600" />
              <div className="h-1.5 w-full rounded-full bg-zinc-200" />
              <div className="h-1.5 w-4/5 rounded-full bg-zinc-200" />
              <div className="h-1.5 w-full rounded-full bg-zinc-100" />
            </div>
          </div>

          <div className="flex items-center gap-2 px-1 text-xs font-semibold text-fg">
            <CustomRadio
              checked={theme === 'light'}
              onChange={() => setTheme('light')}
            />
            <Sun className="size-3.5 text-muted" />
            <span>Light</span>
          </div>
        </div>

        {/* 2. Dark Theme */}
        <div
          onClick={() => setTheme('dark')}
          className={`group rounded-2xl border bg-panel p-3.5 space-y-3 transition cursor-pointer shadow-xs ${
            theme === 'dark'
              ? 'border-brand ring-2 ring-brand/20'
              : 'border-line hover:border-brand/40'
          }`}
        >
          {/* Wireframe Preview Box */}
          <div className="h-32 w-full rounded-xl border border-zinc-800 bg-[#0d0f14] p-3 shadow-inner flex gap-2 overflow-hidden">
            <div className="w-8 space-y-1.5 border-r border-zinc-800 pr-1.5">
              <div className="h-1.5 w-full rounded-full bg-zinc-700" />
              <div className="h-1.5 w-4/5 rounded-full bg-zinc-700" />
              <div className="h-1.5 w-3/5 rounded-full bg-zinc-700" />
            </div>
            <div className="flex-1 space-y-2">
              <div className="h-2 w-2/3 rounded-full bg-blue-500" />
              <div className="h-1.5 w-full rounded-full bg-zinc-800" />
              <div className="h-1.5 w-4/5 rounded-full bg-zinc-800" />
            </div>
          </div>

          <div className="flex items-center gap-2 px-1 text-xs font-semibold text-fg">
            <CustomRadio
              checked={theme === 'dark'}
              onChange={() => setTheme('dark')}
            />
            <Moon className="size-3.5 text-muted" />
            <span>Dark</span>
          </div>
        </div>

        {/* 3. System Theme */}
        <div
          onClick={() => setTheme('system')}
          className={`group rounded-2xl border bg-panel p-3.5 space-y-3 transition cursor-pointer shadow-xs ${
            theme === 'system'
              ? 'border-brand ring-2 ring-brand/20'
              : 'border-line hover:border-brand/40'
          }`}
        >
          {/* Wireframe Preview Box (Split 50/50) */}
          <div className="h-32 w-full rounded-xl border border-zinc-300 dark:border-zinc-800 flex overflow-hidden shadow-inner">
            {/* Left light half */}
            <div className="w-1/2 bg-white p-2.5 space-y-2 border-r border-zinc-200">
              <div className="h-1.5 w-2/3 rounded-full bg-blue-600" />
              <div className="h-1.5 w-full rounded-full bg-zinc-200" />
              <div className="h-1.5 w-4/5 rounded-full bg-zinc-200" />
            </div>
            {/* Right dark half */}
            <div className="w-1/2 bg-[#0d0f14] p-2.5 space-y-2">
              <div className="h-1.5 w-2/3 rounded-full bg-blue-500" />
              <div className="h-1.5 w-full rounded-full bg-zinc-800" />
              <div className="h-1.5 w-4/5 rounded-full bg-zinc-800" />
            </div>
          </div>

          <div className="flex items-center gap-2 px-1 text-xs font-semibold text-fg">
            <CustomRadio
              checked={theme === 'system'}
              onChange={() => setTheme('system')}
            />
            <Laptop className="size-3.5 text-muted" />
            <span>System</span>
          </div>
        </div>
      </div>
    </div>
  )
}
