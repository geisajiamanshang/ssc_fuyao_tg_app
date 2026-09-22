import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from approval_queue import select_pending
from parsers import parse_kv_fields, get_field


class MemoryStore:
    """最小可用的状态存储替身，行为对齐 state_store.StateStore 的读写接口。"""

    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key):
        return self.data.get(key)

    def all(self):
        return self.data

    def set(self, key, value):
        self.data[key] = value

    def update(self, key, **values):
        self.data[key].update(values)


def build_env(**overrides):
    """只抽取待测函数本身，其余依赖通过命名空间注入，不连真实Telegram。"""
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'queue_group_message', 'on_ssc_send_approval',
                                'queue_pre_onboarding_registration'}]
    for node in functions:
        node.decorator_list = []
    env = dict(
        select_pending=select_pending, parse_kv_fields=parse_kv_fields, get_field=get_field,
        get_leader_tags=lambda *a, **kw: ['leader'],
        forward_onboarding_to_hrgs=AsyncMock(),
        asyncio=asyncio, log=logging.getLogger('test'),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
    return env


ONBOARDING_TEXT = (
    '运营中心【入职信息确认】\n'
    '候选人编码：LYSNZ000060\n'
    '候选人姓名：Nancy\n'
    '性别：女\n'
    '入职编制组织：运营中心\n'
    '入职部门：ACFan特战队-品牌组\n'
    '入职日期：2026-10-08（四）\n'
    '候选人联系方式：TG-@LemonQ69'
)


async def _drain_background_tasks():
    """等待 asyncio.create_task 调度的后续任务（预入职登记入队）跑完。"""
    await asyncio.sleep(0)
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        await asyncio.gather(*pending)


class PreOnboardingTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.me = NS(id=9, username='ffuuyao')
        self.sent = []

        async def send_message(destination, text, **kwargs):
            self.sent.append((destination, text))
            return NS(id=300 + len(self.sent))

        self.send_message = send_message
        self.state = MemoryStore({'Nancy': {'stage': 'waiting_ssc_onboarding'}})
        self.outbox = MemoryStore({
            '100': {
                'draft_id': 100, 'destination': -1, 'reply_to': None,
                'candidate': 'Nancy', 'expected_stage': 'waiting_ssc_onboarding',
                'updates': {'stage': 'done'}, 'id_field': None, 'kind': 'onboarding',
                'status': 'pending', 'review_chat_id': 9, 'approval_code': '测试1',
                'delete_draft_after_send': False,
            },
        })
        self.config = NS(
            GROUP_LEADERSHIP=-1, GROUP_PRE_ONBOARDING=-2,
            ALLOWED_DESTINATION_IDS={-1, -2},
            OFFER_APPROVAL_CODE='测试1', PRE_ONBOARDING_APPROVAL_CODE='测试11',
            APPROVAL_CODES=frozenset({'测试1', '测试2', '测试11'}),
            PRE_ONBOARDING_FORWARD_ENABLED=True,
            ENVIRONMENT='test', EXCLUDED_CHAT_IDS=frozenset(),
        )
        self.client = NS(
            get_me=AsyncMock(return_value=self.me),
            send_message=self.send_message,
            get_messages=AsyncMock(return_value=NS(id=100, raw_text=ONBOARDING_TEXT, media=None)),
            delete_messages=AsyncMock(),
        )
        self.env = build_env(
            client=self.client, state=self.state, outbox=self.outbox,
            ssc_send_lock=asyncio.Lock(), get_ssc_reviewer=AsyncMock(return_value=self.me),
            config=self.config,
        )

    async def _approve(self, code, approval_msg_id):
        event = NS(chat_id=9, raw_text=code, is_private=True, sender_id=9,
                   message=NS(id=approval_msg_id, reply_to_msg_id=None))
        await self.env['on_ssc_send_approval'](event)
        await _drain_background_tasks()

    async def test_onboarding_send_enqueues_pre_onboarding_draft(self):
        # SSC放行入职确认本身（测试1）后，应自动再挂一条待"测试11"放行的
        # 预入职登记群草稿，而不是直接发送。
        await self._approve('测试1', 1000)
        self.assertEqual(self.state.data['Nancy']['stage'], 'done')
        pre_items = [r for r in self.outbox.data.values() if r['kind'] == 'pre_onboarding']
        self.assertEqual(len(pre_items), 1)
        item = pre_items[0]
        self.assertEqual(item['destination'], -2)
        self.assertEqual(item['approval_code'], '测试11')
        self.assertEqual(item['status'], 'pending')
        self.assertEqual(item['expected_stage'], 'done')
        # 草稿实际发到了SSC收藏夹（reviewer=9），不是直接发到预入职登记群。
        self.assertEqual({dest for dest, _ in self.sent}, {-1, 9})
        draft_text = next(text for dest, text in self.sent if dest == 9)
        self.assertIn('候选人姓名：Nancy', draft_text)

    async def test_full_approval_forwards_to_pre_onboarding_group(self):
        # 第二次审批码"测试11"放行后，草稿才真正发送到预入职登记群。
        await self._approve('测试1', 1000)
        await self._approve('测试11', 2000)
        self.assertEqual({dest for dest, _ in self.sent}, {-1, 9, -2})
        final_text = next(text for dest, text in self.sent if dest == -2)
        self.assertIn('候选人姓名：Nancy', final_text)
        pre_items = [r for r in self.outbox.data.values() if r['kind'] == 'pre_onboarding']
        self.assertEqual(pre_items[0]['status'], 'sent')

    async def test_disabled_until_destination_group_is_configured(self):
        # 预入职登记群ID尚未配置时（PRE_ONBOARDING_FORWARD_ENABLED=False），
        # 入职确认照常发送，但不会尝试挂预入职登记草稿，也不报错。
        self.config.PRE_ONBOARDING_FORWARD_ENABLED = False
        await self._approve('测试1', 1000)
        self.assertEqual(self.state.data['Nancy']['stage'], 'done')
        pre_items = [r for r in self.outbox.data.values() if r['kind'] == 'pre_onboarding']
        self.assertEqual(pre_items, [])
        self.assertEqual({dest for dest, _ in self.sent}, {-1})

    async def test_wrong_approval_code_does_not_forward(self):
        # 只有专属的"测试11"才能放行到预入职登记群；用错审批码（如测试2）
        # 不应该误伤——继续留在待审批状态。
        await self._approve('测试1', 1000)
        await self._approve('测试2', 2000)
        self.assertEqual({dest for dest, _ in self.sent}, {-1, 9})
        pre_items = [r for r in self.outbox.data.values() if r['kind'] == 'pre_onboarding']
        self.assertEqual(pre_items[0]['status'], 'pending')


if __name__ == '__main__':
    import unittest
    unittest.main()
