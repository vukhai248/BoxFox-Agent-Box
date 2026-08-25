/**
 * Dữ liệu mock cho bước chụp màn hình (Step 9 Demo Screen Capture)
 * và quay video màn hình (Step 11 Demo Screen Recording).
 */

// 1. Browser Unit Testing Suite Report Screenshot
const SVG_1 = `
<svg width="1280" height="720" viewBox="0 0 1280 720" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="1280" height="720" rx="16" fill="#0f1117"/>
  <!-- Browser Header Bar -->
  <rect width="1280" height="48" rx="16" fill="#181a24"/>
  <circle cx="28" cy="24" r="6" fill="#ef4444"/>
  <circle cx="48" cy="24" r="6" fill="#f59e0b"/>
  <circle cx="68" cy="24" r="6" fill="#10b981"/>
  <!-- URL Bar -->
  <rect x="100" y="10" width="700" height="28" rx="8" fill="#0f1117" stroke="#2a2e3d"/>
  <text x="120" y="28" fill="#9ca3af" font-family="JetBrains Mono, monospace" font-size="12">http://localhost:5173/__vitest__/ - Automated Test Runner</text>
  <rect x="1140" y="12" width="110" height="24" rx="6" fill="#10b981" fill-opacity="0.15" stroke="#10b981" stroke-opacity="0.3"/>
  <text x="1155" y="28" fill="#10b981" font-family="system-ui, sans-serif" font-size="11" font-weight="bold">&#9679; LIVE SANDBOX</text>

  <!-- Left Test Suite Sidebar -->
  <rect x="24" y="72" width="340" height="624" rx="12" fill="#181a24" stroke="#2a2e3d"/>
  <text x="44" y="105" fill="#ffffff" font-family="system-ui, sans-serif" font-size="15" font-weight="bold">Test Suites (3 passed)</text>
  <rect x="44" y="120" width="300" height="2" fill="#2a2e3d"/>

  <!-- Test Item 1 -->
  <rect x="40" y="136" width="308" height="52" rx="8" fill="#10b981" fill-opacity="0.08" stroke="#10b981" stroke-opacity="0.25"/>
  <text x="56" y="160" fill="#10b981" font-family="system-ui, sans-serif" font-size="14" font-weight="bold">&#10003;</text>
  <text x="76" y="160" fill="#f3f4f6" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold">src/lib/permissions.test.ts</text>
  <text x="76" y="176" fill="#9ca3af" font-family="system-ui, sans-serif" font-size="10">2 passed (6ms)</text>

  <!-- Test Item 2 -->
  <rect x="40" y="198" width="308" height="52" rx="8" fill="#10b981" fill-opacity="0.08" stroke="#10b981" stroke-opacity="0.25"/>
  <text x="56" y="222" fill="#10b981" font-family="system-ui, sans-serif" font-size="14" font-weight="bold">&#10003;</text>
  <text x="76" y="222" fill="#f3f4f6" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold">src/lib/scope.test.ts</text>
  <text x="76" y="238" fill="#9ca3af" font-family="system-ui, sans-serif" font-size="10">6 passed (9ms)</text>

  <!-- Test Item 3 -->
  <rect x="40" y="260" width="308" height="52" rx="8" fill="#10b981" fill-opacity="0.08" stroke="#10b981" stroke-opacity="0.25"/>
  <text x="56" y="284" fill="#10b981" font-family="system-ui, sans-serif" font-size="14" font-weight="bold">&#10003;</text>
  <text x="76" y="284" fill="#f3f4f6" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold">src/lib/labels.test.ts</text>
  <text x="76" y="300" fill="#9ca3af" font-family="system-ui, sans-serif" font-size="10">6 passed (5ms)</text>

  <!-- Right Detailed Log View -->
  <rect x="384" y="72" width="872" height="624" rx="12" fill="#13151f" stroke="#2a2e3d"/>
  <!-- Status Badge Cards -->
  <rect x="408" y="96" width="180" height="70" rx="10" fill="#181a24" stroke="#2a2e3d"/>
  <text x="424" y="122" fill="#9ca3af" font-family="system-ui, sans-serif" font-size="11" font-weight="600">TEST STATUS</text>
  <text x="424" y="148" fill="#10b981" font-family="system-ui, sans-serif" font-size="18" font-weight="bold">100% PASSED</text>

  <rect x="604" y="96" width="180" height="70" rx="10" fill="#181a24" stroke="#2a2e3d"/>
  <text x="620" y="122" fill="#9ca3af" font-family="system-ui, sans-serif" font-size="11" font-weight="600">DURATION</text>
  <text x="620" y="148" fill="#60a5fa" font-family="system-ui, sans-serif" font-size="18" font-weight="bold">2.10s</text>

  <rect x="800" y="96" width="180" height="70" rx="10" fill="#181a24" stroke="#2a2e3d"/>
  <text x="816" y="122" fill="#9ca3af" font-family="system-ui, sans-serif" font-size="11" font-weight="600">TOTAL ASSERTIONS</text>
  <text x="816" y="148" fill="#a78bfa" font-family="system-ui, sans-serif" font-size="18" font-weight="bold">14 passed</text>

  <!-- Execution Timeline Trace -->
  <rect x="408" y="186" width="824" height="486" rx="8" fill="#0f1117" stroke="#2a2e3d"/>
  <text x="428" y="216" fill="#10b981" font-family="JetBrains Mono, monospace" font-size="13">&#10003; [16:28:07] RUN  v4.1.11 D:/create/BoxFox-Agent-Box/frontend</text>
  <text x="428" y="246" fill="#f3f4f6" font-family="JetBrains Mono, monospace" font-size="13">&#10003; src/lib/permissions.test.ts (2 tests) 4ms</text>
  <text x="428" y="276" fill="#f3f4f6" font-family="JetBrains Mono, monospace" font-size="13">&#10003; src/lib/scope.test.ts (6 tests) 4ms</text>
  <text x="428" y="306" fill="#f3f4f6" font-family="JetBrains Mono, monospace" font-size="13">&#10003; src/lib/labels.test.ts (6 tests) 5ms</text>
  <text x="428" y="346" fill="#9ca3af" font-family="JetBrains Mono, monospace" font-size="12">============================== 14 passed in 0.04s ===============================</text>
</svg>
`

// 2. Application UI Render Preview Screenshot
const SVG_2 = `
<svg width="1280" height="720" viewBox="0 0 1280 720" fill="none" xmlns="http://www.w3.org/2000/svg">
  <rect width="1280" height="720" rx="16" fill="#090a0f"/>
  <!-- Top Navigation -->
  <rect width="1280" height="56" fill="#11131c" stroke="#222533"/>
  <rect x="24" y="14" width="28" height="28" rx="6" fill="#3b82f6"/>
  <text x="64" y="33" fill="#ffffff" font-family="system-ui, sans-serif" font-size="15" font-weight="bold">BoxFox Studio</text>
  <rect x="200" y="14" width="340" height="28" rx="8" fill="#181a26" stroke="#2a2e3d"/>
  <text x="216" y="32" fill="#6b7280" font-family="system-ui, sans-serif" font-size="11">Search files, symbols, commands...</text>

  <!-- Sidebar -->
  <rect x="0" y="56" width="260" height="664" fill="#0f1118" stroke="#222533"/>
  <text x="24" y="88" fill="#9ca3af" font-family="system-ui, sans-serif" font-size="11" font-weight="600">EXPLORER</text>
  <rect x="16" y="104" width="228" height="32" rx="6" fill="#1e2233"/>
  <text x="32" y="125" fill="#60a5fa" font-family="JetBrains Mono, monospace" font-size="12">&#9660; src/</text>
  <text x="48" y="153" fill="#9ca3af" font-family="JetBrains Mono, monospace" font-size="12">&#128196; parser.py</text>
  <text x="48" y="181" fill="#9ca3af" font-family="JetBrains Mono, monospace" font-size="12">&#128196; token_stream.py</text>
  <text x="48" y="209" fill="#9ca3af" font-family="JetBrains Mono, monospace" font-size="12">&#128196; ast_tree.py</text>

  <!-- Main Code Editor Area -->
  <rect x="260" y="56" width="680" height="664" fill="#0a0c13"/>
  <!-- Editor Tabs -->
  <rect x="260" y="56" width="680" height="36" fill="#11131c" stroke="#222533"/>
  <rect x="260" y="56" width="160" height="36" fill="#0a0c13" stroke="#222533"/>
  <text x="280" y="79" fill="#f3f4f6" font-family="JetBrains Mono, monospace" font-size="12">parser.py</text>

  <!-- Code Lines Preview -->
  <text x="280" y="120" fill="#3b82f6" font-family="JetBrains Mono, monospace" font-size="13">class <tspan fill="#60a5fa">UnmatchedBracketError</tspan>(ValueError):</text>
  <text x="304" y="145" fill="#10b981" font-family="JetBrains Mono, monospace" font-size="13">"""Raised when parenthesis/bracket counts are unbalanced."""</text>
  <text x="304" y="170" fill="#f43f5e" font-family="JetBrains Mono, monospace" font-size="13">def <tspan fill="#60a5fa">__init__</tspan>(self, message: str, position: int):</text>
  <text x="328" y="195" fill="#f3f4f6" font-family="JetBrains Mono, monospace" font-size="13">super().__init__(f"{message} at index {position}")</text>
  <text x="328" y="220" fill="#f3f4f6" font-family="JetBrains Mono, monospace" font-size="13">self.position = position</text>

  <!-- Right Visual Output Preview Panel -->
  <rect x="940" y="56" width="340" height="664" fill="#0f1118" stroke="#222533"/>
  <rect x="956" y="80" width="308" height="280" rx="12" fill="#161924" stroke="#2e3347"/>
  <text x="976" y="110" fill="#ffffff" font-family="system-ui, sans-serif" font-size="14" font-weight="bold">Parsed Expression AST</text>
  <circle cx="1110" cy="180" r="28" fill="#3b82f6" fill-opacity="0.2" stroke="#3b82f6" stroke-width="2"/>
  <text x="1098" y="185" fill="#60a5fa" font-family="JetBrains Mono, monospace" font-size="12" font-weight="bold">ROOT</text>
  <circle cx="1040" cy="260" r="22" fill="#10b981" fill-opacity="0.2" stroke="#10b981" stroke-width="2"/>
  <text x="1028" y="265" fill="#34d399" font-family="JetBrains Mono, monospace" font-size="11" font-weight="bold">OP(+)</text>
  <circle cx="1180" cy="260" r="22" fill="#a855f7" fill-opacity="0.2" stroke="#a855f7" stroke-width="2"/>
  <text x="1168" y="265" fill="#c084fc" font-family="JetBrains Mono, monospace" font-size="11" font-weight="bold">VAR(x)</text>
  <line x1="1090" y1="195" x2="1055" y2="240" stroke="#4b5563" stroke-width="2"/>
  <line x1="1130" y1="195" x2="1165" y2="240" stroke="#4b5563" stroke-width="2"/>
</svg>
`

export const SCREENSHOT_TEST_RUNNER = `data:image/svg+xml;utf8,${encodeURIComponent(SVG_1)}`
export const SCREENSHOT_AST_RENDER = `data:image/svg+xml;utf8,${encodeURIComponent(SVG_2)}`

// 3. Screen Recording Video Mock (High Performance WebM/MP4)
export const SCREEN_RECORDING_SESSION_VIDEO =
  'https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ForBiggerBlazes.mp4'
export const SCREEN_RECORDING_POSTER = SCREENSHOT_TEST_RUNNER

export const SCREENSHOT_TEST_REPORT_SVG = SCREENSHOT_TEST_RUNNER
export const SCREENSHOT_APP_PREVIEW_SVG = SCREENSHOT_AST_RENDER
