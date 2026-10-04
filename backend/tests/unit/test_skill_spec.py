"""Fixture offline cho SkillSpec/readiness/registry: không model, provider hay mạng."""
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
import re

import pytest

from agentbox.agent_core import skill_spec
from agentbox.agent_core.orchestration_contracts import ContractError
from agentbox.agent_core.skill_spec import (
    SKILL_SCHEMA, SkillReadiness, SkillRegistry, SkillSpec, readiness, revalidate,
)
from agentbox.agent_core.work_policy import digest
from agentbox.memory.session_store import SessionStore


def payload(**updates):
    value = {
        'schemaVersion': SKILL_SCHEMA, 'id': 'boxfox-web-preview', 'version': 1,
        'title': 'Verify a running web app',
        'goal': 'Prove the selected preview route serves the expected app.',
        'trigger': {'intents': ['implementation'], 'artifactKinds': ['patch'],
                    'actionClasses': ['preview']},
        'applicability': {'roles': ['build'], 'environments': ['linux'],
                          'exclusions': ['production']},
        'requirements': {'tools': ['run_command'], 'capabilities': ['process.jobs'],
                         'commands': ['npm'], 'environmentRefs': ['env:node'],
                         'packages': ['pytest']},
        'provenance': {'origin': 'authored', 'sourceRefs': ['session:task-1'],
                       'licenseMetadata': 'internal', 'authoredAt': '2026-10-03'},
        'procedure': {'requiredLocalChecks': ['server responds on the selected route'],
                      'adaptiveBranches': ['vite or next'], 'stopConditions': ['no route granted']},
        'acceptance': {'outcomes': ['preview loads for the user'],
                       'evidenceKinds': ['screenshot'],
                       'forbiddenEffects': ['public exposure without grant']},
        'context': {'summary': 'Check the app through the real access route.',
                    'fullTextRef': 'artifact:skill-body@1', 'contextCostEstimate': 1200},
        'handoff': {'persistedRefs': ['artifact:preview-binding@1'],
                    'revalidateConditions': ['route or machine changed']},
        'reviewRefs': ['review-1'], 'testedPlatforms': ['linux'], 'contractVersion': 1,
    }
    value.update(updates)
    return value


def spec(**updates):
    return SkillSpec.parse(payload(**updates))


def environment(**updates):
    value = {'commands': ['npm'], 'packages': ['pytest'], 'environmentRefs': ['env:node'],
             'contextEpoch': 4}
    value.update(updates)
    return value


def arguments(**updates):
    value = {'tools': ['run_command'], 'capabilities': ['process.jobs'], 'roles': ['build'],
             'environment': environment(), 'context_epoch': 4}
    value.update(updates)
    return value


def error(code, call):
    with pytest.raises(ContractError) as exc:
        call()
    assert exc.value.code == code


@pytest.fixture
def store(tmp_path):
    session_store = SessionStore(tmp_path / 'sessions.db')
    yield session_store
    session_store.close()


@pytest.fixture
def registry(store):
    return SkillRegistry(store)


def proposed(registry, **updates):
    # Invocation ID tách theo (id, version) để mỗi lần đề xuất có thể lặp lại độc lập.
    invocation = f"inv-{updates.get('id', 'boxfox-web-preview')}-{updates.get('version', 1)}"
    return registry.propose(spec(**updates), 'owner-1', invocation)


def approved(registry, skill_id, version):
    return registry.review(skill_id, version, 'reviewer-1', 'approve', notes='checked')


def enabled(registry, **updates):
    view = proposed(registry, **updates)
    approved(registry, view['skillId'], view['version'])
    return registry.enable(view['skillId'], view['version'], view['revision'])


# --- SkillSpec.parse -------------------------------------------------------

def test_parse_round_trip_hash_and_immutable_snapshot():
    raw = payload()
    parsed = SkillSpec.parse(raw)
    assert parsed.skill_id == 'boxfox-web-preview' and parsed.version == 1
    assert parsed.payload['schemaVersion'] == SKILL_SCHEMA
    assert parsed.skill_hash == digest(parsed.payload) == digest(json.loads(parsed.payload_json))
    raw['goal'] = 'changed by caller'
    assert parsed.payload['goal'] == payload()['goal']
    view = parsed.payload
    view['goal'] = 'changed by reader'
    assert parsed.payload['goal'] == payload()['goal']
    with pytest.raises(FrozenInstanceError):
        parsed.payload_json = '{}'
    with pytest.raises(TypeError):
        SkillSpec()


def test_parse_defaults_builtin_provenance_and_optional_sections():
    raw = payload()
    del raw['provenance']
    del raw['handoff']
    del raw['reviewRefs']
    del raw['testedPlatforms']
    del raw['contractVersion']
    parsed = SkillSpec.parse(raw)
    assert parsed.payload['provenance'] == {'origin': 'builtin'}
    assert parsed.payload['handoff'] == {'persistedRefs': [], 'revalidateConditions': []}
    assert parsed.payload['reviewRefs'] == [] and parsed.payload['testedPlatforms'] == []
    assert parsed.payload['contractVersion'] == 1


@pytest.mark.parametrize('updates', [
    {'goal': None},
    {'id': 7},
    {'trigger': {'intents': ['implementation'], 'artifactKinds': ['patch']}},
])
def test_parse_rejects_invalid_and_incomplete_nested_values(updates):
    error('SKILL_SPEC_INVALID', lambda: SkillSpec.parse(payload(**updates)))


def test_parse_rejects_missing_required_fields():
    for field in ('id', 'version', 'title', 'goal', 'trigger', 'applicability', 'requirements',
                  'procedure', 'acceptance', 'context'):
        raw = payload()
        del raw[field]
        error('SKILL_SPEC_INVALID', lambda raw=raw: SkillSpec.parse(raw))


def test_parse_rejects_unknown_top_level_fields():
    error('SKILL_SPEC_INVALID', lambda: SkillSpec.parse(payload(schema='boxfox-skill-spec/2')))


def test_parse_rejects_unknown_nested_field():
    raw = payload(trigger={'intents': ['implementation'], 'artifactKinds': ['patch'],
                           'actionClasses': [], 'extra': []})
    error('SKILL_SPEC_INVALID', lambda: SkillSpec.parse(raw))


def test_parse_rejects_unsupported_schema():
    error('SKILL_SCHEMA_UNSUPPORTED', lambda: SkillSpec.parse(payload(schemaVersion='other/9')))


def test_parse_rejects_non_mapping_payload():
    error('SKILL_SPEC_INVALID', lambda: SkillSpec.parse(['not', 'a', 'mapping']))


@pytest.mark.parametrize('updates', [
    {'goal': 'g' * 4001},
    {'title': 't' * 401},
    {'context': {'fullTextRef': 'artifact:body@1', 'summary': 's' * 401}},
    {'procedure': {'requiredLocalChecks': ['x' * 2001], 'adaptiveBranches': [],
                   'stopConditions': []}},
    {'requirements': {'tools': [f'tool-{i}' for i in range(101)], 'capabilities': [],
                      'commands': [], 'environmentRefs': [], 'packages': []}},
    {'trigger': {'intents': [f'intent-{i}' for i in range(101)], 'artifactKinds': [],
                 'actionClasses': []}},
    {'reviewRefs': [f'review-{i}' for i in range(101)]},
])
def test_parse_rejects_out_of_bounds_values(updates):
    error('SKILL_SPEC_INVALID', lambda: SkillSpec.parse(payload(**updates)))


def test_parse_accepts_values_at_the_bounds():
    parsed = SkillSpec.parse(payload(
        goal='g' * 4000, title='t' * 400,
        context={'fullTextRef': 'artifact:body@1', 'summary': 's' * 400},
        procedure={'requiredLocalChecks': ['x' * 2000], 'adaptiveBranches': [], 'stopConditions': []},
        requirements={'tools': [f'tool-{i}' for i in range(100)], 'capabilities': [],
                      'commands': [], 'environmentRefs': [], 'packages': []}))
    assert parsed.payload['goal'] == 'g' * 4000


@pytest.mark.parametrize('updates', [
    {'trigger': {'intents': ['a', 'a'], 'artifactKinds': [], 'actionClasses': []}},
    {'applicability': {'roles': ['build', 'build'], 'environments': [], 'exclusions': []}},
    {'requirements': {'tools': [], 'capabilities': [], 'commands': [],
                      'environmentRefs': [], 'packages': ['pytest', 'pytest']}},
    {'procedure': {'requiredLocalChecks': ['same', 'same'], 'adaptiveBranches': [],
                   'stopConditions': []}},
    {'reviewRefs': ['review-1', 'review-1']},
])
def test_parse_rejects_duplicate_entries(updates):
    error('SKILL_SPEC_INVALID', lambda: SkillSpec.parse(payload(**updates)))


@pytest.mark.parametrize('updates', [
    {'id': ''},
    {'id': '../etc/passwd'},
    {'id': 'x' * 121},
    {'version': 0},
    {'version': -1},
    {'version': True},
    {'version': '1'},
    {'contractVersion': 0},
])
def test_parse_rejects_invalid_identifiers_and_versions(updates):
    error('SKILL_SPEC_INVALID', lambda: SkillSpec.parse(payload(**updates)))


@pytest.mark.parametrize('provenance', [
    {'origin': 'adapted'},
    {'origin': 'adapted', 'sourceRefs': ['session:task-1']},
    {'origin': 'external', 'sourceRefs': ['session:task-1'], 'licenseMetadata': 'internal'},
    {'origin': 'builtin', 'sourceRefs': ['inline prose with spaces']},
    {'origin': 'builtin', 'licenseMetadata': ''},
])
def test_parse_rejects_invalid_provenance(provenance):
    error('SKILL_SPEC_INVALID', lambda: SkillSpec.parse(payload(provenance=provenance)))


def test_parse_accepts_non_builtin_provenance_with_refs_and_license():
    parsed = SkillSpec.parse(payload(provenance={
        'origin': 'adapted', 'sourceRefs': ['artifact:reference@3'],
        'sourceVersion': 'v3', 'licenseMetadata': 'internal-only'}))
    assert parsed.payload['provenance']['origin'] == 'adapted'
    assert parsed.payload['provenance']['sourceRefs'] == ['artifact:reference@3']


@pytest.mark.parametrize('context', [
    {'summary': 'no ref'},
    {'fullTextRef': 'plain text without a scheme'},
    {'fullTextRef': 'prose that looks like a prompt with spaces'},
    {'fullTextRef': ''},
])
def test_parse_requires_a_bounded_full_text_ref(context):
    error('SKILL_SPEC_INVALID', lambda: SkillSpec.parse(payload(context=context)))


@pytest.mark.parametrize('cost', [0, 1, 10_000])
def test_parse_keeps_known_context_cost(cost):
    parsed = SkillSpec.parse(payload(context={'fullTextRef': 'artifact:body@1',
                                              'contextCostEstimate': cost}))
    assert parsed.payload['context']['contextCostEstimate'] == cost


@pytest.mark.parametrize('cost', [-1, True, '10', 1.5])
def test_parse_rejects_invalid_context_cost(cost):
    error('SKILL_SPEC_INVALID', lambda: SkillSpec.parse(
        payload(context={'fullTextRef': 'artifact:body@1', 'contextCostEstimate': cost})))


def test_parse_rejects_non_ref_handoff_persisted_refs():
    error('SKILL_SPEC_INVALID', lambda: SkillSpec.parse(
        payload(handoff={'persistedRefs': ['not a ref'], 'revalidateConditions': []})))


# --- readiness -------------------------------------------------------------

def test_readiness_ready_when_every_dependency_is_present():
    result = readiness(spec(), **arguments())
    assert result.state == 'ready' and result.reasons == ()


@pytest.mark.parametrize('updates', [
    {'tools': []},
    {'capabilities': []},
    {'environment': environment(commands=[])},
    {'environment': environment(environmentRefs=[])},
    {'environment': environment(packages=[])},
])
def test_readiness_blocked_per_missing_dependency(updates):
    result = readiness(spec(), **arguments(**updates))
    assert result.state == 'blocked'
    assert any(reason.startswith('missing ') for reason in result.reasons)


@pytest.mark.parametrize('spec_updates,arg_updates', [
    ({}, {'environment': environment(contextEpoch=None), 'context_epoch': None}),
    ({'context': {'fullTextRef': 'artifact:body@1', 'contextCostEstimate': 10}}, {}),
    ({'context': {'fullTextRef': 'artifact:body@1', 'summary': 's'}}, {}),
])
def test_readiness_degraded_when_context_is_incomplete(spec_updates, arg_updates):
    result = readiness(spec(**spec_updates), **arguments(**arg_updates))
    assert result.state == 'degraded' and result.reasons


def test_readiness_blocked_without_an_applicable_role():
    result = readiness(spec(), **arguments(roles=['review']))
    assert result.state == 'blocked'
    assert any(reason.startswith('no applicable role') for reason in result.reasons)


def test_readiness_uses_the_environment_epoch_when_none_is_passed():
    result = readiness(spec(), tools=['run_command'], capabilities=['process.jobs'],
                       roles=['build'], environment=environment(contextEpoch=7))
    assert result.state == 'ready'


def test_readiness_reasons_never_invent_tools_or_permissions():
    allowed = re.compile(
        r"^(missing (tool|capability|command|environment|package) '[^']+'"
        r"|no applicable role: skill targets [A-Za-z0-9_, -]+"
        r'|context epoch unknown: revalidate before use'
        r'|context summary missing: load the full text behind fullTextRef'
        r'|context cost estimate unknown)$')
    result = readiness(spec(), tools=[], capabilities=[], roles=[], environment={},
                       context_epoch=None)
    assert result.state == 'blocked'
    assert all(allowed.match(reason) for reason in result.reasons)
    forbidden = ('install', 'create', 'bypass', 'substitute', 'replacement', 'grant', 'enable')
    assert not any(word in reason.lower() for reason in result.reasons for word in forbidden)


def test_readiness_module_does_not_import_runtime_or_touch_files():
    source = Path(skill_spec.__file__).read_text(encoding='utf-8')
    assert 'from .runtime' not in source
    assert 'from agentbox.agent_core.runtime' not in source
    assert 'subprocess' not in source
    assert 'importlib' not in source
    assert 'open(' not in source
    assert 'Path(' not in source
    assert 'pip install' not in source


@pytest.mark.parametrize('updates', [
    {'tools': 'run_command'},
    {'capabilities': [None]},
    {'roles': None},
    {'environment': ['npm']},
    {'context_epoch': 0},
    {'context_epoch': True},
])
def test_readiness_rejects_invalid_inputs(updates):
    error('SKILL_SPEC_INVALID', lambda: readiness(spec(), **arguments(**updates)))


def test_readiness_result_is_immutable_and_self_checking():
    result = readiness(spec(), **arguments())
    with pytest.raises(FrozenInstanceError):
        result.state = 'blocked'
    with pytest.raises(ValueError):
        SkillReadiness(state='broken')
    with pytest.raises(ValueError):
        SkillReadiness(state='degraded')
    with pytest.raises(ValueError):
        SkillReadiness(state='ready', reasons=('why',))


# --- revalidate ------------------------------------------------------------

def test_revalidate_true_when_all_inputs_are_unchanged():
    previous = {'roleRevision': 3, 'toolRevision': 5, 'adapterRevision': 2,
                'sourceVersion': 'v3', 'contextEpoch': 4}
    assert revalidate(spec(), previous, role_revision=3, tool_revision=5, adapter_revision=2,
                      source_version='v3', context_epoch=4) == (True, ())


@pytest.mark.parametrize('field,previous,current', [
    ('roleRevision', 3, 4),
    ('toolRevision', 5, 6),
    ('adapterRevision', 2, 3),
    ('sourceVersion', 'v3', 'v4'),
    ('contextEpoch', 4, 5),
])
def test_revalidate_false_per_changed_dimension(field, previous, current):
    kwargs = {_KWARG[field]: current}
    ok, reasons = revalidate(spec(), {field: previous}, **kwargs)
    assert ok is False
    assert reasons and field in reasons[0]


_KWARG = {'roleRevision': 'role_revision', 'toolRevision': 'tool_revision',
          'adapterRevision': 'adapter_revision', 'sourceVersion': 'source_version',
          'contextEpoch': 'context_epoch'}


def test_revalidate_false_when_the_previous_value_was_not_recorded():
    ok, reasons = revalidate(spec(), {'roleRevision': 3}, tool_revision=5)
    assert ok is False and 'toolRevision' in reasons[0]


def test_revalidate_skips_unsupplied_dimensions():
    ok, reasons = revalidate(spec(), {'roleRevision': 3}, role_revision=3)
    assert ok is True and reasons == ()


def test_revalidate_rejects_unknown_previous_fields_and_bad_inputs():
    error('SKILL_SPEC_INVALID', lambda: revalidate(spec(), {'tool_revison': 5}, tool_revision=5))
    error('SKILL_SPEC_INVALID', lambda: revalidate(spec(), {'roleRevision': 0}, role_revision=0))
    error('SKILL_SPEC_INVALID', lambda: revalidate(spec(), ['not', 'a', 'mapping']))


# --- registry --------------------------------------------------------------

def test_registry_creates_required_tables_and_columns(registry):
    required = {
        'harness_skills': ('skill_id', 'version', 'schema_version', 'revision', 'state',
                           'spec_hash', 'spec_json', 'provenance_json', 'review_json',
                           'created_at', 'updated_at'),
        'harness_skill_reviews': ('review_id', 'skill_id', 'version', 'reviewer_id', 'verdict',
                                  'notes', 'created_at'),
        'harness_skill_pins': ('pin_id', 'skill_id', 'version', 'attempt_id', 'session_id',
                               'created_at', 'updated_at', 'replaced_version'),
        'harness_skill_invocations': ('scope', 'invocation_id', 'operation', 'request_hash',
                                      'result_json', 'created_at'),
    }
    for table, columns in required.items():
        actual = {row['name'] for row in registry.db.execute(f'PRAGMA table_info({table})')}
        assert set(columns) <= actual, table
    shapes = {tuple(row['name'] for row in registry.db.execute(f'PRAGMA index_info({index["name"]})'))
              for index in registry.db.execute('PRAGMA index_list(harness_skill_pins)')
              if index['unique']}
    assert ('skill_id', 'attempt_id') in shapes
    assert ('skill_id', 'version', 'attempt_id') not in shapes


@pytest.mark.parametrize('ddl', [
    'CREATE TABLE harness_skills (skill_id TEXT, version INTEGER)',
    'CREATE TABLE harness_skill_reviews (review_id TEXT PRIMARY KEY)',
    'CREATE TABLE harness_skill_pins (pin_id TEXT PRIMARY KEY)',
    'CREATE TABLE harness_skill_invocations (invocation_id TEXT PRIMARY KEY)',
])
def test_registry_missing_column_fails_closed(tmp_path, ddl):
    session_store = SessionStore(tmp_path / 'sessions.db')
    try:
        session_store.db.executescript(ddl)
        with pytest.raises(ContractError) as exc:
            SkillRegistry(session_store)
        assert exc.value.code == 'SKILL_SCHEMA_UNSUPPORTED'
    finally:
        session_store.close()


def test_registry_adds_state_reason_to_a_legacy_table(tmp_path):
    session_store = SessionStore(tmp_path / 'sessions.db')
    try:
        session_store.db.executescript('''
            CREATE TABLE harness_skills (
                skill_id TEXT NOT NULL, version INTEGER NOT NULL, revision INTEGER NOT NULL,
                state TEXT NOT NULL, spec_hash TEXT NOT NULL, spec_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL, review_json TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(skill_id, version));''')
        SkillRegistry(session_store)
        columns = {row['name'] for row in session_store.db.execute('PRAGMA table_info(harness_skills)')}
        assert 'state_reason' in columns
    finally:
        session_store.close()


def test_registry_upgrades_a_pre_schema_version_table_in_place(tmp_path):
    session_store = SessionStore(tmp_path / 'sessions.db')
    try:
        session_store.db.executescript('''
            CREATE TABLE harness_skills (
                skill_id TEXT NOT NULL, version INTEGER NOT NULL, revision INTEGER NOT NULL,
                state TEXT NOT NULL, spec_hash TEXT NOT NULL, spec_json TEXT NOT NULL,
                provenance_json TEXT NOT NULL, review_json TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(skill_id, version));''')
        session_store.db.execute(
            'INSERT INTO harness_skills VALUES(?,?,?,?,?,?,?,?,?,?)',
            ('legacy-skill', 1, 1, 'draft', 'hash',
             '{"id":"legacy-skill","title":"Legacy skill"}', '{}', '{}', 1.0, 1.0))
        registry = SkillRegistry(session_store)
        row = session_store.db.execute('SELECT schema_version FROM harness_skills').fetchone()
        assert row['schema_version'] == 1
        view = registry.get('legacy-skill', 1)
        assert view['schemaVersion'] == 1 and view['title'] == 'Legacy skill'
    finally:
        session_store.close()


def test_legacy_pin_table_upgrades_to_one_pin_per_attempt(tmp_path):
    session_store = SessionStore(tmp_path / 'sessions.db')
    try:
        session_store.db.executescript('''
            CREATE TABLE harness_skill_pins (
                pin_id TEXT PRIMARY KEY, skill_id TEXT NOT NULL, version INTEGER NOT NULL,
                attempt_id TEXT NOT NULL, session_id TEXT NOT NULL, created_at REAL NOT NULL,
                UNIQUE(skill_id, version, attempt_id));''')
        session_store.db.executemany(
            'INSERT INTO harness_skill_pins VALUES(?,?,?,?,?,?)',
            [('pin-a', 'boxfox-web-preview', 1, 'attempt-1', 'session-1', 1.0),
             ('pin-b', 'boxfox-web-preview', 2, 'attempt-1', 'session-1', 2.0),
             ('pin-c', 'skill-b', 1, 'attempt-1', 'session-1', 3.0)])
        registry = SkillRegistry(session_store)
        pins = registry.pins(attempt_id='attempt-1')
        assert [(pin['skillId'], pin['version']) for pin in pins] == [
            ('boxfox-web-preview', 2), ('skill-b', 1)]
        newest = next(pin for pin in pins if pin['skillId'] == 'boxfox-web-preview')
        assert newest['pinId'] == 'pin-b' and newest['replacedVersion'] == 1
        assert newest['createdAt'] == 2.0 and newest['updatedAt'] == 2.0
        shapes = {tuple(row['name'] for row in
                        session_store.db.execute(f'PRAGMA index_info({index["name"]})'))
                  for index in session_store.db.execute('PRAGMA index_list(harness_skill_pins)')
                  if index['unique']}
        assert ('skill_id', 'attempt_id') in shapes
        assert ('skill_id', 'version', 'attempt_id') not in shapes
    finally:
        session_store.close()


def test_unknown_record_schema_version_fails_closed(registry):
    proposed(registry)
    registry.db.execute('UPDATE harness_skills SET schema_version=2')
    error('SKILL_SCHEMA_UNSUPPORTED', lambda: registry.get('boxfox-web-preview', 1))
    error('SKILL_SCHEMA_UNSUPPORTED', lambda: registry.list())
    error('SKILL_SCHEMA_UNSUPPORTED', lambda: registry.enable('boxfox-web-preview', 1, 1))


def test_corrupt_record_json_fails_closed(registry):
    proposed(registry)
    registry.db.execute("UPDATE harness_skills SET spec_json='{'")
    error('SKILL_RECORD_CORRUPT', lambda: registry.get('boxfox-web-preview', 1))
    error('SKILL_RECORD_CORRUPT', lambda: registry.list())
    registry.db.execute("UPDATE harness_skills SET spec_json='[]'")
    error('SKILL_RECORD_CORRUPT', lambda: registry.get('boxfox-web-preview', 1))
    registry.db.execute("UPDATE harness_skills SET spec_json='{}', review_json='{'")
    error('SKILL_RECORD_CORRUPT', lambda: registry.get('boxfox-web-preview', 1))
    error('SKILL_RECORD_CORRUPT',
          lambda: registry.enable('boxfox-web-preview', 1, 1))


def test_corrupt_invocation_receipt_fails_closed(registry):
    proposed(registry)
    registry.db.execute("UPDATE harness_skill_invocations SET result_json='{'")
    error('SKILL_RECORD_CORRUPT',
          lambda: registry.propose(spec(), 'owner-1', 'inv-boxfox-web-preview-1'))


def test_propose_writes_a_draft_row_without_enabling(registry):
    view = registry.propose(spec(), 'owner-1', 'inv-propose')
    assert view['state'] == 'draft' and view['revision'] == 1
    assert view['spec']['id'] == 'boxfox-web-preview' and view['review'] is None
    assert view['specHash'] == digest(view['spec'])
    assert registry.get('boxfox-web-preview', 1)['state'] == 'draft'
    assert registry.db.execute('SELECT COUNT(*) FROM harness_skill_reviews').fetchone()[0] == 0


def test_propose_is_idempotent_by_invocation(registry):
    first = registry.propose(spec(), 'owner-1', 'inv-propose')
    second = registry.propose(spec(), 'owner-1', 'inv-propose')
    assert second == first
    assert registry.db.execute('SELECT COUNT(*) FROM harness_skills').fetchone()[0] == 1
    assert registry.db.execute('SELECT COUNT(*) FROM harness_skill_invocations').fetchone()[0] == 1


def test_propose_rejects_invocation_reuse_with_a_different_spec(registry):
    registry.propose(spec(), 'owner-1', 'inv-propose')
    error('SKILL_INVOCATION_CONFLICT',
          lambda: registry.propose(spec(goal='A different goal.'), 'owner-1', 'inv-propose'))
    assert registry.db.execute('SELECT COUNT(*) FROM harness_skills').fetchone()[0] == 1


def test_propose_rejects_the_same_version_with_different_content(registry):
    registry.propose(spec(), 'owner-1', 'inv-1')
    error('SKILL_VERSION_CONFLICT',
          lambda: registry.propose(spec(goal='A different goal.'), 'owner-2', 'inv-2'))


@pytest.mark.parametrize('call', [
    lambda registry: registry.propose(spec(), '../owner', 'inv-1'),
    lambda registry: registry.propose(spec(), 'owner-1', 'inv 1'),
    lambda registry: registry.propose(spec(), 'owner-1', ''),
])
def test_propose_rejects_invalid_identifiers(registry, call):
    error('SKILL_SPEC_INVALID', lambda: call(registry))
    assert registry.db.execute('SELECT COUNT(*) FROM harness_skills').fetchone()[0] == 0


def test_enable_and_disable_replay_by_invocation(registry):
    view = registry.propose(spec(), 'owner-1', 'inv-1')
    approved(registry, 'boxfox-web-preview', 1)
    first = registry.enable('boxfox-web-preview', 1, view['revision'], invocation_id='inv-enable')
    second = registry.enable('boxfox-web-preview', 1, view['revision'], invocation_id='inv-enable')
    assert second == first and second['revision'] == view['revision'] + 1
    disabled = registry.disable('boxfox-web-preview', 1, 'route revoked', invocation_id='inv-disable')
    again = registry.disable('boxfox-web-preview', 1, 'route revoked', invocation_id='inv-disable')
    assert again == disabled and again['revision'] == disabled['revision']


def test_review_records_the_latest_verdict_and_requires_a_known_version(registry):
    error('SKILL_UNKNOWN', lambda: registry.review('missing-skill', 1, 'reviewer-1', 'approve'))
    registry.propose(spec(), 'owner-1', 'inv-1')
    view = registry.review('boxfox-web-preview', 1, 'reviewer-1', 'approve', notes='checked')
    assert view['verdict'] == 'approve' and view['notes'] == 'checked'
    assert registry.get('boxfox-web-preview', 1)['review']['reviewId'] == view['reviewId']
    error('SKILL_SPEC_INVALID',
          lambda: registry.review('boxfox-web-preview', 1, 'reviewer-1', 'maybe'))


def test_enable_requires_an_approved_review(registry):
    view = registry.propose(spec(), 'owner-1', 'inv-1')
    error('SKILL_NOT_REVIEWED', lambda: registry.enable('boxfox-web-preview', 1, view['revision']))
    registry.review('boxfox-web-preview', 1, 'reviewer-1', 'reject', notes='unsafe')
    error('SKILL_NOT_REVIEWED', lambda: registry.enable('boxfox-web-preview', 1, view['revision']))
    assert registry.get('boxfox-web-preview', 1)['state'] == 'draft'


def test_enable_requires_a_matching_revision(registry):
    view = registry.propose(spec(), 'owner-1', 'inv-1')
    approved(registry, 'boxfox-web-preview', 1)
    error('SKILL_REVISION_CONFLICT',
          lambda: registry.enable('boxfox-web-preview', 1, view['revision'] + 1))
    assert registry.get('boxfox-web-preview', 1)['state'] == 'draft'


def test_enable_transitions_draft_and_is_idempotent(registry):
    view = registry.propose(spec(), 'owner-1', 'inv-1')
    approved(registry, 'boxfox-web-preview', 1)
    first = registry.enable('boxfox-web-preview', 1, view['revision'])
    assert first['state'] == 'enabled' and first['revision'] == view['revision'] + 1
    second = registry.enable('boxfox-web-preview', 1, first['revision'])
    assert second['revision'] == first['revision'] and second['state'] == 'enabled'


def test_enable_unknown_skill_is_rejected(registry):
    error('SKILL_UNKNOWN', lambda: registry.enable('missing-skill', 1, 1))


def test_disable_is_idempotent_and_keeps_the_first_reason(registry):
    enabled(registry)
    first = registry.disable('boxfox-web-preview', 1, 'preview route no longer granted')
    assert first['state'] == 'disabled' and first['stateReason'] == 'preview route no longer granted'
    second = registry.disable('boxfox-web-preview', 1, 'a later reason')
    assert second['revision'] == first['revision'] and second['state'] == 'disabled'
    assert second['stateReason'] == 'preview route no longer granted'


def test_disable_unknown_skill_is_rejected(registry):
    error('SKILL_UNKNOWN', lambda: registry.disable('missing-skill', 1, 'no longer wanted'))


def test_pin_requires_an_enabled_version_and_is_idempotent(registry):
    proposed(registry)
    error('SKILL_STATE_CONFLICT',
          lambda: registry.pin('boxfox-web-preview', 1, 'attempt-1', 'session-1'))
    enabled(registry)
    first = registry.pin('boxfox-web-preview', 1, 'attempt-1', 'session-1')
    second = registry.pin('boxfox-web-preview', 1, 'attempt-1', 'session-1')
    assert first == second and first['version'] == 1
    assert len(registry.pins(attempt_id='attempt-1')) == 1
    assert registry.pins(skill_id='boxfox-web-preview')[0]['sessionId'] == 'session-1'


def test_enable_records_a_pin_for_the_active_attempt(registry):
    view = registry.propose(spec(), 'owner-1', 'inv-1')
    approved(registry, 'boxfox-web-preview', 1)
    registry.enable('boxfox-web-preview', 1, view['revision'],
                    attempt_id='attempt-1', session_id='session-1')
    pins = registry.pins(attempt_id='attempt-1')
    assert len(pins) == 1 and pins[0]['version'] == 1
    error('SKILL_SPEC_INVALID',
          lambda: registry.enable('boxfox-web-preview', 1, view['revision'],
                                  attempt_id='attempt-1'))


def test_enable_replaces_the_pin_for_the_same_attempt(registry):
    first = proposed(registry)
    approved(registry, 'boxfox-web-preview', 1)
    registry.enable('boxfox-web-preview', 1, first['revision'],
                    attempt_id='attempt-1', session_id='session-1')
    second = proposed(registry, version=2, goal='An improved preview procedure.')
    approved(registry, 'boxfox-web-preview', 2)
    registry.enable('boxfox-web-preview', 2, second['revision'],
                    attempt_id='attempt-1', session_id='session-1')
    pins = registry.pins(attempt_id='attempt-1')
    assert len(pins) == 1 and pins[0]['version'] == 2
    assert pins[0]['replacedVersion'] == 1
    assert pins[0]['createdAt'] <= pins[0]['updatedAt']
    assert registry.db.execute('SELECT COUNT(*) FROM harness_skill_pins').fetchone()[0] == 1


def test_enable_same_version_twice_keeps_one_pin_without_replacement(registry):
    view = proposed(registry)
    approved(registry, 'boxfox-web-preview', 1)
    first = registry.enable('boxfox-web-preview', 1, view['revision'],
                            attempt_id='attempt-1', session_id='session-1')
    registry.enable('boxfox-web-preview', 1, first['revision'],
                    attempt_id='attempt-1', session_id='session-1')
    pins = registry.pins(attempt_id='attempt-1')
    assert len(pins) == 1 and pins[0]['version'] == 1
    assert pins[0]['replacedVersion'] is None


def test_one_attempt_keeps_one_version_per_skill(registry):
    enabled(registry, version=1)
    enabled(registry, version=2)
    enabled(registry, id='skill-b')
    registry.pin('boxfox-web-preview', 1, 'attempt-1', 'session-1')
    registry.pin('boxfox-web-preview', 2, 'attempt-1', 'session-1')
    registry.pin('skill-b', 1, 'attempt-1', 'session-1')
    pins = registry.pins(attempt_id='attempt-1')
    assert sorted((pin['skillId'], pin['version']) for pin in pins) == [
        ('boxfox-web-preview', 2), ('skill-b', 1)]
    assert registry.pins(skill_id='boxfox-web-preview') == [
        pin for pin in pins if pin['skillId'] == 'boxfox-web-preview']


def test_enable_does_not_mutate_a_pinned_active_attempt_skill(registry):
    enabled(registry)
    registry.pin('boxfox-web-preview', 1, 'attempt-1', 'session-1')
    before = registry.get('boxfox-web-preview', 1)
    second = proposed(registry, version=2, goal='An improved preview procedure.')
    approved(registry, 'boxfox-web-preview', 2)
    registry.enable('boxfox-web-preview', 2, second['revision'])
    after = registry.get('boxfox-web-preview', 1)
    assert after == before and after['state'] == 'enabled'
    assert [pin['version'] for pin in registry.pins(attempt_id='attempt-1')] == [1]
    again = registry.enable('boxfox-web-preview', 1, before['revision'])
    assert again['revision'] == before['revision'] and again['specHash'] == before['specHash']


def test_list_uses_keyset_pagination(registry):
    for index in range(5):
        registry.propose(spec(id=f'skill-{index}'), 'owner-1', f'inv-{index}')
    first = registry.list(limit=2)
    assert [item['skillId'] for item in first['items']] == ['skill-0', 'skill-1']
    assert first['hasMore'] is True and first['nextAfter'] == 'skill-1@1'
    second = registry.list(limit=2, cursor=first['nextAfter'])
    assert [item['skillId'] for item in second['items']] == ['skill-2', 'skill-3']
    third = registry.list(limit=2, cursor=second['nextAfter'])
    assert [item['skillId'] for item in third['items']] == ['skill-4']
    assert third['hasMore'] is False and third['nextAfter'] == 'skill-4@1'


def test_list_pages_across_versions_of_the_same_skill(registry):
    for version in (1, 2):
        registry.propose(spec(version=version), 'owner-1', f'inv-a-{version}')
    registry.propose(spec(id='skill-b'), 'owner-1', 'inv-b-1')
    first = registry.list(limit=2)
    assert [(item['skillId'], item['version']) for item in first['items']] == [
        ('boxfox-web-preview', 1), ('boxfox-web-preview', 2)]
    assert first['nextAfter'] == 'boxfox-web-preview@2'
    second = registry.list(limit=2, cursor=first['nextAfter'])
    assert [(item['skillId'], item['version']) for item in second['items']] == [('skill-b', 1)]
    assert second['hasMore'] is False


def test_list_filters_by_state_and_rejects_bad_arguments(registry):
    enabled(registry)
    registry.propose(spec(id='skill-draft'), 'owner-1', 'inv-draft')
    listing = registry.list(state='enabled')
    assert [item['skillId'] for item in listing['items']] == ['boxfox-web-preview']
    error('SKILL_SPEC_INVALID', lambda: registry.list(state='unknown'))
    error('SKILL_SPEC_INVALID', lambda: registry.list(limit=0))
    error('SKILL_SPEC_INVALID', lambda: registry.list(limit=101))
    error('SKILL_SPEC_INVALID', lambda: registry.list(cursor='not-a-cursor'))


def test_get_prefers_the_highest_enabled_version(registry):
    enabled(registry)
    proposed(registry, version=2)
    assert registry.get('boxfox-web-preview')['version'] == 1
    approved(registry, 'boxfox-web-preview', 2)
    registry.enable('boxfox-web-preview', 2, registry.get('boxfox-web-preview', 2)['revision'])
    assert registry.get('boxfox-web-preview')['version'] == 2
    error('SKILL_UNKNOWN', lambda: registry.get('missing-skill'))
    error('SKILL_UNKNOWN', lambda: registry.get('boxfox-web-preview', 9))
