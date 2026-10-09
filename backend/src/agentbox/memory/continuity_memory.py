"""Capsules retain facts, never capability/approval credentials."""


def safe_state(value):
    forbidden = {'token', 'password', 'secret', 'grant', 'lease', 'capability', 'approval', 'authorization'}
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in forbidden or str(key).lower().endswith(('token', 'secret', 'password', 'grant', 'lease', 'capability')):
                raise ValueError('CAPSULE_AUTHORITY_FIELD_FORBIDDEN')
            safe_state(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            safe_state(item)
