"""指定机器人私聊查岗提醒；持久化延时任务，结果不确定时不重发。"""
import asyncio
import logging
import random
import re
import time

log = logging.getLogger(__name__)
BOT_USERNAME = 'chagang123bot'


def parse_reminder(text):
    if '查岗提醒' not in (text or ''):
        return None
    match = re.search(r'请在\s*(\d+)\s*分钟内回复以下关键词[^\n]*[：:]\s*\n+\s*【([^【】\n]+)】', text)
    if not match:
        return None
    keyword = match.group(2).strip()
    minutes = int(match.group(1))
    if not keyword or len(keyword) > 32 or not 1 <= minutes <= 120:
        return None
    return keyword, minutes * 60


class AttendanceReplies:
    def __init__(self, client, store, *, clock=time.time, randint=random.randint, sleep=asyncio.sleep):
        self.client, self.store = client, store
        self.clock, self.randint, self.sleep = clock, randint, sleep
        self.lock = asyncio.Lock()
        self.tasks = {}

    def schedule(self, key):
        if key not in self.tasks:
            task = asyncio.create_task(self.deliver(key))
            self.tasks[key] = task
            task.add_done_callback(lambda done: self.tasks.pop(key, None))

    async def receive(self, event):
        if not event.is_private or event.out:
            return
        sender = await event.get_sender()
        if (not getattr(sender, 'bot', False)
                or (getattr(sender, 'username', '') or '').casefold() != BOT_USERNAME
                or event.chat_id != sender.id
                or getattr(event.message, 'fwd_from', None)):
            return
        parsed = parse_reminder(event.raw_text)
        if parsed is None:
            return
        keyword, duration = parsed
        key = f'{event.chat_id}:{event.message.id}'
        async with self.lock:
            if self.store.get(key):
                return
            now = self.clock()
            deadline = event.message.date.timestamp() + duration
            delay = self.randint(180, 600)
            if now + delay >= deadline:
                self.store.set(key, {'status': 'expired'})
                return
            self.store.set(key, dict(status='pending', chat_id=sender.id,
                                    message_id=event.message.id, keyword=keyword,
                                    due=now + delay, deadline=deadline))
            log.info('[查岗] 消息%s已安排，延迟%s秒', event.message.id, delay)
            self.schedule(key)

    async def deliver(self, key):
        try:
            record = self.store.get(key)
            await self.sleep(max(0, record['due'] - self.clock()))
            async with self.lock:
                record = self.store.get(key)
                if record['status'] != 'pending':
                    return
                if self.clock() >= record['deadline']:
                    self.store.update(key, status='expired')
                    return
                original = await self.client.get_messages(record['chat_id'], ids=record['message_id'])
                if not original or parse_reminder(original.raw_text) != (record['keyword'], int(record['deadline'] - original.date.timestamp())):
                    self.store.update(key, status='changed_or_deleted')
                    return
                # 手工已回复关键词时取消自动回复。
                async for message in self.client.iter_messages(record['chat_id'], min_id=record['message_id']):
                    if message.out and (message.raw_text or '').strip() == record['keyword']:
                        self.store.update(key, status='answered_manually')
                        return
                if self.clock() >= record['deadline']:
                    self.store.update(key, status='expired')
                    return
                self.store.update(key, status='sending')
                sent = await self.client.send_message(record['chat_id'], record['keyword'],
                                                      reply_to=record['message_id'], parse_mode=None)
                self.store.update(key, status='sent', sent_id=sent.id)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception('[查岗] 任务%s失败；发送结果不明时不自动重试', key)

    def resume(self):
        for key, record in self.store.all().items():
            if record.get('status') == 'pending':
                self.schedule(key)

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
