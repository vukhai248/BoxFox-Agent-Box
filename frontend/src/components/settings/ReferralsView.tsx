import { useState } from 'react'
import { Gift, Copy, Check, Users, Sparkles } from 'lucide-react'

export function ReferralsView() {
  const [copied, setCopied] = useState(false)
  const referralLink = 'https://boxfox.com/join?ref=khai_vu_7782'

  const handleCopy = () => {
    navigator.clipboard.writeText(referralLink)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>Administration</span>
        <span>›</span>
        <span className="text-fg font-semibold">Referrals</span>
      </div>

      {/* Header */}
      <div className="space-y-1 border-b border-line pb-4">
        <h1 className="text-xl font-bold text-fg">Referrals & Credits</h1>
        <p className="text-xs text-muted">
          Invite teammates and friends to earn complimentary agent compute credits.
        </p>
      </div>

      {/* Referral Link Card */}
      <div className="rounded-2xl border border-line bg-panel p-6 space-y-4 shadow-xs">
        <div className="flex items-center gap-3">
          <div className="flex size-10 items-center justify-center rounded-xl bg-purple-500/15 text-purple-400 border border-purple-500/30">
            <Gift className="size-5" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-fg">Your Personal Referral Link</h3>
            <p className="text-xs text-muted">Give $50 in credits to each person you invite, and get $50 when they run their first agent session.</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <input
            type="text"
            readOnly
            value={referralLink}
            className="flex-1 rounded-lg border border-line bg-panel2 px-3.5 py-2 text-xs font-mono text-fg outline-hidden"
          />
          <button
            type="button"
            onClick={handleCopy}
            className="flex items-center gap-1.5 rounded-lg bg-brand px-4 py-2 text-xs font-semibold text-brandfg shadow-md hover:opacity-90 transition cursor-pointer"
          >
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            <span>{copied ? 'Copied' : 'Copy Link'}</span>
          </button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="rounded-2xl border border-line bg-panel p-5 flex items-center gap-4 shadow-xs">
          <div className="flex size-10 items-center justify-center rounded-xl bg-brand/15 text-brand border border-brand/30">
            <Users className="size-5" />
          </div>
          <div>
            <span className="text-xs text-muted font-medium">Referred Engineers</span>
            <div className="text-xl font-bold font-mono text-fg">0</div>
          </div>
        </div>

        <div className="rounded-2xl border border-line bg-panel p-5 flex items-center gap-4 shadow-xs">
          <div className="flex size-10 items-center justify-center rounded-xl bg-emerald-500/15 text-emerald-500 border border-emerald-500/30">
            <Sparkles className="size-5" />
          </div>
          <div>
            <span className="text-xs text-muted font-medium">Credits Earned</span>
            <div className="text-xl font-bold font-mono text-emerald-500">$0.00</div>
          </div>
        </div>
      </div>
    </div>
  )
}
