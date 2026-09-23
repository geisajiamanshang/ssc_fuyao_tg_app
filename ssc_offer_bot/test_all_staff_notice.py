import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from approval_queue import select_pending


GROUP_RULES = [
    {"name": "测试-ACFAN", "keywords": ["ACFAN特战队", "ACFAN", "AIGC原创部", "AIGC"], "chat_id": -101},
    {"name": "测试-运营一部", "keywords": ["运营一部", "运营1部"], "chat_id": -102},
    {"name": "测试-运营二部", "keywords": ["运营二部", "运营2部"], "chat_id": -103},
    {"name": "测试-渠道商务", "keywords": ["渠道部", "商务部"], "chat_id": -104},
    {"name": "测试-技术效能", "keywords": ["技术部", "效能部"], "chat_id": -105},
]

TRIGGER_TEXT = "麻烦转发到全员群，谢谢～"


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
        ALL_STAFF_NOTICE_ENABLED=True,
        ALL_STAFF_NOTICE_TRIGGER_CHAT_IDS=frozenset({-5000000002, -5339407017}),
        ALL_STAFF_NOTICE_TRIGGER_KEYWORD='全员群',
        ANNIVERSARY_GROUP_RULES=GROUP_RULES,
        ALLOWED_DESTINATION_IDS={-101, -102, -103, -104, -105},
        ALL_STAFF_NOTICE_APPROVAL_CODE='测试7',
        APPROVAL_CODES=frozenset({'测试7'}),
        OFFER_APPROVAL_CODE='测试1', ENVIRONMENT='test',
    )
    fields.update(overrides)
    return NS(**fields)


def build_env(history_messages=None, **overrides):
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'on_all_staff_notice_trigger', 'get_ssc_reviewer',
                                'queue_all_staff_broadcast', 'on_ssc_send_approval'}]
    for node in functions:
        node.decorator_list = []

    sent = []
    deleted = []

    async def send_message(destination, text, **kwargs):
        sent.append((destination, text, kwargs.get('file')))
        return NS(id=100 + len(sent))

    async def delete_messages(chat_id, ids):
        deleted.extend(ids)

    async def history(*args, **kwargs):
        for message in (history_messages or []):
            yield message

    me = NS(id=9, username='ffuuyao')
    client = NS(get_me=AsyncMock(return_value=me), send_message=send_message,
                get_messages=AsyncMock(), delete_messages=delete_messages,
                iter_messages=history)

    env = dict(
        select_pending=select_pending,
        asyncio=asyncio,
        log=logging.getLogger('test'),
        client=client,
        outbox=MemoryStore(), state=MemoryStore(), ssc_send_lock=asyncio.Lock(),
        all_staff_notice_events=MemoryStore(), all_staff_notice_lock=asyncio.Lock(),
        forward_onboarding_to_hrgs=AsyncMock(),
        config=base_config(),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
    env['_sent'] = sent
    env['_deleted'] = deleted
    env['_client'] = client
    return env


def trigger_event(msg_id=10, chat_id=-5000000002):
    return NS(chat_id=chat_id, raw_text=TRIGGER_TEXT, message=NS(id=msg_id))


def approve_event(code, approval_msg_id):
    return NS(chat_id=9, raw_text=code, is_private=True, sender_id=9,
              message=NS(id=approval_msg_id, reply_to_msg_id=None))


class AllStaffNoticeTests(IsolatedAsyncioTestCase):
    async def test_finds_nearest_preceding_photo_text_message_and_queues_it(self):
        poster = NS(id=9, raw_text='【今日培训温馨提醒】各位同事好……', media=NS(photo=True))
        unrelated_text_only = NS(id=8, raw_text='收到', media=None)
        env = build_env(history_messages=[poster, unrelated_text_only])

        await env['on_all_staff_notice_trigger'](trigger_event())

        # 触发消息本身不转发，只转发找到的图文通知草稿，全部先进收藏夹(reviewer.id=9)。
        self.assertEqual(len(env['_sent']), 1)
        dest, text, file = env['_sent'][0]
        self.assertEqual(dest, 9)
        self.assertIn('培训温馨提醒', text)
        self.assertIsNotNone(file)

        record = env['all_staff_notice_events'].get('-5000000002:10')
        self.assertEqual(record['status'], 'queued')
        self.assertEqual(record['source_message_id'], 9)

    async def test_skips_text_only_messages_when_searching_for_source(self):
        text_only = NS(id=8, raw_text='大家注意查收', media=None)
        poster = NS(id=7, raw_text='【欢迎新同事】图文海报正文', media=NS(photo=True))
        env = build_env(history_messages=[text_only, poster])

        await env['on_all_staff_notice_trigger'](trigger_event())

        record = env['all_staff_notice_events'].get('-5000000002:10')
        self.assertEqual(record['source_message_id'], 7)

    async def test_one_approval_broadcasts_to_only_one_group(self):
        poster = NS(id=9, raw_text='【今日培训温馨提醒】原始内容', media=NS(photo=True))
        env = build_env(history_messages=[poster])
        await env['on_all_staff_notice_trigger'](trigger_event())

        draft_id = next(
            r['draft_id'] for r in env['outbox'].all().values()
            if r['approval_code'] == '测试7'
        )
        env['_client'].get_messages = AsyncMock(
            return_value=NS(id=draft_id, raw_text='【今日培训温馨提醒】原始内容', media=NS(photo=True))
        )

        await env['on_ssc_send_approval'](approve_event('测试7', 2000))

        broadcast_destinations = [d for d, _t, _f in env['_sent'] if d != 9]
        self.assertEqual(len(broadcast_destinations), 1)
        self.assertEqual(broadcast_destinations[0], -101)  # 第一个全员群
        # 只发了一个群，草稿还不能删，要等5个群都发完。
        self.assertEqual(env['_deleted'], [])
        record = next(r for r in env['outbox'].all().values() if r['draft_id'] == draft_id)
        self.assertEqual(record['status'], 'pending')
        self.assertEqual(record['remaining_destinations'], [-102, -103, -104, -105])

    async def test_five_approvals_cover_all_groups_then_delete_draft(self):
        poster = NS(id=9, raw_text='【今日培训温馨提醒】原始内容', media=NS(photo=True))
        env = build_env(history_messages=[poster])
        await env['on_all_staff_notice_trigger'](trigger_event())

        draft_id = next(
            r['draft_id'] for r in env['outbox'].all().values()
            if r['approval_code'] == '测试7'
        )
        env['_client'].get_messages = AsyncMock(
            return_value=NS(id=draft_id, raw_text='【今日培训温馨提醒】已修正内容', media=NS(photo=True))
        )

        for i in range(5):
            await env['on_ssc_send_approval'](approve_event('测试7', 2000 + i))

        broadcast_destinations = [d for d, _t, _f in env['_sent'] if d != 9]
        self.assertEqual(broadcast_destinations, [-101, -102, -103, -104, -105])
        self.assertTrue(all(t == '【今日培训温馨提醒】已修正内容' for _d, t, _f in env['_sent'][1:]))
        # 第5次发送成功后才删除收藏夹草稿。
        self.assertEqual(env['_deleted'], [draft_id])
        record = next(r for r in env['outbox'].all().values() if r['draft_id'] == draft_id)
        self.assertEqual(record['status'], 'sent')

    async def test_sixth_approval_after_completion_does_not_resend(self):
        poster = NS(id=9, raw_text='【今日培训温馨提醒】原始内容', media=NS(photo=True))
        env = build_env(history_messages=[poster])
        await env['on_all_staff_notice_trigger'](trigger_event())

        draft_id = next(
            r['draft_id'] for r in env['outbox'].all().values()
            if r['approval_code'] == '测试7'
        )
        env['_client'].get_messages = AsyncMock(
            return_value=NS(id=draft_id, raw_text='内容', media=NS(photo=True))
        )
        for i in range(5):
            await env['on_ssc_send_approval'](approve_event('测试7', 3000 + i))

        # 草稿已删除、状态已是sent，再发一次同一个审批码不应该再触发任何发送。
        await env['on_ssc_send_approval'](approve_event('测试7', 3999))
        broadcast_destinations = [d for d, _t, _f in env['_sent'] if d != 9]
        self.assertEqual(len(broadcast_destinations), 5)

    async def test_no_matching_source_message_reports_failure_without_sending(self):
        text_only = NS(id=8, raw_text='没有图的消息', media=None)
        env = build_env(history_messages=[text_only])

        await env['on_all_staff_notice_trigger'](trigger_event())

        record = env['all_staff_notice_events'].get('-5000000002:10')
        self.assertEqual(record['status'], 'failed')
        # 失败提示发到收藏夹，不应该出现任何广播草稿。
        self.assertEqual(len(env['_sent']), 1)
        self.assertEqual(env['_sent'][0][0], 9)

    async def test_non_trigger_chat_is_ignored(self):
        env = build_env(history_messages=[])
        await env['on_all_staff_notice_trigger'](trigger_event(chat_id=-999))
        self.assertEqual(env['_sent'], [])

    async def test_missing_keyword_is_ignored(self):
        env = build_env(history_messages=[])
        await env['on_all_staff_notice_trigger'](
            NS(chat_id=-5000000002, raw_text='今天天气不错', message=NS(id=11))
        )
        self.assertEqual(env['_sent'], [])

    async def test_disabled_when_no_trigger_chat_configured(self):
        env = build_env(
            history_messages=[NS(id=1, raw_text='x', media=NS(photo=True))],
            config=base_config(ALL_STAFF_NOTICE_ENABLED=False),
        )
        await env['on_all_staff_notice_trigger'](trigger_event())
        self.assertEqual(env['_sent'], [])


if __name__ == '__main__':
    import unittest
    unittest.main()
