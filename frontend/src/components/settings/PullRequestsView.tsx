import { useState } from 'react'
import { CheckCircle2, XCircle, Plus } from 'lucide-react'
import { CustomSelect } from './CustomSelect'
import { CustomRadio } from './CustomRadio'

const MACHINE_SIZE_OPTIONS = [
  { value: 'Default Machine Size', label: 'Default Machine Size' },
  { value: '2x CPU / 8GB RAM', label: '2x CPU / 8GB RAM' },
  { value: '4x CPU / 16GB RAM', label: '4x CPU / 16GB RAM' },
  { value: '8x CPU / 32GB RAM (High Performance)', label: '8x CPU / 32GB RAM' },
]

export function PullRequestsView() {
  const [activeSubTab, setActiveSubTab] = useState<'team' | 'my'>('team')

  // ==========================================
  // 1. My Settings State
  // ==========================================
  const [myAutoArchive, setMyAutoArchive] = useState(false)
  const [myPrAuthor, setMyPrAuthor] = useState<'boxfox' | 'me'>('me')
  const [myCreationMode, setMyCreationMode] = useState<'automatic' | 'manual'>('automatic')
  const [myPrType, setMyPrType] = useState<'open' | 'draft'>('open')
  const [githubConnected, setGithubConnected] = useState(true)
  const [githubAccount, setGithubAccount] = useState('@khaivu-dev')

  // ==========================================
  // 2. Team Settings State
  // ==========================================
  // Section: Pull Requests
  const [teamAutoArchive, setTeamAutoArchive] = useState(false)
  const [teamPrAuthor, setTeamPrAuthor] = useState<'boxfox' | 'me'>('me')
  const [teamCreationMode, setTeamCreationMode] = useState<'automatic' | 'manual'>('automatic')
  const [teamPrType, setTeamPrType] = useState<'open' | 'draft'>('open')
  const [branchPrefix, setBranchPrefix] = useState('boxfox/')

  // Section: Auto Review
  const [enableAutoReview, setEnableAutoReview] = useState(false)
  const [machineSize, setMachineSize] = useState('Default Machine Size')
  const [reviewNewCommits, setReviewNewCommits] = useState(false)
  const [useRiskAssessment, setUseRiskAssessment] = useState(false)
  const [enableTestingInReviews, setEnableTestingInReviews] = useState(false)
  const [dailyReviewLimit, setDailyReviewLimit] = useState(10)

  // Section: Merge Queue
  const [enableAutomerge, setEnableAutomerge] = useState(false)

  const handleConnectGithub = () => {
    setGithubConnected(true)
    setGithubAccount('@khaivu-dev')
  }

  const handleDisconnectGithub = () => {
    setGithubConnected(false)
  }

  return (
    <div className="p-8 max-w-5xl mx-auto space-y-6 select-text">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-xs text-muted">
        <span>Settings</span>
        <span>›</span>
        <span>Features</span>
        <span>›</span>
        <span className="text-fg font-semibold">Pull Requests</span>
      </div>

      {/* Sub Tabs: Team Settings vs My Settings */}
      <div className="flex items-center gap-6 border-b border-line text-xs font-semibold">
        <button
          type="button"
          onClick={() => setActiveSubTab('team')}
          className={`pb-3 transition cursor-pointer ${
            activeSubTab === 'team'
              ? 'border-b-2 border-brand text-fg font-bold'
              : 'text-muted hover:text-fg'
          }`}
        >
          Team Settings
        </button>
        <button
          type="button"
          onClick={() => setActiveSubTab('my')}
          className={`pb-3 transition cursor-pointer ${
            activeSubTab === 'my'
              ? 'border-b-2 border-brand text-fg font-bold'
              : 'text-muted hover:text-fg'
          }`}
        >
          My Settings
        </button>
      </div>

      {/* ========================================================================= */}
      {/* 1. TEAM SETTINGS */}
      {/* ========================================================================= */}
      {activeSubTab === 'team' ? (
        <div className="space-y-6">
          {/* A. PULL REQUESTS CONTAINER */}
          <div className="space-y-3">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted">
              PULL REQUESTS
            </span>

            <div className="rounded-2xl border border-line bg-panel divide-y divide-line/80 shadow-xs">
              {/* Auto-archive session on PR merge */}
              <div className="flex items-center justify-between p-5">
                <div className="space-y-0.5 max-w-xl">
                  <h3 className="text-xs font-semibold text-fg">
                    Auto-archive session on PR merge
                  </h3>
                  <p className="text-xs text-muted">
                    Automatically archive a session when all its associated pull requests are merged.
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => setTeamAutoArchive(!teamAutoArchive)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors duration-200 ease-in-out focus:outline-hidden ${
                    teamAutoArchive ? 'bg-brand border-brand' : 'bg-panel2 border-line'
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block size-3.5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out m-0.5 ${
                      teamAutoArchive ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>

              {/* PR author */}
              <div className="p-5 space-y-3">
                <h3 className="text-xs font-semibold text-fg">PR author</h3>
                <p className="text-xs text-muted">
                  Choose who appears as the author on pull requests
                </p>

                <div className="space-y-2 pt-1">
                  <CustomRadio
                    checked={teamPrAuthor === 'boxfox'}
                    onChange={() => setTeamPrAuthor('boxfox')}
                    label="BoxFox"
                    description="PRs are authored by the BoxFox bot account."
                  />
                  <CustomRadio
                    checked={teamPrAuthor === 'me'}
                    onChange={() => setTeamPrAuthor('me')}
                    label="Me"
                    description="PRs are authored using your personal GitHub account."
                  />
                </div>
              </div>

              {/* PR creation mode */}
              <div className="p-5 space-y-3">
                <h3 className="text-xs font-semibold text-fg">PR creation mode</h3>
                <p className="text-xs text-muted">
                  Choose how pull requests are created for your sessions
                </p>

                <div className="space-y-2 pt-1">
                  <CustomRadio
                    checked={teamCreationMode === 'automatic'}
                    onChange={() => setTeamCreationMode('automatic')}
                    label="Automatic"
                    description="BoxFox creates PRs automatically when your code is ready."
                  />
                  <CustomRadio
                    checked={teamCreationMode === 'manual'}
                    onChange={() => setTeamCreationMode('manual')}
                    label="Manual"
                    description="Review your changes in the Code Diff panel and click 'Create PR' when you're ready."
                  />
                </div>
              </div>

              {/* PR type */}
              <div className="p-5 space-y-3">
                <h3 className="text-xs font-semibold text-fg">PR type</h3>
                <p className="text-xs text-muted">
                  Choose what type of pull request BoxFox creates
                </p>

                <div className="space-y-2 pt-1">
                  <CustomRadio
                    checked={teamPrType === 'open'}
                    onChange={() => setTeamPrType('open')}
                    label="Open PR"
                    description="Creates a standard open pull request, ready for review."
                  />
                  <CustomRadio
                    checked={teamPrType === 'draft'}
                    onChange={() => setTeamPrType('draft')}
                    label="Draft PR"
                    description="Creates a draft pull request so you can review before marking as ready."
                  />
                </div>
              </div>

              {/* Branch prefix */}
              <div className="flex items-center justify-between p-5">
                <div className="space-y-0.5 max-w-lg">
                  <h3 className="text-xs font-semibold text-fg">Branch prefix</h3>
                  <p className="text-xs text-muted">
                    Prefix used when creating branches for pull requests (e.g., "boxfox", "boxfox/", "auto/", "bot/").
                  </p>
                </div>

                <div className="w-52">
                  <input
                    type="text"
                    value={branchPrefix}
                    onChange={(e) => setBranchPrefix(e.target.value)}
                    placeholder="boxfox/"
                    className="w-full rounded-lg border border-line bg-panel2 px-3 py-1.5 text-xs text-fg placeholder:text-muted outline-hidden focus:border-brand font-mono"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* B. AUTO REVIEW CONTAINER */}
          <div className="space-y-3">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted">
              AUTO REVIEW
            </span>

            <div className="rounded-2xl border border-line bg-panel divide-y divide-line/80 shadow-xs">
              {/* Enable auto PR review */}
              <div className="flex items-center justify-between p-5">
                <div className="space-y-0.5 max-w-xl">
                  <h3 className="text-xs font-semibold text-fg">
                    Enable auto PR review
                  </h3>
                  <p className="text-xs text-muted">
                    Automatically review pull requests opened by non-bot users
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => setEnableAutoReview(!enableAutoReview)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors duration-200 ease-in-out focus:outline-hidden ${
                    enableAutoReview ? 'bg-brand border-brand' : 'bg-panel2 border-line'
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block size-3.5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out m-0.5 ${
                      enableAutoReview ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>

              {/* Auto Review machine size */}
              <div className="flex items-center justify-between p-5">
                <div className="space-y-0.5 max-w-lg">
                  <h3 className="text-xs font-semibold text-fg">
                    Auto Review machine size
                  </h3>
                  <p className="text-xs text-muted">
                    Choose the machine size BoxFox uses to review pull requests automatically.
                  </p>
                </div>

                <CustomSelect
                  value={machineSize}
                  onChange={setMachineSize}
                  options={MACHINE_SIZE_OPTIONS}
                  className="w-56"
                />
              </div>

              {/* Review new commits pushed to PRs */}
              <div className="p-5 space-y-3">
                <div className="flex items-center justify-between">
                  <div className="space-y-0.5 max-w-xl">
                    <h3 className="text-xs font-semibold text-fg">
                      Review new commits pushed to PRs
                    </h3>
                    <p className="text-xs text-muted">
                      For each new head commit, add a follow-up review message to the same PR review session.
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={() => setReviewNewCommits(!reviewNewCommits)}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors duration-200 ease-in-out focus:outline-hidden ${
                      reviewNewCommits ? 'bg-brand border-brand' : 'bg-panel2 border-line'
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block size-3.5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out m-0.5 ${
                        reviewNewCommits ? 'translate-x-4' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>

                {/* Sub Card: Use risk assessment */}
                <div className="rounded-xl border border-line bg-panel2 p-4 flex items-center justify-between mt-2">
                  <div className="space-y-0.5 max-w-lg">
                    <h4 className="text-xs font-semibold text-fg">Use risk assessment</h4>
                    <p className="text-[11px] text-muted">
                      Calculate PR merge risk after auto review completes and post the findings as a separate PR comment.
                    </p>
                  </div>

                  <button
                    type="button"
                    onClick={() => setUseRiskAssessment(!useRiskAssessment)}
                    className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors duration-200 ease-in-out focus:outline-hidden ${
                      useRiskAssessment ? 'bg-brand border-brand' : 'bg-panel2 border-line'
                    }`}
                  >
                    <span
                      className={`pointer-events-none inline-block size-3.5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out m-0.5 ${
                        useRiskAssessment ? 'translate-x-4' : 'translate-x-0'
                      }`}
                    />
                  </button>
                </div>
              </div>

              {/* Enable testing in auto reviews */}
              <div className="flex items-center justify-between p-5">
                <div className="space-y-0.5 max-w-xl">
                  <h3 className="text-xs font-semibold text-fg">
                    Enable testing in auto reviews
                  </h3>
                  <p className="text-xs text-muted">
                    Include manual UI/API testing when reviewing PRs
                  </p>
                </div>

                <button
                  type="button"
                  onClick={() => setEnableTestingInReviews(!enableTestingInReviews)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors duration-200 ease-in-out focus:outline-hidden ${
                    enableTestingInReviews ? 'bg-brand border-brand' : 'bg-panel2 border-line'
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block size-3.5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out m-0.5 ${
                      enableTestingInReviews ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>

              {/* Daily review limit */}
              <div className="flex items-center justify-between p-5">
                <div className="space-y-0.5 max-w-lg">
                  <h3 className="text-xs font-semibold text-fg">Daily review limit</h3>
                  <p className="text-xs text-muted">
                    Maximum auto-reviews per day (0 = no reviews allowed, max 1000)
                  </p>
                </div>

                <div className="w-20">
                  <input
                    type="number"
                    value={dailyReviewLimit}
                    onChange={(e) => setDailyReviewLimit(Number(e.target.value))}
                    min={0}
                    max={1000}
                    className="w-full rounded-lg border border-line bg-panel2 px-3 py-1.5 text-xs text-fg text-center outline-hidden focus:border-brand font-mono"
                  />
                </div>
              </div>
            </div>
          </div>

          {/* C. MERGE QUEUE CONTAINER */}
          <div className="space-y-3">
            <span className="text-[11px] font-bold uppercase tracking-wider text-muted">
              MERGE QUEUE
            </span>

            <div className="rounded-2xl border border-line bg-panel p-5 shadow-xs flex items-center justify-between">
              <div className="space-y-1 max-w-xl">
                <div className="flex items-center gap-2">
                  <h3 className="text-xs font-semibold text-fg">
                    Enable automerge by default
                  </h3>
                  <span className="rounded bg-brand/15 border border-brand/30 px-2 py-0.2 text-[9px] font-bold text-brand font-mono">
                    GitHub only
                  </span>
                </div>
                <p className="text-xs text-muted">
                  Automatically enqueue agent-created pull requests into the merge queue for validation and landing.
                </p>
              </div>

              <button
                type="button"
                onClick={() => setEnableAutomerge(!enableAutomerge)}
                className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors duration-200 ease-in-out focus:outline-hidden ${
                  enableAutomerge ? 'bg-brand border-brand' : 'bg-panel2 border-line'
                }`}
              >
                <span
                  className={`pointer-events-none inline-block size-3.5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out m-0.5 ${
                    enableAutomerge ? 'translate-x-4' : 'translate-x-0'
                  }`}
                />
              </button>
            </div>
          </div>
        </div>
      ) : (
        /* ========================================================================= */
        /* 2. MY SETTINGS */
        /* ========================================================================= */
        <div className="space-y-4">
          <span className="text-[11px] font-bold uppercase tracking-wider text-muted">
            PULL REQUESTS
          </span>

          <div className="rounded-2xl border border-line bg-panel divide-y divide-line/80 shadow-xs">
            {/* Auto-archive session on PR merge */}
            <div className="flex items-center justify-between p-5">
              <div className="space-y-0.5 max-w-xl">
                <h3 className="text-xs font-semibold text-fg">
                  Auto-archive session on PR merge
                </h3>
                <p className="text-xs text-muted">
                  Automatically archive a session when all its associated pull requests are merged.
                </p>
              </div>

              <div className="flex items-center gap-3">
                <span className="text-[11px] text-muted">Team default</span>
                <button
                  type="button"
                  onClick={() => setMyAutoArchive(!myAutoArchive)}
                  className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border transition-colors duration-200 ease-in-out focus:outline-hidden ${
                    myAutoArchive ? 'bg-brand border-brand' : 'bg-panel2 border-line'
                  }`}
                >
                  <span
                    className={`pointer-events-none inline-block size-3.5 transform rounded-full bg-white shadow-sm ring-0 transition duration-200 ease-in-out m-0.5 ${
                      myAutoArchive ? 'translate-x-4' : 'translate-x-0'
                    }`}
                  />
                </button>
              </div>
            </div>

            {/* PR author with Interactive GitHub Connected / Add / Disconnect */}
            <div className="p-5 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-xs font-semibold text-fg">PR author</h3>
                  <p className="text-xs text-muted">
                    Choose who appears as the author on pull requests
                  </p>
                </div>
                <span className="text-[11px] text-muted">Team default</span>
              </div>

              <div className="space-y-2 pt-1">
                <CustomRadio
                  checked={myPrAuthor === 'boxfox'}
                  onChange={() => setMyPrAuthor('boxfox')}
                  label="BoxFox"
                  description="PRs are authored by the BoxFox bot account."
                />
                <CustomRadio
                  checked={myPrAuthor === 'me'}
                  onChange={() => setMyPrAuthor('me')}
                  label="Me"
                  description="PRs are authored using your personal GitHub account."
                />
              </div>

              {/* GitHub Connection Badge & Action Buttons */}
              <div className="flex items-center justify-between rounded-xl border border-line bg-panel2 p-3 mt-2">
                {githubConnected ? (
                  <>
                    <div className="flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400 font-medium">
                      <CheckCircle2 className="size-4" />
                      <span>GitHub connected ({githubAccount})</span>
                    </div>

                    <button
                      type="button"
                      onClick={handleDisconnectGithub}
                      className="rounded-md border border-line bg-panel px-3 py-1 text-xs font-medium text-muted hover:text-rose-500 hover:border-rose-500/40 transition cursor-pointer"
                    >
                      Disconnect
                    </button>
                  </>
                ) : (
                  <>
                    <div className="flex items-center gap-2 text-xs text-muted">
                      <XCircle className="size-4 text-muted" />
                      <span>GitHub not connected</span>
                    </div>

                    <button
                      type="button"
                      onClick={handleConnectGithub}
                      className="flex items-center gap-1.5 rounded-md bg-brand px-3 py-1 text-xs font-semibold text-brandfg hover:opacity-90 shadow-xs transition cursor-pointer"
                    >
                      <Plus className="size-3.5" />
                      <span>Connect GitHub account</span>
                    </button>
                  </>
                )}
              </div>
            </div>

            {/* PR creation mode */}
            <div className="p-5 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-xs font-semibold text-fg">PR creation mode</h3>
                  <p className="text-xs text-muted">
                    Choose how pull requests are created for your sessions
                  </p>
                </div>
                <span className="text-[11px] text-muted">Team default</span>
              </div>

              <div className="space-y-2 pt-1">
                <CustomRadio
                  checked={myCreationMode === 'automatic'}
                  onChange={() => setMyCreationMode('automatic')}
                  label="Automatic"
                  description="BoxFox creates PRs automatically when your code is ready."
                />
                <CustomRadio
                  checked={myCreationMode === 'manual'}
                  onChange={() => setMyCreationMode('manual')}
                  label="Manual"
                  description="Review your changes in the Code Diff panel and click 'Create PR' when you're ready."
                />
              </div>
            </div>

            {/* PR type */}
            <div className="p-5 space-y-3">
              <div className="flex items-center justify-between">
                <div>
                  <h3 className="text-xs font-semibold text-fg">PR type</h3>
                  <p className="text-xs text-muted">
                    Choose what type of pull request BoxFox creates
                  </p>
                </div>
                <span className="text-[11px] text-muted">Team default</span>
              </div>

              <div className="space-y-2 pt-1">
                <CustomRadio
                  checked={myPrType === 'open'}
                  onChange={() => setMyPrType('open')}
                  label="Open PR"
                  description="Creates a standard open pull request, ready for review."
                />
                <CustomRadio
                  checked={myPrType === 'draft'}
                  onChange={() => setMyPrType('draft')}
                  label="Draft PR"
                  description="Creates a draft pull request so you can review before marking as ready."
                />
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
