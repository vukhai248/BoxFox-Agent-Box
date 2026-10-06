"""Dựng một lead Research THẬT cho những bài kiểm cần vai đã admit.

Bề mặt 7 (`6c8fe6b`) xoá nốt lối thoát legacy: main không còn `delegate_task role=research` với một
`researchId` tự khai trong `config`. Đường còn lại — cũng là đường THẬT của sản phẩm — là lead
Research đã admit. Ở đây mở intake bằng chính cổng công khai của sản phẩm
(`research_job_submit` → `research_job_control resume`) và admit bằng hook của fixture, không phải
consent sống. Lượt của lead KHÔNG chạy: `runtime.start` bị chặn trong lúc resume (đúng cách các bài
kiểm cũ tránh mở lượt model), rồi được trả lại nguyên trạng cho người gọi.
"""
from __future__ import annotations

import asyncio

REQUEST = {'schema': 'boxfox-research-job/1', 'goal': 'Chốt phương án thay thế hệ cũ.',
           'decisionContext': 'Cần một câu trả lời có nguồn trước khi chốt.',
           'questions': ['Phương án nào rẻ hơn?'],
           'constraints': ['Không chi tiêu sống, không ra mạng ngoài fixture.'],
           'inputRefs': [], 'desiredOutput': 'Bản tổng hợp có nguồn.',
           'freshnessRequirement': 'as-of request', 'permissionEnvelopeRef': None,
           'allocationRef': None, 'consentRef': None}


def admit_lead(store, runtime, root, *, invocation='lead-submit'):
    """Trả `(lead, run_id)` của một intake đã admit (binding `running`)."""
    original_start = runtime.start
    runtime.start = lambda *args, **kwargs: asyncio.get_running_loop().create_future()

    async def run():
        receipt = await runtime.dispatch(root, 'research_job_submit',
                                         {'request': REQUEST, 'invocationId': invocation})
        runtime.prepare_research_admission = None
        runtime.research_admission = lambda lead, request: True
        await runtime.dispatch(root, 'research_job_control', {
            'jobId': receipt['researchJobId'], 'expectedRevision': receipt['revision'],
            'invocationId': invocation + '-resume', 'action': 'resume',
            'reason': 'Fixture admission.'})
        return receipt

    try:
        receipt = asyncio.run(run())
    finally:
        runtime.start = original_start
    return store.get(receipt['ownerControllerId']), receipt['researchJobId']
