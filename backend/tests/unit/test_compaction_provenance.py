"""Summary state remains useful without recursively importing the harness framing."""
from agentbox.agent_core.compression import COMPACTION_BANNER, summarizer_material


def test_legacy_summary_keeps_outstanding_work_but_removes_recursive_frames():
    material = summarizer_material([{
        'role': 'assistant',
        'content': COMPACTION_BANNER + '\n' + COMPACTION_BANNER + '\nOutstanding work: fix failing test',
    }])
    assert material == [{'role': 'assistant', 'content': 'Outstanding work: fix failing test'}]


def test_identical_summary_reference_is_included_once_without_dropping_other_state():
    old = {'role': 'assistant', 'origin': 'synthetic_handoff', 'summaryGeneration': 3,
           'sourceRanges': [{'checkpointId': 7}],
           'content': COMPACTION_BANNER + '\nGoal: preserve the owner request'}
    other = {**old, 'content': COMPACTION_BANNER + '\nEvidence: test failed'}
    material = summarizer_material([old, old, other])
    assert len(material) == 2
    assert material[0]['content'] == 'Goal: preserve the owner request'
    assert material[1]['content'] == 'Evidence: test failed'


def test_same_text_with_different_source_is_not_silently_discarded():
    first = {'role': 'assistant', 'origin': 'synthetic_handoff',
             'sourceRanges': [{'checkpointId': 7}], 'content': 'Evidence: tool interrupted'}
    second = {**first, 'sourceRanges': [{'checkpointId': 8}]}
    assert len(summarizer_material([first, second])) == 2


def test_user_text_with_banner_is_not_recategorized_as_a_summary():
    text = COMPACTION_BANNER + '\nThis is the actual owner request'
    assert summarizer_material([{'role': 'user', 'content': text}]) == [
        {'role': 'user', 'content': text}]
