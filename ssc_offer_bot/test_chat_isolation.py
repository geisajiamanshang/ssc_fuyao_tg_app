import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock


class ChatIsolationTests(IsolatedAsyncioTestCase):
    def setUp(self):
        source = ast.parse(Path(__file__).with_name('main.py').read_text())
        functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                     and n.name in {'debug_all_messages', 'retry_recruit_notifications',
                                    'on_ssc_send_approval'}]
        for node in functions:
            node.decorator_list = []
        self.logs = []
        env = dict(
            log=NS(info=lambda *a, **k: self.logs.append(a), warning=lambda *a, **k: None,
                   exception=lambda *a, **k: None),
            config=NS(EXCLUDED_CHAT_IDS=frozenset({-999}), APPROVAL_CODES=frozenset()),
            client=NS(get_me=AsyncMock(return_value=NS(id=1))),
            get_ssc_reviewer=AsyncMock(return_value=NS(id=1)),
            outbox=NS(all=lambda: {}), state=NS(all=lambda: {}),
            ssc_send_lock=asyncio.Lock(),
        )
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
        self.env = env

    async def test_debug_logger_skips_test_group(self):
        event = NS(chat_id=-999, get_chat=AsyncMock(return_value=NS(title='测试群')),
                    message=NS(mentioned=False), raw_text='任意内容')
        await self.env['debug_all_messages'](event)
        self.assertEqual(self.logs, [])

    async def test_debug_logger_still_logs_other_chats(self):
        event = NS(chat_id=-1, get_chat=AsyncMock(return_value=NS(title='正常群')),
                    message=NS(mentioned=False), raw_text='任意内容')
        await self.env['debug_all_messages'](event)
        self.assertEqual(len(self.logs), 1)

    async def test_retry_notifications_skips_test_group(self):
        event = NS(chat_id=-999, raw_text='重试招聘通知')
        result = await self.env['retry_recruit_notifications'](event)
        self.assertIsNone(result)
        self.env['client'].get_me.assert_not_called()

    async def test_ssc_send_approval_skips_test_group(self):
        event = NS(chat_id=-999, raw_text='1')
        result = await self.env['on_ssc_send_approval'](event)
        self.assertIsNone(result)
        self.env['client'].get_me.assert_not_called()
