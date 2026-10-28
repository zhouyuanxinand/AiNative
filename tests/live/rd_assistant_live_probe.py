"""Explicit live probe using synthetic data; never targets production projects.

Run manually to verify the configured model can propose a real registered action.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from browser_support import APP, browser_options
sys.path[:0] = [str(APP), str(APP / 'src/service')]


def run():
    from src.service.rd_platform.store import RdStore
    from src.service.assistant.conversation import answer_question
    from src.service.assistant.operations import confirm_operation
    with tempfile.TemporaryDirectory(prefix='xiaohang-live-operation-') as folder:
        store = RdStore(Path(folder) / 'synthetic.sqlite3')
        actor = {'user_id': 'synthetic-owner', 'display_name': '合成测试负责人'}
        detail = store.create_project(actor, {'name': '合成连通验证项目', 'customer': '测试', 'product': '测试'}, 'create')
        pid = detail['project']['id']
        message = '新增一条需求，标题是测试需求，内容是这是合成验证文字，来源是测试输入，验收要求是人工核对，状态待澄清。请为我生成新增需求操作草案。'
        answer = asyncio.run(answer_question(store, actor, 'auto', message, [], pid))
        proposal = answer.get('proposal')
        assert answer['source'] == 'model' and proposal, 'The model did not produce a valid operation proposal'
        assert store.detail(pid, actor['user_id'])['requirements'] == []
        receipt = confirm_operation(store, actor, proposal['id'])
        assert len(store.detail(pid, actor['user_id'])['requirements']) == 1
        proof = {'source': answer['source'], 'model': answer['model'], 'resolved_intent': answer.get('intent'),
                 'capability': proposal['action'], 'unconfirmed_business_writes': 0,
                 'explicit_confirmation': receipt['status'], 'synthetic_project_only': True, 'production_writes': 0}
        evidence = APP / 'runtime/xiaohang-live/operation-proof.json'
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps(proof, ensure_ascii=False))


if __name__ == '__main__':
    run()
