import ast
import asyncio
import logging
from datetime import datetime, timedelta, timezone
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
        ALL_STAFF_NOTICE_TRIGGER_SENDERS={},
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
    functions = [n for n in source.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                 and n.name in {'on_all_staff_notice_trigger', 'get_ssc_reviewer',
                                'queue_all_staff_broadcast', 'on_ssc_send_approval',
                                'find_all_staff_source_near', '_all_staff_candidate',
                                'usable_media'}]
    for node in functions:
        node.decorator_list = []

    sent = []
    deleted = []

    async def send_message(destination, text, **kwargs):
        sent.append((destination, text, kwargs.get('file')))
        return NS(id=100 + len(sent))

    async def delete_messages(chat_id, ids):
        deleted.extend(ids)

    async def history(chat_id, limit=None, max_id=0, min_id=0, reverse=False, **kwargs):
        # 像Telethon一样：默认从新到旧，reverse从旧到新；min_id/max_id是开区间
        messages = [m for m in list(history_messages or [])
                    if (not max_id or m.id < max_id) and (not min_id or m.id > min_id)]
        messages.sort(key=lambda m: m.id, reverse=not reverse)
        for message in messages[:limit]:
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
    env['_history'] = history_messages
    env['_sent'] = sent
    env['_deleted'] = deleted
    env['_client'] = client
    return env


def trigger_event(msg_id=10, chat_id=-5000000002):
    return NS(chat_id=chat_id, raw_text=TRIGGER_TEXT, message=NS(id=msg_id))


def approve_event(code, approval_msg_id):
    return NS(chat_id=9, raw_text=code, is_private=True, sender_id=9,
              message=NS(id=approval_msg_id, reply_to_msg_id=None))


def sender_event(username, msg_id=10, chat_id=-5000000002):
    return NS(chat_id=chat_id, raw_text=TRIGGER_TEXT, message=NS(id=msg_id),
              get_sender=AsyncMock(return_value=NS(username=username)))


T0 = datetime(2026, 10, 17, 3, 0, 0, tzinfo=timezone.utc)
OWNER_ID = 555
PHOTO = NS(photo=True)


def msg(msg_id, seconds, text='', media=None, sender_id=OWNER_ID):
    return NS(id=msg_id, date=T0 + timedelta(seconds=seconds), raw_text=text,
              media=media, sender_id=sender_id)


def sender_event(username, msg_id=10, chat_id=-5000000002, seconds=100):
    return NS(chat_id=chat_id, raw_text=TRIGGER_TEXT,
              message=msg(msg_id, seconds, TRIGGER_TEXT),
              get_sender=AsyncMock(return_value=NS(username=username, id=OWNER_ID)))


class FakeAsyncio:
    """不真的等待：每次sleep推进一个假时钟，并让到点的"迟到消息"出现在历史里。"""

    def __init__(self, history, late=()):
        self.history = history
        self.late = list(late)  # [(第几秒出现, 消息)]
        self.clock = 0
        self.Lock = asyncio.Lock

    async def sleep(self, seconds):
        self.clock += seconds
        for at, message in list(self.late):
            if self.clock >= at:
                self.history.append(message)
                self.late.remove((at, message))


RESTRICTED = {-5000000002: 'xingchendahai990'}


def restricted_env(history, late=(), wait=60):
    history = list(history)
    fake = FakeAsyncio(history, late)
    env = build_env(
        history_messages=history,
        config=base_config(ALL_STAFF_NOTICE_TRIGGER_SENDERS=RESTRICTED,
                           ALL_STAFF_NOTICE_AFTER_WAIT_SECONDS=wait),
        asyncio=fake,
    )
    env['_fake'] = fake
    return env


class AllStaffNoticeSenderTests(IsolatedAsyncioTestCase):
    """星辰小组工作对接群里只认@xingchendahai990发的"全员群"关键词，
    要转发的是该发送者发的、离指令最近的那条（上面或下面）。"""

    async def test_trigger_from_required_sender_queues_draft(self):
        env = restricted_env([msg(9, 95, '【欢迎新同事】图文海报正文', PHOTO)])
        await env['on_all_staff_notice_trigger'](sender_event('xingchendahai990'))
        self.assertEqual(len(env['_sent']), 1)
        self.assertEqual(env['all_staff_notice_events'].get('-5000000002:10')['status'], 'queued')

    async def test_sender_match_ignores_case_and_at_sign(self):
        env = restricted_env([msg(9, 95, '正文', PHOTO)])
        await env['on_all_staff_notice_trigger'](sender_event('XingChenDaHai990'))
        self.assertEqual(len(env['_sent']), 1)

    async def test_keyword_from_anyone_else_is_ignored(self):
        env = restricted_env([msg(9, 95, '正文', PHOTO)])
        for username in ('someone_else', '', None):
            await env['on_all_staff_notice_trigger'](sender_event(username))
        self.assertEqual(env['_sent'], [])
        self.assertIsNone(env['all_staff_notice_events'].get('-5000000002:10'))

    async def test_other_trigger_chat_is_not_sender_restricted(self):
        poster = NS(id=9, raw_text='【欢迎新同事】图文海报正文', media=NS(photo=True))
        env = build_env(
            history_messages=[poster],
            config=base_config(ALL_STAFF_NOTICE_TRIGGER_SENDERS=RESTRICTED),
        )
        # -5339407017是另一个来源群（SSC3内部沟通群），不限发送者，也不会去取发送者
        event = NS(chat_id=-5339407017, raw_text=TRIGGER_TEXT, message=NS(id=10),
                   get_sender=AsyncMock(side_effect=AssertionError('不该查发送者')))
        await env['on_all_staff_notice_trigger'](event)
        self.assertEqual(len(env['_sent']), 1)

    async def test_forwarded_notice_below_the_trigger_is_used_with_its_image(self):
        # 截图1：指令上面是别的内容，下面紧跟着转发进来的"重要通知"（带图）
        old = msg(5, 0, '很早以前的旧消息')
        notice = msg(11, 103, '【重要通知】明天全员大会', PHOTO)
        env = restricted_env([old, msg(10, 100, TRIGGER_TEXT), notice])
        await env['on_all_staff_notice_trigger'](sender_event('xingchendahai990'))
        destination, text, media = env['_sent'][0]
        self.assertIn('【重要通知】明天全员大会', text)
        self.assertIs(media, PHOTO)

    async def test_text_only_notice_above_the_trigger_is_used(self):
        # 截图2：上面是纯文字"9月薪资已发放完毕…"；下面是别的发送者（机器人）的消息
        salary = msg(9, 97, '9月薪资已发放完毕，请大家查收', None)
        bot_reply = msg(11, 101, '收到', None, sender_id=999)
        env = restricted_env([salary, msg(10, 100, TRIGGER_TEXT), bot_reply], wait=6)
        await env['on_all_staff_notice_trigger'](sender_event('xingchendahai990'))
        destination, text, media = env['_sent'][0]
        self.assertIn('9月薪资已发放完毕，请大家查收', text)
        self.assertIsNone(media)

    async def test_closer_one_wins_when_both_sides_exist(self):
        before = msg(9, 50, '上面那条（隔了50秒）')
        after = msg(11, 102, '下面那条（隔了2秒）')
        env = restricted_env([before, msg(10, 100, TRIGGER_TEXT), after])
        await env['on_all_staff_notice_trigger'](sender_event('xingchendahai990'))
        self.assertIn('下面那条', env['_sent'][0][1])

        before = msg(9, 98, '上面那条（隔了2秒）')
        after = msg(11, 150, '下面那条（隔了50秒）')
        env = restricted_env([before, msg(10, 100, TRIGGER_TEXT), after])
        await env['on_all_staff_notice_trigger'](sender_event('xingchendahai990'))
        self.assertIn('上面那条', env['_sent'][0][1])

    async def test_notice_arriving_after_the_trigger_is_waited_for(self):
        late = msg(11, 108, '【重要通知】迟到的通知', PHOTO)
        env = restricted_env([msg(10, 100, TRIGGER_TEXT)], late=[(6, late)])
        await env['on_all_staff_notice_trigger'](sender_event('xingchendahai990'))
        self.assertIn('迟到的通知', env['_sent'][0][1])
        self.assertLessEqual(env['_fake'].clock, 60)

    async def test_far_above_message_does_not_make_us_wait_the_full_time(self):
        # 上面那条只隔3秒：下面的只有3秒内到才更近，所以最多等3秒
        env = restricted_env([msg(9, 97, '上面那条'), msg(10, 100, TRIGGER_TEXT)])
        await env['on_all_staff_notice_trigger'](sender_event('xingchendahai990'))
        self.assertIn('上面那条', env['_sent'][0][1])
        self.assertLessEqual(env['_fake'].clock, 3)

    async def test_other_senders_and_the_trigger_itself_are_never_picked(self):
        env = restricted_env([
            msg(9, 99, '别人发的', PHOTO, sender_id=999),
            msg(10, 100, TRIGGER_TEXT),
            msg(11, 101, '另一个全员群指令', None),
        ], wait=4)
        await env['on_all_staff_notice_trigger'](sender_event('xingchendahai990'))
        # 只给收藏夹发一条失败提示，不生成转发草稿
        self.assertEqual(len(env['_sent']), 1)
        self.assertIn('转发失败', env['_sent'][0][1])
        self.assertEqual(env['all_staff_notice_events'].get('-5000000002:10')['status'], 'failed')

    async def test_empty_media_without_text_is_not_a_candidate(self):
        webpage = msg(9, 99, '', NS(webpage=True))
        env = restricted_env([webpage, msg(10, 100, TRIGGER_TEXT)], wait=2)
        env['usable_media'] = lambda m: None
        await env['on_all_staff_notice_trigger'](sender_event('xingchendahai990'))
        self.assertEqual(len(env['_sent']), 1)
        self.assertIn('转发失败', env['_sent'][0][1])


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
        # 第5次发送成功后才删除：收藏夹草稿 + 5条审批码(7)消息。
        self.assertEqual(env['_deleted'], [draft_id, 2000, 2001, 2002, 2003, 2004])
        record = next(r for r in env['outbox'].all().values() if r['draft_id'] == draft_id)
        self.assertEqual(record['status'], 'sent')

    async def test_approval_message_delete_failure_does_not_break_completion(self):
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
        calls = []

        async def flaky_delete(chat_id, ids):
            calls.append(list(ids))
            if len(calls) == 2:
                raise RuntimeError('network')

        env['_client'].delete_messages = flaky_delete
        for i in range(5):
            await env['on_ssc_send_approval'](approve_event('测试7', 4000 + i))

        self.assertEqual(calls, [[draft_id], [4000, 4001, 4002, 4003, 4004]])
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
