import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from parsers import (mentions_ssc, is_offer_message, parse_kv_fields,
                     get_field, offer_header_org, strip_header_footer)


class MentionTests(TestCase):
    def test_missing_flag_still_accepts_exact_username(self):
        for text in ['@ffuuyao 请审批', '@FFUUYAO', '请@ffuuyao审批']:
            self.assertTrue(mentions_ssc(NS(raw_text=text)))
        for text in ['@ffuuyao_other', '@other', '小A 小B 小C']:
            self.assertFalse(mentions_ssc(NS(raw_text=text)))

    def test_id_mention_and_flag(self):
        self.assertFalse(mentions_ssc(NS(mentioned=True)))
        self.assertTrue(mentions_ssc(NS(entities=[NS(user_id=8853414240)])))
        self.assertFalse(mentions_ssc(NS(entities=[NS(user_id=8)])))


class MemoryStore:
    def __init__(self):
        self.data = {}

    def find_by_field(self, field, value):
        return next(((key, rec) for key, rec in self.data.items()
                     if rec.get(field) == value), (None, None))

    def set(self, key, value):
        self.data[key] = value

    def update(self, key, **values):
        self.data[key].update(values)


class IntakeTests(IsolatedAsyncioTestCase):
    async def test_three_concurrent_offers_create_three_saved_drafts(self):
        # 执行真实处理函数和入队函数，隔离Telegram连接及磁盘副作用。
        source = ast.parse(Path(__file__).with_name('main.py').read_text())
        functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                     and n.name in {'queue_group_message', 'on_hrbp_offer'}]
        for node in functions:
            node.decorator_list = []
        saved = []

        async def send_message(destination, text, **kwargs):
            saved.append((destination, text))
            return NS(id=100 + len(saved))

        me = NS(id=9, username='ffuuyao')
        state, outbox = MemoryStore(), MemoryStore()
        env = dict(globals(), client=NS(get_me=AsyncMock(return_value=me),
                                       send_message=send_message),
                   state=state, outbox=outbox, ssc_send_lock=asyncio.Lock(),
                   get_ssc_reviewer=AsyncMock(return_value=me),
                   log=logging.getLogger('test'),
                   build_offer_confirm_message=lambda org, body: org + '\n' + body,
                   config=NS(GROUP_LEADERSHIP=-1, ALLOWED_DESTINATION_IDS={-1},
                             OFFER_APPROVAL_CODE='测试1', ENVIRONMENT='test'))
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
        events = [NS(message=NS(id=i, mentioned=False, media=None,
                               raw_text=f'【Offer】+附件简历\n候选人姓名：小{name}\n入职编制组织：技术中心\n@ffuuyao 请审批'),
                     chat_id=-2, sender_id=8, get_sender=AsyncMock(return_value=NS(username='bp')))
                  for i, name in enumerate('ABC', 1)]
        await asyncio.gather(*(env['on_hrbp_offer'](event) for event in events))
        self.assertEqual(len(saved), 3)
        self.assertEqual({dest for dest, _ in saved}, {9})
        self.assertEqual({r['candidate'] for r in outbox.data.values()}, {'小A', '小B', '小C'})
        self.assertTrue(all(r['status'] == 'pending' for r in outbox.data.values()))

        await asyncio.gather(*(env['on_hrbp_offer'](event) for event in events))
        self.assertEqual(len(saved), 3)
