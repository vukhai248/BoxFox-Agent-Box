"""Lazy full-source skill loading adapted from Hermes skills_tool; never preprocess shell."""
from pathlib import Path
import hashlib
import yaml

ROOT = Path(__file__).resolve().parents[1] / 'vendor/hermes'
DEFAULT_SKILLS = {'codebase-inspection', 'systematic-debugging', 'requesting-code-review', 'simplify-code', 'test-driven-development', 'grounded-citations',
                  # Vòng 24 (D-31): dạng câu trả lời cuối (menu phần, đoạn mở đầu, ảnh khép
                  # câu trả lời) nằm trong chính kỹ năng này — phiên MỚI nhận mặc định; phiên
                  # đang chạy giữ danh sách kỹ năng của nó (không hồi tố).
                  'final-report',
                  # Vòng 25 (D-33): vòng lặp kế hoạch (nghiên cứu → ghi → phản biện → ghi nhận
                  # verdict → duyệt). Nhận mặc định vì lượt lập kế hoạch nào cũng cần nó.
                  'planning',
                  # Work Graph: main opens this procedure with `skill_view` on every non-trivial request.
                  'work-graph-planning',
                  # Vòng 27 (A7/C-1): ba mức + bốn pha + sổ nguồn + hình dạng hồ sơ. Nhận mặc
                  # định vì mọi lượt nghiên cứu đều phải mở đầu bằng `research_brief`.
                  'research-team', 'research-scoping', 'research-search', 'research-reading',
                  'research-evidence', 'research-synthesis', 'research-critique', 'research-to-plan',
                  # Vòng 27 (A7): `arxiv` gọi `web_fetch` trên API export.arxiv.org (không còn
                  # `curl` — vai research không có `terminal_exec`); `blocked-page-recovery` là
                  # thang 5 bậc cho trang bị chặn, đúng việc research và không cần gói nào.
                  'arxiv', 'blocked-page-recovery'}


# Sáu kỹ năng nghiên cứu CỐ Ý để TẮT (vòng 27, A7) — không phải bỏ quên. Lý do có chữ:
#   rss-feeds, blogwatcher  — cần script/CLI trong box chạy nền (#5977 cấm cài gói).
#   pdf                     — cần `pdftotext`/`pypdf`/`tesseract`; box không có, không cài được.
#   scrapling               — cần gói Python ngoài .venv của box.
#   duckduckgo-search, searxng-search — cần script + điểm cuối tìm kiếm ngoài; harness đã có
#                             `web_search` (HOST) làm đúng việc đó, không cần kỹ năng trùng.
# Mở lại theo thứ tự rss-feeds → pdf → scrapling khi Phạm vi A giao runner/allowlist cho script.
DISABLED_RESEARCH_SKILLS = {'rss-feeds', 'blogwatcher', 'pdf', 'scrapling', 'duckduckgo-search', 'searxng-search'}
DISABLED_RESEARCH_REASON = ('cần gói/script không cài được trong box (#5977) — xem khối chú thích '
                            'DISABLED_RESEARCH_SKILLS trong catalog.py')


class SkillCatalog:
    def __init__(self, root=ROOT):
        self.root = Path(root).resolve()
        self.items = {}
        for group in ['skills', 'optional-skills']:
            for path in sorted((self.root / group).rglob('SKILL.md')):
                content = path.read_text(encoding='utf-8')
                parts = content.split('---', 2)
                try:
                    meta = yaml.safe_load(parts[1]) if content.startswith('---') and len(parts) == 3 else {}
                except yaml.YAMLError:
                    meta = {}
                meta = meta if isinstance(meta, dict) else {}
                hermes = (meta.get('metadata') or {}).get('hermes', {})
                hermes = hermes if isinstance(hermes, dict) else {}
                sid = path.parent.name
                if sid in self.items:
                    sid = path.parent.relative_to(self.root).as_posix()
                self.items[sid] = {
                    'id': sid, 'name': str(meta.get('name', path.parent.name)),
                    'category': path.relative_to(self.root).parts[1],
                    'description': str(meta.get('description', 'Upstream skill package.')),
                    'source': 'hermes', 'enabled': sid in DEFAULT_SKILLS,
                    'optional': group == 'optional-skills', 'tags': hermes.get('tags', []),
                    'relatedSkills': hermes.get('related_skills', []),
                    'requirements': {'commands': meta.get('required_commands', []),
                                     'environment': meta.get('required_environment_variables', []),
                                     'files': meta.get('required_credential_files', [])},
                    'platforms': meta.get('platforms', []), 'readiness': 'requires-environment-check',
                    'instructions': '', 'sha256': hashlib.sha256(content.encode('utf-8')).hexdigest(),
                    '_path': path,
                }

    def list(self, enabled=None):
        return [{k: v for k, v in item.items() if k != '_path'} | (
            {'enabled': item['id'] in enabled} if enabled is not None else {}) for item in self.items.values()]

    def read(self, sid, file_path='SKILL.md'):
        if sid not in self.items:
            raise ValueError('Unknown skill')
        directory = self.items[sid]['_path'].parent.resolve()
        path = (directory / file_path).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise ValueError('Skill file must be inside its package')
        # Instruction files are read fully, without pagination or shell preprocessing.
        text = path.read_text(encoding='utf-8')
        linked = [p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()]
        return {'id': sid, 'content': text, 'file': file_path, 'linkedFiles': linked,
                'basePath': '/opt/boxfox-skills/' + directory.relative_to(self.root).as_posix(),
                'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}

    def prompt(self, enabled):
        return '\n'.join(f"- {s['id']}: {s['description']}" for s in self.list() if s['id'] in enabled)
