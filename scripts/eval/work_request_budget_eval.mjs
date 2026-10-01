/** W6.5 real Space Bunny request deadlines, no production settings or sessions. */
import { execFileSync } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve, relative, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createProviders } from '../../router/src/providers/index.mjs';

const root = fileURLToPath(new URL('../../', import.meta.url));
if (execFileSync('git', ['branch', '--show-current'], { cwd: root, encoding: 'utf8' }).trim() !== 'B') throw new Error('Branch B required');
const out = resolve(root, process.argv[2] || '.tmp/work-checks/w65-request-time');
if (!relative(resolve(root, '.tmp'), out).startsWith(`work-checks${sep}`)) throw new Error('Disposable work-checks output required');
await mkdir(out, { recursive: true });
const provider = createProviders({ fetchImpl: fetch }).opencode;
const connection = { id: 'w65-request', providerId: 'opencode', endpoint: 'https://opencode.ai' };
const prompt = `Viết một kế hoạch SWE chi tiết bằng tiếng Việt cho app synthetic nhập CSV vào SQLite và xuất CSV giữ Unicode. Đây chỉ là phép đo tài liệu, không thực thi. Người dùng đã chốt Python 3.12+, CLI, SQLite local, không cloud, không dữ liệu thật, input là một file CSV với header case_id, date, note. Khoảng 10000 hàng/file; nhận diện file lỗi, báo hàng lỗi và có thể retry idempotent. Đề xuất M1–M8, kiến trúc và responsibility, schema/index/version/migration, input/output/errors, parsing newline/quotes, Unicode, validation, concurrency, atomic import, corruption/backup/rollback, observability, lựa chọn kỹ thuật và đánh đổi, bộ test fixture/expected/command chưa chạy, traceability, rủi ro. Mỗi milestone có vị trí dự kiến tạo/sửa, phụ thuộc, checkpoint và acceptance cụ thể. Các ngưỡng chưa đo phải ghi đề xuất. Không bịa test pass, benchmark, nguồn đã đọc hoặc quyết định người dùng. Viết đủ 3500–4500 từ để người khác triển khai; phần cuối là bảng traceability yêu cầu tới milestone/test. Không dành phần lớn output cho suy nghĩ.`;
const rows = [];
// Interleave rather than attributing a later provider load to the timeout alone.
for (const repeat of [1, 2]) for (const seconds of repeat === 1 ? [90, 180, 240] : [240, 180, 90]) {
  const started = performance.now();
  const row = { repeat, deadlineSeconds: seconds, model: 'opencode/space-bunny-free', maxTokens: 16000,
    scope: 'direct production OpenCode adapter, no HTTP client/whole child budget comparison',
    commit: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim() };
  let text = '', reasoning = '', firstDeltaMs = null;
  try {
    for await (const event of provider.generate({ connection, credentials: {},
      body: { model: 'space-bunny-free', stream: true, max_tokens: 16000,
        messages: [{ role: 'user', content: prompt }] }, signal: AbortSignal.timeout(seconds * 1000) })) {
      if (event.type === 'delta') {
        firstDeltaMs ??= performance.now() - started;
        text += event.delta?.content || '';
        reasoning += event.delta?.reasoning_content || event.delta?.reasoning || '';
      }
      if (event.type === 'usage') row.usage = event.usage;
      if (event.type === 'finish') row.finishReason = event.finishReason;
    }
    row.status = row.finishReason === 'stop' ? 'completed' : 'partial';
  } catch (error) {
    row.status = 'error';
    row.error = { name: error.name, code: error.code, message: String(error.message).slice(0, 500) };
  }
  row.seconds = (performance.now() - started) / 1000;
  row.firstDeltaMs = firstDeltaMs;
  row.answerChars = text.length;
  row.reasoningChars = reasoning.length;
  row.words = text.trim().split(/\s+/u).filter(Boolean).length;
  row.semanticAdjudication = 'pending; stop and word count do not prove professional quality';
  const name = `${seconds}-${repeat}`;
  await writeFile(resolve(out, `${name}.md`), text, 'utf8');
  await writeFile(resolve(out, `${name}-reasoning.txt`), reasoning, 'utf8');
  rows.push(row);
  await writeFile(resolve(out, 'results.json'), JSON.stringify(rows, null, 2), 'utf8');
  console.log(JSON.stringify(row));
}
