"""Bounded Work Graph budgets; owner ceilings and verification gates still apply.

Live W6.5: a 42-source chain exhausted 40 steps (37 reads plus wrap-up),
while 60 completed it. Long checks need more than 14 steps; increasing to
40 did not establish that skipped artifact ranges become verified.
"""

PRODUCER_STEPS = 60
SHORT_REVIEW_STEPS = 14
LONG_REVIEW_STEPS = 24
LARGE_ARTIFACT_CHARS = 32000
MANY_CRITERIA = 8


def profiles():
    return {'deliverableMaxSteps': PRODUCER_STEPS, 'shortCheckMaxSteps': SHORT_REVIEW_STEPS,
            'longCheckMaxSteps': LONG_REVIEW_STEPS, 'largeArtifactChars': LARGE_ARTIFACT_CHARS,
            'manyCriteria': MANY_CRITERIA, 'ownerClamped': True}


def review_hints(metas, criteria, risk='normal'):
    return {'artifactCount': len(metas), 'artifactChars': sum(m['chars'] for m in metas),
            'criterionCount': len(criteria), 'risk': risk}


def requested(role, work, task_kind, legacy_steps, legacy_seconds):
    """Only the harness supplies work/hints, never delegate tool arguments."""
    if not work:
        return {'profile': 'legacy', 'maxSteps': legacy_steps, 'deadlineSeconds': legacy_seconds}
    if work.get('purpose') == 'review':
        hints = work.get('budgetHints') or {}
        long = (hints.get('artifactCount', 0) > 1
                or hints.get('artifactChars', 0) > LARGE_ARTIFACT_CHARS
                or hints.get('criterionCount', 0) > MANY_CRITERIA
                or hints.get('risk') == 'consequential')
        return {'profile': 'review_long' if long else 'review_short',
                'maxSteps': LONG_REVIEW_STEPS if long else SHORT_REVIEW_STEPS,
                'deadlineSeconds': legacy_seconds}
    long = (work.get('purpose') == 'produce' and role in ('research', 'plan', 'design')
            and task_kind not in ('lookup', 'diagnostic'))
    return {'profile': 'deliverable' if long else 'lookup_or_execution',
            'maxSteps': PRODUCER_STEPS if long else legacy_steps,
            'deadlineSeconds': legacy_seconds}


def applied(request, config):
    steps, seconds = config['maxSteps'], config['deadlineSeconds']
    return {'profile': request['profile'], 'requestedMaxSteps': request['maxSteps'],
            'effectiveMaxSteps': steps, 'requestedDeadlineSeconds': request['deadlineSeconds'],
            'effectiveDeadlineSeconds': seconds,
            'clamped': steps < request['maxSteps'] or seconds < request['deadlineSeconds']}


def receipt(result):
    """Persist real measurements separately from Markdown and source citations."""
    return {key: result.get(key) for key in ('status', 'reason', 'budget', 'stepsUsed',
                                           'outputTokens', 'wallMs')} | {
        'toolCalls': len(result['tools_run']) if isinstance(result.get('tools_run'), list) else None}
