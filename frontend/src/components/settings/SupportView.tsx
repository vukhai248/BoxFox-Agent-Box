/**
 * Khung Cài đặt Support & Help (SupportView).
 * Nằm trong menu Settings -> ADMINISTRATION -> Support & Docs.
 * Tích hợp đầy đủ các kênh hỗ trợ kỹ thuật, tài liệu API, Discord, và System Status.
 * 
 * HƯỚNG DẪN CẤU HÌNH:
 * - Thay đổi các đường dẫn URL tài liệu (`docs.boxfox.dev`), Discord invite, và email hỗ trợ tại các thẻ tương ứng.
 */
import { BookOpen, MessageSquare, LifeBuoy, CheckCircle2, ExternalLink } from 'lucide-react'

export function SupportView() {
  return (
    <div className="p-8 max-w-4xl space-y-6 select-text">
      <div className="space-y-1 border-b border-line pb-4">
        <h1 className="text-xl font-bold text-fg">Support & Resources</h1>
        <p className="text-xs text-muted">
          Need assistance with BoxFox? Explore technical guides, contact our team, or join community discussions.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Card 1: Documentation */}
        <div className="rounded-2xl border border-line bg-panel p-5 space-y-3 shadow-xs">
          <div className="flex size-9 items-center justify-center rounded-xl bg-blue-500/10 text-blue-400 border border-blue-500/20">
            <BookOpen className="size-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-fg">Documentation & Guides</h3>
            <p className="text-xs text-muted mt-0.5">
              Read comprehensive architecture specs, API reference, and agent harness tutorials.
            </p>
          </div>
          <a
            href="https://docs.boxfox.dev"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-brand hover:underline"
          >
            <span>View documentation</span>
            <ExternalLink className="size-3" />
          </a>
        </div>

        {/* Card 2: Discord Community */}
        <div className="rounded-2xl border border-line bg-panel p-5 space-y-3 shadow-xs">
          <div className="flex size-9 items-center justify-center rounded-xl bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
            <MessageSquare className="size-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-fg">Community Discord</h3>
            <p className="text-xs text-muted mt-0.5">
              Chat with core developers, share custom harnesses, and get quick answers.
            </p>
          </div>
          <a
            href="https://discord.gg/boxfox"
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-400 hover:underline"
          >
            <span>Join Discord server</span>
            <ExternalLink className="size-3" />
          </a>
        </div>

        {/* Card 3: Contact Support */}
        <div className="rounded-2xl border border-line bg-panel p-5 space-y-3 shadow-xs">
          <div className="flex size-9 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <LifeBuoy className="size-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-fg">Priority Support</h3>
            <p className="text-xs text-muted mt-0.5">
              Have an urgent issue or bug to report? Email our engineering team directly.
            </p>
          </div>
          <a
            href="mailto:support@boxfox.dev"
            className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-400 hover:underline"
          >
            <span>support@boxfox.dev</span>
            <ExternalLink className="size-3" />
          </a>
        </div>

        {/* Card 4: System Status */}
        <div className="rounded-2xl border border-line bg-panel p-5 space-y-3 shadow-xs">
          <div className="flex size-9 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            <CheckCircle2 className="size-4" />
          </div>
          <div>
            <h3 className="text-sm font-bold text-fg">System Operational</h3>
            <p className="text-xs text-muted mt-0.5">
              All cloud sandboxes, gateway routes, and inference clusters are running 100% healthy.
            </p>
          </div>
          <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-muted">
            <span className="size-2 rounded-full bg-emerald-500 animate-pulse" />
            <span>99.99% Uptime</span>
          </span>
        </div>
      </div>
    </div>
  )
}
