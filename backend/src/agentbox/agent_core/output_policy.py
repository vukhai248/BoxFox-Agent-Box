"""Output budgets and completion facts. No scheduler, route selection, or UI policy."""
import os

DEFAULT_OUTPUT_TOKENS = 4096
RESEARCH_OUTPUT_TOKENS = 16000  # 8k/12k hit the cap in the Space Bunny long-report fixtures.
DOCUMENT_OUTPUT_TOKENS = 16000
REVIEW_OUTPUT_TOKENS = 16000  # W6: user requested measured 8k/16k reviewer comparison.
# W6.5.3: nested lookup helper (work purpose `knowledge`). Measured 02/10/2026 on Space Bunny:
# 5/16 runs at 4096 ended `length` (0/16 at 16000) and median wall time was not worse at 16000
# (docs/plan/W6.5.3-helper-budget-evidence.json). Keep the knob for re-measurement only.
WORK_HELPER_OUTPUT_TOKENS = 16000
WORK_CHECK_OUTPUT_TOKENS = REVIEW_OUTPUT_TOKENS
MAX_OUTPUT_TOKENS = 64000  # Existing router request limit, not a model capability.
RECOVERY_INPUT_MAX_CHARS = 64000
STREAM_INTERRUPTED_CODE = 'PROVIDER_STREAM_INTERRUPTED'
REASONING_ONLY_CODE = 'PROVIDER_REASONING_ONLY'


def positive_budget(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= MAX_OUTPUT_TOKENS:
        raise ValueError(f'OUTPUT_BUDGET_INVALID: {field} must be an integer in 1–{MAX_OUTPUT_TOKENS}')
    return value


def configured_budget(name, default, choices):
    raw = os.environ.get(name)
    if raw is None:
        return default
    if not raw.isdigit() or int(raw) not in choices:
        raise ValueError(f'OUTPUT_BUDGET_INVALID: {name} must be one of {sorted(choices)}')
    return int(raw)


def child_budget(role, work=None, task_kind=None):
    work = work or {}
    if work.get('purpose') == 'review' and work.get('checkId'):
        return configured_budget('BOXFOX_WORK_CHECK_OUTPUT_TOKENS', WORK_CHECK_OUTPUT_TOKENS, {4096, 8192, 16000})
    if role in {'review', 'plan-review', 'research-review'}:
        return configured_budget('BOXFOX_REVIEW_OUTPUT_TOKENS', REVIEW_OUTPUT_TOKENS, {8192, 16000})
    if work.get('purpose') == 'knowledge':
        return configured_budget('BOXFOX_WORK_HELPER_OUTPUT_TOKENS', WORK_HELPER_OUTPUT_TOKENS,
                                 {DEFAULT_OUTPUT_TOKENS, WORK_HELPER_OUTPUT_TOKENS})
    if work and (work.get('purpose') != 'produce' or work.get('stage') != 'produce'):
        return None
    if role in {'plan', 'design'}:
        return configured_budget('BOXFOX_DOCUMENT_OUTPUT_TOKENS', DOCUMENT_OUTPUT_TOKENS, {16000, 32000})
    if role == 'research' and task_kind != 'knowledge':
        return configured_budget('BOXFOX_RESEARCH_OUTPUT_TOKENS', RESEARCH_OUTPUT_TOKENS, {8192, 12288, 16000})
    return None


def model_output_ceiling(metadata):
    if not isinstance(metadata, dict):
        return None
    values = [metadata.get(key) for key in ('maxOutputTokens', 'max_output_tokens', 'outputTokenLimit')]
    limits = metadata.get('limit')
    if isinstance(limits, dict):
        values.append(limits.get('output'))
    published = [v for v in values if isinstance(v, int) and not isinstance(v, bool) and v > 0]
    return min(published) if published else None


def request_budget(config, input_estimate=0):
    requested = positive_budget(config.get('maxTokens', DEFAULT_OUTPUT_TOKENS), 'maxTokens')
    ceiling = config.get('outputTokenCeiling')
    owner = positive_budget(ceiling, 'outputTokenCeiling') if ceiling is not None else None
    metadata = config.get('modelMetadata')
    route = config.get('route') or {}
    if isinstance(metadata, dict) and route.get('modelId') and metadata.get('id') != route['modelId']:
        metadata = None
    provider = model_output_ceiling(metadata)
    candidates = [requested] + [v for v in (owner, provider) if v is not None]
    context = config.get('contextWindow')
    if isinstance(context, int) and not isinstance(context, bool) and context > 0:
        room = context - max(0, input_estimate) - 512
        if room < 1:
            raise ValueError('OUTPUT_CONTEXT_EXHAUSTED: no output room remains; compact context before requesting a completion')
        candidates.append(room)
    return min(candidates)


def completion_reason(response):
    choice = ((response.get('choices') or [{}])[0])
    message = choice.get('message') or {}
    finish = choice.get('finish_reason')
    if message.get('refusal') or finish in {'content_filter', 'refusal'}:
        return 'provider_refusal'
    if finish in {'error', 'failed'}:
        return 'provider_error'
    if finish in {'stream_incomplete', 'stream_interrupted'}:
        return 'stream_interrupted'
    if finish in {'length', 'max_tokens'}:
        return 'output_limit'
    if finish not in {'stop', 'end_turn', 'tool_calls', 'function_call'}:
        return 'stream_interrupted'
    if not (message.get('content') or '').strip() and not message.get('tool_calls'):
        if message.get('reasoning_content') or message.get('thought') or choice.get('reasoning_content'):
            return 'reasoning_only'
        return 'empty'
    return 'complete'


def usage_counts(usage):
    usage = usage if isinstance(usage, dict) else {}
    def count(*values):
        return next((v for v in values if isinstance(v, int) and not isinstance(v, bool) and v >= 0), None)
    details = usage.get('completion_tokens_details') or usage.get('output_tokens_details') or {}
    details = details if isinstance(details, dict) else {}
    return {'inputTokens': count(usage.get('prompt_tokens'), usage.get('input_tokens')),
            'outputTokens': count(usage.get('completion_tokens'), usage.get('output_tokens')),
            'reasoningTokens': count(usage.get('reasoning_tokens'), details.get('reasoning_tokens'))}
