import ast
import asyncio
import logging
import random
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from approval_queue import select_pending
from parsers import parse_kv_fields, get_field
from account_request import (
    account_request_category,
    build_account_request_text,
    matches_account_request_keyword,
    name_from_direct_text,
    name_from_forward_sender_name,
)


PROFILE_TEXT = """【入职信息同步】
北斗矩阵：恒睿
部门-小组：效能中心-测试组
编号：NX4325
花名：廖伊波
简历名：廖伊波
TG：@heather80130
"""


class MemoryStore:
    def __init__(self, data=None):
        self.data = data or {}

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
        EXCLUDED_CHAT_IDS=frozenset(),
        ACCOUNT_REQUEST_ENABLED=True,
        ACCOUNT_REQUEST_MANAGER_USERNAME='huakaifuguiyes',
        GROUP_LEADERSHIP=-1,
        GROUP_ACCOUNT_REQUEST_FOREIGN=-5414021470,
        GROUP_ACCOUNT_REQUEST_WORK=-5309896717,
        ALLOWED_DESTINATION_IDS={-5414021470, -5309896717},
        ACCOUNT_REQUEST_APPROVAL_CODE='测试5',
        APPROVAL_CODES=frozenset({'测试5'}),
        OFFER_APPROVAL_CODE='测试1', ENVIRONMENT='test',
    )
    fields.update(overrides)
    return NS(**fields)


def build_env(profile_text=PROFILE_TEXT, find_error=None, **overrides):
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'on_account_request_trigger', '_send_delayed_ok_reply',
                                'get_ssc_reviewer', 'queue_group_message',
                                'on_ssc_send_approval'}]
    for node in functions:
        node.decorator_list = []

    sent = []
    replies = []

    async def send_message(destination, text, **kwargs):
        if kwargs.get('reply_to') is not None and destination != 9:
            pass
        sent.append((destination, text, kwargs.get('file'), kwargs.get('reply_to')))
        return NS(id=100 + len(sent))

    me = NS(id=9, username='ffuuyao')
    manager = NS(id=555, username='huakaifuguiyes', first_name='洛羽-SSC主管-CN')
    client = NS(get_me=AsyncMock(return_value=me), send_message=send_message,
                get_messages=AsyncMock())

    def find_by_display_name(name):
        if find_error:
            raise find_error
        return profile_text, NS(get=lambda k: 'file-id')

    env = dict(
        matches_account_request_keyword=matches_account_request_keyword,
        account_request_category=account_request_category,
        name_from_forward_sender_name=name_from_forward_sender_name,
        name_from_direct_text=name_from_direct_text,
        build_account_request_text=build_account_request_text,
        parse_kv_fields=parse_kv_fields, get_field=get_field,
        select_pending=select_pending,
        asyncio=asyncio, random=random,
        log=logging.getLogger('test'),
        client=client,
        outbox=MemoryStore(), state=MemoryStore(), ssc_send_lock=asyncio.Lock(),
        account_request_events=MemoryStore(), account_request_lock=asyncio.Lock(),
        onboarding_training_drive=NS(find_by_display_name=find_by_display_name),
        forward_onboarding_to_hrgs=AsyncMock(),
        config=base_config(),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
    env['_sent'] = sent
    env['_client'] = client
    env['_manager'] = manager
    return env


def dm_event(text, msg_id=1, forward=None, sender=None):
    return NS(
        chat_id=555, is_private=True, raw_text=text,
        get_sender=AsyncMock(return_value=sender or NS(id=555, username='huakaifuguiyes', first_name='洛羽-SSC主管-CN')),
        message=NS(id=msg_id, forward=forward),
    )


def approve_event(code, approval_msg_id):
    return NS(chat_id=9, raw_text=code, is_private=True, sender_id=9,
              message=NS(id=approval_msg_id, reply_to_msg_id=None))


class AccountRequestHandlerTests(IsolatedAsyncioTestCase):
    async def test_forwarded_message_extracts_name_and_queues_foreign_category(self):
        forward = NS(sender=NS(first_name='里昂-HRGS-CN'), from_name=None)
        env = build_env()
        await env['on_account_request_trigger'](
            dm_event('哥 我这边要申请一个外事号', forward=forward)
        )

        drafts = [t for d, t, _f, _r in env['_sent'] if d == 9]
        self.assertEqual(len(drafts), 1)
        self.assertIn('花名：廖伊波', drafts[0])
        self.assertIn('申请外事号/外事TG号/外事邮箱 1个', drafts[0])

        record = next(r for r in env['outbox'].all().values() if r['approval_code'] == '测试5')
        self.assertEqual(record['destination'], -5414021470)

    async def test_direct_text_extracts_name_and_queues_work_category(self):
        env = build_env()
        await env['on_account_request_trigger'](
            dm_event('就为廖伊波申请一个工作邮箱')
        )

        record = next(r for r in env['outbox'].all().values() if r['approval_code'] == '测试5')
        self.assertEqual(record['destination'], -5309896717)
        drafts = [t for d, t, _f, _r in env['_sent'] if d == 9]
        self.assertIn('申请工作帐号/TG号/工作邮箱 1个', drafts[0])

    async def test_schedules_delayed_ok_reply_without_blocking_draft_creation(self):
        forward = NS(sender=NS(first_name='里昂-HRGS-CN'), from_name=None)
        env = build_env()
        await env['on_account_request_trigger'](
            dm_event('哥 我这边要申请一个外事号', forward=forward, msg_id=42)
        )
        # 草稿已经生成，说明没有等30-60秒的延迟任务跑完才继续。
        self.assertTrue(any(d == 9 for d, _t, _f, _r in env['_sent']))
        # 还没replies到私聊(依赖随机延迟任务真正跑完，这里只验证没有立刻同步发送)。
        self.assertFalse(any(d == 555 for d, _t, _f, _r in env['_sent']))

    async def test_non_manager_sender_is_ignored(self):
        env = build_env()
        await env['on_account_request_trigger'](
            dm_event('哥 我这边要申请一个外事号',
                     sender=NS(id=1, first_name='张三'))
        )
        self.assertEqual(env['_sent'], [])

    async def test_group_message_is_ignored(self):
        env = build_env()
        event = dm_event('哥 我这边要申请一个外事号')
        event.is_private = False
        await env['on_account_request_trigger'](event)
        self.assertEqual(env['_sent'], [])

    async def test_no_keyword_is_ignored(self):
        env = build_env()
        await env['on_account_request_trigger'](dm_event('今天天气不错'))
        self.assertEqual(env['_sent'], [])

    async def test_no_extractable_name_reports_failure(self):
        env = build_env()
        await env['on_account_request_trigger'](dm_event('外事号么'))
        record = env['account_request_events'].get('555:1')
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(len(env['_sent']), 1)
        self.assertEqual(env['_sent'][0][0], 9)

    async def test_profile_lookup_failure_reports_to_favorites(self):
        forward = NS(sender=NS(first_name='里昂-HRGS-CN'), from_name=None)
        env = build_env(find_error=FileNotFoundError('未找到'))
        await env['on_account_request_trigger'](
            dm_event('哥 我这边要申请一个外事号', forward=forward)
        )
        record = env['account_request_events'].get('555:1')
        self.assertEqual(record['status'], 'failed')

    async def test_approving_code_forwards_to_matching_group(self):
        forward = NS(sender=NS(first_name='里昂-HRGS-CN'), from_name=None)
        env = build_env()
        await env['on_account_request_trigger'](
            dm_event('哥 我这边要申请一个外事号', forward=forward)
        )
        draft_id = next(
            r['draft_id'] for r in env['outbox'].all().values()
            if r['approval_code'] == '测试5'
        )
        env['_client'].get_messages = AsyncMock(
            return_value=NS(id=draft_id, raw_text='【员工帐号申请】已核对内容', media=None)
        )
        await env['on_ssc_send_approval'](approve_event('测试5', 2000))

        forwarded = [t for d, t, _f, _r in env['_sent'] if d == -5414021470]
        self.assertEqual(len(forwarded), 1)
        self.assertIn('已核对内容', forwarded[0])

    async def test_disabled_when_not_enabled(self):
        forward = NS(sender=NS(first_name='里昂-HRGS-CN'), from_name=None)
        env = build_env(config=base_config(ACCOUNT_REQUEST_ENABLED=False))
        await env['on_account_request_trigger'](
            dm_event('哥 我这边要申请一个外事号', forward=forward)
        )
        self.assertEqual(env['_sent'], [])


if __name__ == '__main__':
    import unittest
    unittest.main()
