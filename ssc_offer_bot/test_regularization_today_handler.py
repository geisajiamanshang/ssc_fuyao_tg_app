import ast
import asyncio
import logging
import unicodedata
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from regularization import (
    department_for_name,
    greeting_for_name,
    match_department_group,
    names_from_trigger,
    split_sections,
    today_trigger_matches,
    today_trigger_scope,
)
from state_store import StateStore


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
        config=NS(
            EXCLUDED_CHAT_IDS=frozenset(), ALLOW_MANUAL_TRIGGERS=True,
            REGULARIZATION_TRIGGER_BOT_ID=8416618309,
            REGULARIZATION_TODAY_TRIGGER_KEYWORD='转正提醒-恒睿-今日转正',
            DAILY_REPORT_TIMEZONE='Asia/Shanghai',
            ANNIVERSARY_GROUP_RULES=GROUP_RULES,
            ALLOWED_DESTINATION_IDS={-5375721803},
            REGULARIZATION_TODAY_APPROVAL_CODE='测试4',
            OFFER_APPROVAL_CODE='测试1', ENVIRONMENT='test',
        ),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
    env['_sent'] = sent
    return env


class RegularizationTodayHandlerTests(IsolatedAsyncioTestCase):
    async def test_happy_path_sends_poster_and_greeting_to_matched_group(self):
        env = build_env()
        event = NS(chat_id=-1, sender_id=8416618309, raw_text=GROUPED_MESSAGE,
                    message=NS(id=1))
        await env['on_regularization_today_trigger'](event)

        # 草稿先进 SSC 收藏夹（reviewer.id=9），不是直接发到全员群；
        # 真正的目标群记录在 outbox 里，等 SSC 回复测试4后才会真正转发。
        self.assertEqual(len(env['_sent']), 1)
        draft_recipient, text, file = env['_sent'][0]
        self.assertEqual(draft_recipient, 9)
        self.assertTrue(text.startswith('祝贺 比尔 @guzhi2099'))
        self.assertNotIn('🆗️', text)
        self.assertEqual(file, 'poster-for-比尔')

        outbox_record = next(iter(env['outbox'].all().values()))
        self.assertEqual(outbox_record['destination'], -5375721803)
        self.assertEqual(outbox_record['approval_code'], '测试4')

        record = env['regularization_events'].get('today:-1:1')
        self.assertEqual(record['status'], 'queued')
        self.assertEqual(record['drafts'][0]['name'], '比尔')

    async def test_ignores_message_without_today_keyword(self):
        env = build_env()
        event = NS(chat_id=-1, sender_id=8416618309, raw_text='普通消息，没有关键字',
                    message=NS(id=2))
        await env['on_regularization_today_trigger'](event)
        self.assertEqual(env['_sent'], [])

    async def test_skips_test_group_when_excluded(self):
        env = build_env(config=NS(
            EXCLUDED_CHAT_IDS=frozenset({-1}), ALLOW_MANUAL_TRIGGERS=True,
            REGULARIZATION_TRIGGER_BOT_ID=8416618309,
            REGULARIZATION_TODAY_TRIGGER_KEYWORD='转正提醒-恒睿-今日转正',
            DAILY_REPORT_TIMEZONE='Asia/Shanghai', ANNIVERSARY_GROUP_RULES=GROUP_RULES,
            ALLOWED_DESTINATION_IDS={-5375721803},
            REGULARIZATION_TODAY_APPROVAL_CODE='测试4',
            OFFER_APPROVAL_CODE='测试1', ENVIRONMENT='test',
        ))
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
        self.assertEqual(len(env['_sent']), 1)
        await env['on_regularization_today_trigger'](event)
        self.assertEqual(len(env['_sent']), 1)
