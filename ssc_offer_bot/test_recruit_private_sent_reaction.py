# -*- coding: utf-8 -*-
"""场景二：终审通知里让招聘"私聊我"发候选人信息之后，SSC平时会手动点个
👌或❤️表情确认收到——一处是招聘回到招聘群回复那条通知说"私发了"，一处是
招聘私聊SSC发候选人信息本身。这两处都自动化成随机延迟10-30秒后点一个
随机表情，模拟人工确认的节奏，而不是消息一出现就秒回。
"""

import ast
import asyncio
import random
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

source = Path(__file__).with_name('main.py').read_text()
tree = ast.parse(source)
selected = {'_send_delayed_reaction', 'on_recruit_private_sent_reply'}


class _FakeReactionEmoji:
    def __init__(self, emoticon):
        self.emoticon = emoticon


def _fake_send_reaction_request(peer, msg_id, reaction):
    return NS(peer=peer, msg_id=msg_id, reaction=reaction)


class MockClient:
    """client(SomeRequest(...))这种可调用写法，SimpleNamespace不支持让实例
    本身可调用，单独写一个最小的替身类（跟test_leadership_reaction.py用的
    是同一个模式）。"""
    def __init__(self):
        self.call_mock = AsyncMock()

    async def __call__(self, *args, **kwargs):
        return await self.call_mock(*args, **kwargs)


def build_env(**overrides):
    functions = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in selected]
    for node in functions:
        node.decorator_list = []
    client = MockClient()
    client.get_me = AsyncMock(return_value=NS(id=9, username='ffuuyao'))
    env = dict(
        asyncio=asyncio, random=random,
        ReactionEmoji=_FakeReactionEmoji,
        SendReactionRequest=_fake_send_reaction_request,
        RECRUIT_PRIVATE_SENT_ACK_EMOJIS=("👌", "❤️"),
        client=client,
        config=NS(EXCLUDED_CHAT_IDS=frozenset()),
        log=NS(warning=lambda *a, **kw: None, exception=lambda *a, **kw: None),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
    env['_client'] = client
    return env


def reply_event(text, *, chat_id=-456, msg_id=200, replied_sender_id=9, is_reply=True):
    replied = NS(sender_id=replied_sender_id) if is_reply else None
    return NS(
        chat_id=chat_id, raw_text=text, is_reply=is_reply,
        message=NS(id=msg_id),
        get_reply_message=AsyncMock(return_value=replied),
    )


class SendDelayedReactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_sleeps_then_sends_one_of_the_two_emojis(self):
        env = build_env()
        with patch.object(env['asyncio'], 'sleep', AsyncMock()) as sleep_mock, \
             patch.object(env['random'], 'choice', return_value='👌') as choice_mock:
            await env['_send_delayed_reaction'](-456, 300, 17)
        sleep_mock.assert_awaited_once_with(17)
        choice_mock.assert_called_once_with(('👌', '❤️'))
        env['_client'].call_mock.assert_awaited_once()
        call = env['_client'].call_mock.call_args.args[0]
        self.assertEqual(call.peer, -456)
        self.assertEqual(call.msg_id, 300)
        self.assertEqual(len(call.reaction), 1)
        self.assertEqual(call.reaction[0].emoticon, '👌')

    async def test_failure_is_caught_and_logged_not_raised(self):
        env = build_env()
        env['_client'].call_mock.side_effect = RuntimeError('boom')
        logged = []
        env['log'] = NS(exception=lambda *a, **kw: logged.append(a))
        # 不应该抛出异常中断调用方（这是一个fire-and-forget的后台任务）。
        await env['_send_delayed_reaction'](-456, 300, 0)
        self.assertEqual(len(logged), 1)


class RecruitPrivateSentReplyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.env = build_env()
        self.scheduled = []

        async def fake_reaction(chat_id, message_id, delay_seconds):
            self.scheduled.append((chat_id, message_id, delay_seconds))

        self.env['_send_delayed_reaction'] = fake_reaction

    async def _run(self, event):
        await self.env['on_recruit_private_sent_reply'](event)
        # asyncio.create_task调度的后台任务要让出一次事件循环才会真正执行。
        await asyncio.sleep(0)

    async def test_reply_to_bot_notice_with_keyword_schedules_reaction(self):
        # 真实例子：招聘回复机器人发的招聘通知，说"入职信息已私发"。
        await self._run(reply_event('入职信息已私发', chat_id=-456, msg_id=201))
        self.assertEqual(len(self.scheduled), 1)
        chat_id, message_id, delay = self.scheduled[0]
        self.assertEqual((chat_id, message_id), (-456, 201))
        self.assertTrue(10 <= delay <= 30)

    async def test_reply_without_keyword_is_ignored(self):
        await self._run(reply_event('约10月8日16点面试 谢谢'))
        self.assertEqual(self.scheduled, [])

    async def test_reply_to_someone_elses_message_is_ignored(self):
        # 只处理"回复机器人自己发的通知"，不误伤回复别人消息里提到"私发"
        # 两个字的日常对话。
        await self._run(reply_event('入职信息已私发', replied_sender_id=8))
        self.assertEqual(self.scheduled, [])

    async def test_non_reply_message_is_ignored(self):
        await self._run(reply_event('入职信息已私发', is_reply=False))
        self.assertEqual(self.scheduled, [])

    async def test_excluded_chat_is_ignored(self):
        self.env['config'] = NS(EXCLUDED_CHAT_IDS=frozenset({-456}))
        await self._run(reply_event('入职信息已私发', chat_id=-456))
        self.assertEqual(self.scheduled, [])


if __name__ == '__main__':
    unittest.main()
