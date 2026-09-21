import ast
import asyncio
import logging
import unicodedata
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from approval_queue import select_pending
from regularization import (
    department_for_name,
    extract_section_for_names,
    greeting_for_name,
    match_department_group,
    names_from_trigger,
    split_sections,
    today_trigger_matches,
    today_trigger_scope,
)


MONTHLY_TEXT = """【转正信息同步】

————

北斗矩阵：恒睿
部门-小组：AIGC原创部-AIGC原创组
编号：YY1940
花名：比尔
岗位：运营专员
入职日期：2026-07-21
转正日期：2026-09-21
直属上级/BP评估：同意按期转正
试用期职级：P3
转正职级：P3

【转正通知】

————

🆗️祝贺 比尔 @guzhi2099，表现优秀，通过试用期考核评估，于2026-09-21 起正式转正。
愿你在未来的工作中继续保持热忱，持续成长，共创更多价值！

恭喜转正，未来可期！👏👏👏
"""

GROUPED_MESSAGE = """📋 转正提醒 · 2026-09-21

【恒睿】
今日转正：
比尔（YY1940）转正日期：2026-09-21
"""

GROUP_RULES = [
    {"name": "测试-ACFAN", "keywords": ["ACFAN特战队", "ACFAN", "AIGC原创部", "AIGC"],
     "chat_id": -5375721803},
]


class MemoryStore:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value

    def update(self, key, **values):
        self.data.setdefault(key, {}).update(values)

    def all(self):
        return self.data


def base_config(**overrides):
    fields = dict(
        EXCLUDED_CHAT_IDS=frozenset(), ALLOW_MANUAL_TRIGGERS=True,
        REGULARIZATION_TRIGGER_BOT_ID=8416618309,
        REGULARIZATION_TODAY_TRIGGER_KEYWORD='转正提醒-恒睿-今日转正',
        DAILY_REPORT_TIMEZONE='Asia/Shanghai',
        ANNIVERSARY_GROUP_RULES=GROUP_RULES,
        GROUP_REGULARIZATION_SYNC=-5258992607,
        ALLOWED_DESTINATION_IDS={-5375721803, -5258992607},
        REGULARIZATION_TODAY_APPROVAL_CODE='测试4',
        REGULARIZATION_TODAY_SYNC_APPROVAL_CODE='测试4.1',
        OFFER_APPROVAL_CODE='测试1', ENVIRONMENT='test',
    )
    fields.update(overrides)
    return NS(**fields)


def build_env(**overrides):
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'on_regularization_today_trigger', 'get_ssc_reviewer',
                                'queue_group_message'}]
    for node in functions:
        node.decorator_list = []

    sent = []

    async def send_message(destination, text, **kwargs):
        sent.append((destination, text, kwargs.get('file')))
        return NS(id=100 + len(sent))

    me = NS(id=9, username='ffuuyao')
    env = dict(
        department_for_name=department_for_name, greeting_for_name=greeting_for_name,
        extract_section_for_names=extract_section_for_names,
        match_department_group=match_department_group, names_from_trigger=names_from_trigger,
        split_sections=split_sections, today_trigger_matches=today_trigger_matches,
        today_trigger_scope=today_trigger_scope,
        unicodedata=unicodedata, asyncio=asyncio,
        log=logging.getLogger('test'),
        client=NS(get_me=AsyncMock(return_value=me), send_message=send_message),
        outbox=MemoryStore(), state=MemoryStore(), ssc_send_lock=asyncio.Lock(),
        regularization_events=MemoryStore(), regularization_lock=asyncio.Lock(),
        regularization_drive=NS(
            load_month=lambda day: (MONTHLY_TEXT, NS(get=lambda k: 'file-id')),
            find_poster=lambda day, name: f'poster-for-{name}',
        ),
        config=base_config(),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
    env['_sent'] = sent
    return env


class RegularizationTodayHandlerTests(IsolatedAsyncioTestCase):
    async def test_happy_path_sends_poster_and_sync_info_as_two_drafts(self):
        env = build_env()
        event = NS(chat_id=-1, sender_id=8416618309, raw_text=GROUPED_MESSAGE,
                    message=NS(id=1))
        await env['on_regularization_today_trigger'](event)

        # 两条草稿都先进 SSC 收藏夹（reviewer.id=9），不是直接发到目标群；
        # 真正的目标群记录在 outbox 里，等 SSC 回复对应审批码后才会真正转发。
        self.assertEqual(len(env['_sent']), 2)
        for draft_recipient, _text, _file in env['_sent']:
            self.assertEqual(draft_recipient, 9)

        poster_recipient, poster_text, poster_file = env['_sent'][0]
        self.assertTrue(poster_text.startswith('祝贺 比尔 @guzhi2099'))
        self.assertNotIn('🆗️', poster_text)
        self.assertEqual(poster_file, 'poster-for-比尔')

        _sync_recipient, sync_text, sync_file = env['_sent'][1]
        self.assertTrue(sync_text.startswith('【转正信息同步】'))
        self.assertIn('花名：比尔', sync_text)
        self.assertIsNone(sync_file)

        records = list(env['outbox'].all().values())
        poster_record = next(r for r in records if r['approval_code'] == '测试4')
        sync_record = next(r for r in records if r['approval_code'] == '测试4.1')
        self.assertEqual(poster_record['destination'], -5375721803)
        self.assertTrue(poster_record['delete_draft_after_send'])
        self.assertEqual(sync_record['destination'], -5258992607)
        self.assertTrue(sync_record['delete_draft_after_send'])

        record = env['regularization_events'].get('today:-1:1')
        self.assertEqual(record['status'], 'queued')

    async def test_skips_sync_send_when_destination_not_configured(self):
        env = build_env(config=base_config(GROUP_REGULARIZATION_SYNC=None))
        event = NS(chat_id=-1, sender_id=8416618309, raw_text=GROUPED_MESSAGE,
                    message=NS(id=6))
        await env['on_regularization_today_trigger'](event)
        self.assertEqual(len(env['_sent']), 1)

    async def test_ignores_message_without_today_keyword(self):
        env = build_env()
        event = NS(chat_id=-1, sender_id=8416618309, raw_text='普通消息，没有关键字',
                    message=NS(id=2))
        await env['on_regularization_today_trigger'](event)
        self.assertEqual(env['_sent'], [])

    async def test_skips_test_group_when_excluded(self):
        env = build_env(config=base_config(EXCLUDED_CHAT_IDS=frozenset({-1})))
        event = NS(chat_id=-1, sender_id=8416618309, raw_text=GROUPED_MESSAGE,
                    message=NS(id=3))
        result = await env['on_regularization_today_trigger'](event)
        self.assertIsNone(result)
        self.assertEqual(env['_sent'], [])

    async def test_missing_department_match_reports_failure_without_sending(self):
        env = build_env()
        no_dept_text = MONTHLY_TEXT.replace(
            "部门-小组：AIGC原创部-AIGC原创组\n", ""
        )
        env['regularization_drive'] = NS(
            load_month=lambda day: (no_dept_text, NS(get=lambda k: 'file-id')),
            find_poster=lambda day, name: f'poster-for-{name}',
        )
        event = NS(chat_id=-1, sender_id=8416618309, raw_text=GROUPED_MESSAGE,
                    message=NS(id=4))
        await env['on_regularization_today_trigger'](event)
        self.assertEqual(len(env['_sent']), 1)
        destination, text, _ = env['_sent'][0]
        self.assertEqual(destination, 9)
        self.assertIn('无法根据部门匹配全员群', text)
        record = env['regularization_events'].get('today:-1:4')
        self.assertEqual(record['status'], 'failed')

    async def test_duplicate_message_is_not_reprocessed(self):
        env = build_env()
        event = NS(chat_id=-1, sender_id=8416618309, raw_text=GROUPED_MESSAGE,
                    message=NS(id=5))
        await env['on_regularization_today_trigger'](event)
        self.assertEqual(len(env['_sent']), 2)
        await env['on_regularization_today_trigger'](event)
        self.assertEqual(len(env['_sent']), 2)


class SscApprovalDeletesDraftTests(IsolatedAsyncioTestCase):
    def build_approval_env(self, outbox, state):
        source = ast.parse(Path(__file__).with_name('main.py').read_text())
        functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                     and n.name in {'on_ssc_send_approval', 'get_ssc_reviewer'}]
        for node in functions:
            node.decorator_list = []

        sent = []
        self.deleted = []

        async def send_message(destination, text, **kwargs):
            sent.append((destination, text))
            return NS(id=999, date=NS(isoformat=lambda: '2026-09-21'))

        async def get_messages(chat_id, ids):
            return NS(id=ids, raw_text='【转正信息同步】\n\n花名：比尔', media=None)

        async def delete_messages(chat_id, ids):
            self.deleted.append((chat_id, ids))

        me = NS(id=9, username='ffuuyao')
        env = dict(
            asyncio=asyncio, log=logging.getLogger('test'), select_pending=select_pending,
            client=NS(get_me=AsyncMock(return_value=me), send_message=send_message,
                       get_messages=get_messages, delete_messages=delete_messages),
            outbox=outbox, state=state, ssc_send_lock=asyncio.Lock(),
            config=NS(APPROVAL_CODES=frozenset({'测试4.1'}), EXCLUDED_CHAT_IDS=frozenset()),
            forward_onboarding_to_hrgs=AsyncMock(),
            replay_pending_recruiter_dm=AsyncMock(),
        )
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
        self._sent = sent
        return env

    async def test_deletes_draft_after_forwarding_when_flagged(self):
        outbox = MemoryStore()
        outbox.set('200', {
            'draft_id': 200, 'destination': -5258992607, 'reply_to': None,
            'candidate': 'regularization_today_sync:today:-1:1',
            'expected_stage': 'waiting_ssc_regularization_today_sync',
            'updates': {'stage': 'regularization_today_sync_sent', 'names': ['比尔']},
            'id_field': None, 'kind': 'message', 'status': 'pending',
            'review_chat_id': 9, 'approval_code': '测试4.1',
            'delete_draft_after_send': True,
        })
        state = MemoryStore()
        state.set('regularization_today_sync:today:-1:1',
                   {'stage': 'waiting_ssc_regularization_today_sync'})
        env = self.build_approval_env(outbox, state)

        event = NS(chat_id=9, sender_id=9, is_private=True, raw_text='测试4.1',
                    message=NS(id=201, reply_to_msg_id=None))
        await env['on_ssc_send_approval'](event)

        self.assertEqual(self._sent, [(-5258992607, '【转正信息同步】\n\n花名：比尔')])
        self.assertEqual(self.deleted, [(9, [200])])
        self.assertEqual(outbox.get('200')['status'], 'sent')

    async def test_poster_draft_also_deleted_after_测试4_approval(self):
        # 用户要求：测试4 审核通过、海报和祝贺转发到全员群后，收藏夹里的这条草稿也要删掉。
        outbox = MemoryStore()
        outbox.set('400', {
            'draft_id': 400, 'destination': -5375721803, 'reply_to': None,
            'candidate': 'regularization_today:today:-1:1:比尔',
            'expected_stage': 'waiting_ssc_regularization_today',
            'updates': {'stage': 'regularization_today_sent', 'name': '比尔'},
            'id_field': None, 'kind': 'message', 'status': 'pending',
            'review_chat_id': 9, 'approval_code': '测试4',
            'delete_draft_after_send': True,
        })
        state = MemoryStore()
        state.set('regularization_today:today:-1:1:比尔',
                   {'stage': 'waiting_ssc_regularization_today'})
        env = self.build_approval_env(outbox, state)
        env['config'].APPROVAL_CODES = frozenset({'测试4'})

        event = NS(chat_id=9, sender_id=9, is_private=True, raw_text='测试4',
                    message=NS(id=401, reply_to_msg_id=None))
        await env['on_ssc_send_approval'](event)

        self.assertEqual(self.deleted, [(9, [400])])
        self.assertEqual(outbox.get('400')['status'], 'sent')

    async def test_does_not_delete_draft_when_flag_absent(self):
        # 代表未设置 delete_draft_after_send 的老流程（如 offer 群消息），默认不删草稿。
        outbox = MemoryStore()
        outbox.set('300', {
            'draft_id': 300, 'destination': -5375721803, 'reply_to': None,
            'candidate': 'offer:some-candidate',
            'expected_stage': 'waiting_ssc_offer',
            'updates': {'stage': 'offer_sent'},
            'id_field': None, 'kind': 'message', 'status': 'pending',
            'review_chat_id': 9, 'approval_code': '测试1',
        })
        state = MemoryStore()
        state.set('offer:some-candidate', {'stage': 'waiting_ssc_offer'})
        env = self.build_approval_env(outbox, state)
        env['config'].APPROVAL_CODES = frozenset({'测试1'})

        event = NS(chat_id=9, sender_id=9, is_private=True, raw_text='测试1',
                    message=NS(id=301, reply_to_msg_id=None))
        await env['on_ssc_send_approval'](event)

        self.assertEqual(len(self._sent), 1)
        self.assertEqual(self.deleted, [])
