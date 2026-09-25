import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock
from attendance_reply import AttendanceReplies, parse_reminder

TEXT = '🔔 查岗提醒 (编号 SS1132)\n请在 30 分钟内回复以下关键词,以确认当前在岗状态:\n\n【雨】\n20分钟内回复:正常响应。'

class ParserTests(TestCase):
    def test_keyword(self):
        self.assertEqual(parse_reminder(TEXT), ('雨', 1800))
        self.assertEqual(parse_reminder(TEXT.replace('雨', '风')), ('风', 1800))
    def test_unrelated(self):
        for text in ['【雨】', '查岗提醒 已完成', TEXT.replace('30 分钟', '0 分钟')]:
            self.assertIsNone(parse_reminder(text))

class Store:
    def __init__(self): self.data = {}
    def get(self, k): return self.data.get(k)
    def all(self): return self.data
    def set(self, k, v): self.data[k] = v
    def update(self, k, **v): self.data[k].update(v)

class ReplyTests(IsolatedAsyncioTestCase):
    async def setup_case(self, delay=180, manual=False):
        self.now = 1000
        self.original = NS(raw_text=TEXT, date=datetime.fromtimestamp(1000, timezone.utc), id=1, fwd_from=None)
        async def sleep(seconds): self.now += seconds
        async def history(*a, **kw):
            if manual: yield NS(out=True, raw_text='雨')
        self.client = NS(get_messages=AsyncMock(return_value=self.original),
                         send_message=AsyncMock(return_value=NS(id=2)), iter_messages=history)
        self.store = Store()
        self.worker = AttendanceReplies(self.client, self.store, clock=lambda: self.now,
                                        randint=lambda a,b: delay, sleep=sleep)
        self.sender = NS(bot=True, username='chagang123bot', id=10)
        self.event = NS(is_private=True, out=False, chat_id=10, raw_text=TEXT,
                        message=self.original, get_sender=AsyncMock(return_value=self.sender))
    async def test_delay_and_duplicate(self):
        for delay in (180, 600):
            await self.setup_case(delay)
            await self.worker.receive(self.event)
            await self.worker.receive(self.event)
            await asyncio.gather(*list(self.worker.tasks.values()))
            self.assertEqual(self.now, 1000+delay)
            self.client.send_message.assert_awaited_once_with(10, '雨', reply_to=1, parse_mode=None)
    async def test_wrong_sender_or_group_ignored(self):
        await self.setup_case()
        self.sender.username = 'other'
        await self.worker.receive(self.event)
        self.sender.username = 'chagang123bot'
        self.event.is_private = False
        await self.worker.receive(self.event)
        self.assertFalse(self.store.all())
    async def test_manual_reply_cancels(self):
        await self.setup_case(manual=True)
        await self.worker.receive(self.event)
        await asyncio.gather(*list(self.worker.tasks.values()))
        self.client.send_message.assert_not_awaited()
    async def test_expired_ignored(self):
        await self.setup_case()
        self.now = 2800
        await self.worker.receive(self.event)
        self.assertEqual(self.store.get('10:1')['status'], 'expired')
        self.client.send_message.assert_not_awaited()
    async def test_uncertain_send_not_retried(self):
        await self.setup_case()
        self.client.send_message.side_effect = TimeoutError()
        await self.worker.receive(self.event)
        with self.assertLogs('attendance_reply', level='ERROR'):
            await asyncio.gather(*list(self.worker.tasks.values()))
        self.assertEqual(self.store.get('10:1')['status'], 'sending')
        await self.worker.receive(self.event)
        self.worker.resume()
        self.assertEqual(self.client.send_message.await_count, 1)
