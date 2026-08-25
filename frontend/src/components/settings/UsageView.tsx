import { useState } from 'react'
import {
  ChevronLeft,
  ChevronRight,
  Activity,
} from 'lucide-react'

export function UsageView() {
  const [timeRange, setTimeRange] = useState<'day' | 'week' | 'month' | 'custom'>('week')
  const [metricView, setMetricView] = useState<'overview' | 'cost' | 'tokens' | 'sessions'>('overview')

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>Administration</span>
        <span>›</span>
        <span className="text-fg font-semibold">Usage</span>
      </div>

      {/* Top Filter Bar */}
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line pb-4">
        {/* Time range selector + date navigator */}
        <div className="flex items-center gap-3">
          <div className="flex items-center rounded-lg border border-line bg-panel2 p-0.5 text-xs">
            {(['day', 'week', 'month', 'custom'] as const).map((range) => (
              <button
                key={range}
                type="button"
                onClick={() => setTimeRange(range)}
                className={`rounded-md px-3 py-1 font-medium capitalize transition cursor-pointer ${
                  timeRange === range
                    ? 'bg-panel text-fg font-semibold border border-line shadow-xs'
                    : 'text-muted hover:text-fg'
                }`}
              >
                {range}
              </button>
            ))}
          </div>

          <div className="flex items-center rounded-lg border border-line bg-panel2 px-2.5 py-1 text-xs text-fg gap-2">
            <button
              type="button"
              className="text-muted hover:text-fg transition cursor-pointer"
            >
              <ChevronLeft className="size-3.5" />
            </button>
            <span className="font-mono text-[11px] font-medium">Aug 24 - 30, 2026</span>
            <button
              type="button"
              className="text-muted hover:text-fg transition cursor-pointer"
            >
              <ChevronRight className="size-3.5" />
            </button>
          </div>
        </div>

        {/* Metric filter pills */}
        <div className="flex items-center rounded-lg border border-line bg-panel2 p-0.5 text-xs">
          {(['overview', 'cost', 'tokens', 'sessions'] as const).map((metric) => (
            <button
              key={metric}
              type="button"
              onClick={() => setMetricView(metric)}
              className={`rounded-md px-3 py-1 font-medium capitalize transition cursor-pointer ${
                metricView === metric
                  ? 'bg-panel text-fg font-semibold border border-line shadow-xs'
                  : 'text-muted hover:text-fg'
              }`}
            >
              {metric}
            </button>
          ))}
        </div>
      </div>

      {/* 1. My Usage Cards Grid */}
      <div className="space-y-3">
        <h2 className="text-sm font-bold text-fg">My Usage</h2>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          {/* Total tokens */}
          <div className="rounded-2xl border border-line bg-panel p-4 space-y-1 shadow-xs">
            <span className="text-[11px] font-semibold text-muted">Total tokens</span>
            <div className="text-xl font-bold font-mono text-fg">0</div>
            <p className="text-[10px] text-muted">Input + output tokens</p>
          </div>

          {/* Total cost */}
          <div className="rounded-2xl border border-line bg-panel p-4 space-y-1 shadow-xs">
            <span className="text-[11px] font-semibold text-muted">Total cost</span>
            <div className="text-xl font-bold font-mono text-fg">$0.00</div>
            <p className="text-[10px] text-muted">Includes LLM + machine cost</p>
          </div>

          {/* BYOK cost */}
          <div className="rounded-2xl border border-line bg-panel p-4 space-y-1 shadow-xs">
            <span className="text-[11px] font-semibold text-muted">BYOK cost</span>
            <div className="text-xl font-bold font-mono text-fg">$0.00</div>
            <p className="text-[10px] text-muted">Included in total cost</p>
          </div>

          {/* Machine cost */}
          <div className="rounded-2xl border border-line bg-panel p-4 space-y-1 shadow-xs">
            <span className="text-[11px] font-semibold text-muted">Machine cost</span>
            <div className="text-xl font-bold font-mono text-fg">$0.00</div>
            <p className="text-[10px] text-muted">Machine runtime cost</p>
          </div>

          {/* Sessions started */}
          <div className="rounded-2xl border border-line bg-panel p-4 space-y-1 shadow-xs">
            <span className="text-[11px] font-semibold text-muted">Sessions started</span>
            <div className="text-xl font-bold font-mono text-fg">0</div>
            <p className="text-[10px] text-muted">Selected period</p>
          </div>
        </div>
      </div>

      {/* 2. Usage Leaderboard */}
      <div className="space-y-3 pt-2">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-bold text-fg">Usage leaderboard</h2>
          <span className="text-xs text-muted font-mono">0 users · $0.00 total</span>
        </div>

        <div className="rounded-2xl border border-line bg-panel p-8 flex flex-col items-center justify-center text-center shadow-xs">
          <Activity className="size-8 text-muted mb-2 opacity-60" />
          <span className="text-xs font-semibold text-fg">No usage data recorded for this period</span>
          <p className="text-[11px] text-muted mt-0.5">
            Token usage, machine execution hours, and provider costs will appear here automatically.
          </p>
        </div>
      </div>

      {/* 3. Sessions Started Section */}
      <div className="space-y-2 pt-2">
        <h2 className="text-sm font-bold text-fg">Sessions Started</h2>
        <p className="text-xs text-muted">Daily session counts by user</p>

        <div className="rounded-2xl border border-line bg-panel p-8 flex flex-col items-center justify-center text-center shadow-xs">
          <Activity className="size-8 text-muted mb-2 opacity-60" />
          <span className="text-xs font-semibold text-fg">No sessions recorded in this period</span>
          <p className="text-[11px] text-muted mt-0.5">
            Active and completed agent sessions will be graphed here automatically.
          </p>
        </div>
      </div>
    </div>
  )
}
