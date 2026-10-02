"""W6.1.3 — hợp đồng đối số của `verify_exec` (kiểm ở backend trước khi gửi xuống box).

Worker trong box kiểm lại lần nữa; ở đây chỉ để lỗi nêu đúng field và luật, đúng mục I của SOP
("A tool error names the field and the rule").
"""

LANGUAGES = ('python', 'node')
CODE_MAX = 8000
STDIN_MAX = 8000
CLAIM_MAX = 300
TIMEOUT_MIN, TIMEOUT_MAX, TIMEOUT_DEFAULT = 1, 20, 10


def arg_error(args):
    """Return None or 'VERIFY_EXEC_INVALID: <field> ...' for the first broken rule."""
    if not isinstance(args, dict):
        return 'VERIFY_EXEC_INVALID: arguments must be an object'
    language = args.get('language')
    if language not in LANGUAGES:
        return 'VERIFY_EXEC_INVALID: language must be one of python|node'
    for field, limit, required in (('code', CODE_MAX, True), ('claim', CLAIM_MAX, True),
                                   ('stdin', STDIN_MAX, False)):
        value = args.get(field)
        if value is None and not required:
            continue
        if not isinstance(value, str) or (required and not value.strip()):
            return f'VERIFY_EXEC_INVALID: {field} must be a non-empty string' if required \
                else f'VERIFY_EXEC_INVALID: {field} must be a string'
        if len(value) > limit:
            return f'VERIFY_EXEC_INVALID: {field} exceeds {limit} characters'
    timeout = args.get('timeoutSeconds')
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, int)
                                or not TIMEOUT_MIN <= timeout <= TIMEOUT_MAX):
        return f'VERIFY_EXEC_INVALID: timeoutSeconds must be an integer {TIMEOUT_MIN}-{TIMEOUT_MAX}'
    extra = sorted(set(args) - {'language', 'code', 'claim', 'stdin', 'timeoutSeconds'})
    if extra:
        return 'VERIFY_EXEC_INVALID: unknown field ' + extra[0]
    return None


UNPROBED = {'available': None, 'reason': 'not probed yet'}


def observed(result, previous=None):
    """Health view from a worker answer; unrelated results keep the previous state."""
    if not isinstance(result, dict):
        return previous or dict(UNPROBED)
    if result.get('errorCode') == 'VERIFY_EXEC_UNAVAILABLE' or \
            str(result.get('error') or '').startswith('VERIFY_EXEC_UNAVAILABLE'):
        return {'available': False, 'reason': str(result.get('error') or '')[:300]}
    if 'available' in result:  # verify_exec_probe
        return {'available': bool(result['available']), 'reason': result.get('reason'),
                'procMode': result.get('procMode')}
    if isinstance(result.get('receipt'), dict):
        return {'available': True, 'reason': None, 'procMode': result['receipt'].get('isolation')}
    return previous or dict(UNPROBED)
