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
    build_regularization_messages,
    names_from_trigger,
    regularization_trigger_scope,
    split_sections,
    trigger_keyword_matches,
)


MONTHLY_TEXT = """【转正申请】
————
【效能中心-试用员工转正申请】
花名：清衡
编号：NX0393
旧版本
————
【效能中心-试用员工转正申请】
花名：清衡
编号：NX0393
新版本

【转正信息同步】
————
编号：NX0393
花名：清衡
岗位：前端工程师

【转正通知】
————
祝贺 清衡 @qingheng，表现优秀，通过试用期考核评估。

【预转正提醒】
————
【效能中心-恒睿公司-新人预转正提醒】
花名：清衡
编号：NX0393
以上员工试用期即将届满。
————
如需延期，请告知预计转正日期。
"""

TRIGGER_TEXT = "转正提醒-恒睿-转正倒数4天 清衡"


class MemoryStore:
    """最小可用的状态存储替身，行为对齐 state_store.StateStore 的读写接口。"""

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
        EXCLUDED_CHAT_IDS=frozenset(), ALLOW_MANUAL_TRIGGERS=True,
        REGULARIZATION_TRIGGER_BOT_ID=8416618309,
        REGULARIZATION_TRIGGER_KEYWORD='转正提醒-恒睿-转正倒数4天',
        DAILY_REPORT_TIMEZONE='Asia/Shanghai',
        GROUP_LEADERSHIP=-1,
        ALLOWED_DESTINATION_IDS={-1},
        REGULARIZATION_APPROVAL_CODE='测试2',
        REGULARIZATION_APPLICATION_APPROVAL_CODE='测试21',
        APPROVAL_CODES=frozenset({'测试2', '测试21'}),
        OFFER_APPROVAL_CODE='测试1', ENVIRONMENT='test',
    )
    fields.update(overrides)
    return NS(**fields)


def build_env(monthly_text=MONTHLY_TEXT, **overrides):
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'on_regularization_trigger', 'get_ssc_reviewer',
                                'queue_group_message', 'on_ssc_send_approval',
                                '_send_saved_text'}]
    for node in functions:
        node.decorator_list = []

    sent = []

    async def send_message(destination, text, **kwargs):
        sent.append((destination, text, kwargs.get('file')))
        return NS(id=100 + len(sent))

    me = NS(id=9, username='ffuuyao')
    client = NS(get_me=AsyncMock(return_value=me), send_message=send_message,
                get_messages=AsyncMock())

    env = dict(
        build_regularization_messages=build_regularization_messages,
        names_from_trigger=names_from_trigger,
        regularization_trigger_scope=regularization_trigger_scope,
        split_sections=split_sections,
        trigger_keyword_matches=trigger_keyword_matches,
        select_pending=select_pending,
        unicodedata=unicodedata, asyncio=asyncio,
        log=logging.getLogger('test'),
        client=client,
        outbox=MemoryStore(), state=MemoryStore(), ssc_send_lock=asyncio.Lock(),
        regularization_events=MemoryStore(), regularization_lock=asyncio.Lock(),
        regularization_drive=NS(
            load_month=lambda day: (monthly_text, NS(get=lambda k: 'file-id')),
        ),
        forward_onboarding_to_hrgs=AsyncMock(),
        config=base_config(),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
    env['_sent'] = sent
    env['_client'] = client
    return env


def trigger_event(msg_id=1):
    return NS(chat_id=-1, sender_id=8416618309, raw_text=TRIGGER_TEXT,
              message=NS(id=msg_id))


def approve_event(code, approval_msg_id):
    return NS(chat_id=9, raw_text=code, is_private=True, sender_id=9,
              message=NS(id=approval_msg_id, reply_to_msg_id=None))


class RegularizationApplicationTests(IsolatedAsyncioTestCase):
    async def test_application_and_reminder_are_queued_as_separate_drafts(self):
        env = build_env()
        await env['on_regularization_trigger'](trigger_event())

        # 参考资料(转正信息同步/转正通知)不带审批码，转正申请与预转正提醒
        # 各自带独立审批码，全部先进SSC收藏夹(reviewer.id=9)。
        self.assertTrue(all(dest == 9 for dest, _text, _file in env['_sent']))

        records = list(env['outbox'].all().values())
        application_record = next(r for r in records if r['approval_code'] == '测试21')
        reminder_record = next(r for r in records if r['approval_code'] == '测试2')
        self.assertEqual(application_record['destination'], -1)
        self.assertEqual(reminder_record['destination'], -1)
        # 转正申请只保留最新版本，不包含被覆盖的旧版本。
        application_text = next(t for _d, t, _f in env['_sent'] if '新版本' in t)
        self.assertIn('花名：清衡', application_text)
        self.assertNotIn('旧版本', application_text)

    async def test_approving_application_code_sends_latest_edited_content(self):
        env = build_env()
        await env['on_regularization_trigger'](trigger_event())
        application_draft_id = next(
            r['draft_id'] for r in env['outbox'].all().values()
            if r['approval_code'] == '测试21'
        )

        # SSC 在收藏夹里发现内容有误，批准前先编辑了草稿。
        edited_text = "【效能中心-试用员工转正申请】\n花名：清衡\n编号：NX0393\n新版本（已修正薪资）"
        env['_client'].get_messages = AsyncMock(
            return_value=NS(id=application_draft_id, raw_text=edited_text, media=None)
        )

        await env['on_ssc_send_approval'](approve_event('测试21', 1000))

        forwarded = [t for d, t, _f in env['_sent'] if d == -1]
        self.assertEqual(len(forwarded), 1)
        self.assertEqual(forwarded[0], edited_text)
        self.assertIn('已修正薪资', forwarded[0])

    async def test_application_approval_does_not_consume_reminder_draft(self):
        env = build_env()
        await env['on_regularization_trigger'](trigger_event())

        await env['on_ssc_send_approval'](approve_event('测试21', 1000))
        self.assertEqual([d for d, _t, _f in env['_sent'] if d == -1], [-1])

        reminder_record = next(
            r for r in env['outbox'].all().values() if r['approval_code'] == '测试2'
        )
        self.assertEqual(reminder_record['status'], 'pending')

        await env['on_ssc_send_approval'](approve_event('测试2', 2000))
        self.assertEqual([d for d, _t, _f in env['_sent'] if d == -1], [-1, -1])

    async def test_missing_application_section_marks_event_failed(self):
        broken_text = MONTHLY_TEXT.replace(
            "【转正申请】\n"
            "————\n"
            "【效能中心-试用员工转正申请】\n"
            "花名：清衡\n"
            "编号：NX0393\n"
            "旧版本\n"
            "————\n"
            "【效能中心-试用员工转正申请】\n"
            "花名：清衡\n"
            "编号：NX0393\n"
            "新版本\n\n",
            "",
        )
        env = build_env(monthly_text=broken_text)
        await env['on_regularization_trigger'](trigger_event())

        record = env['regularization_events'].get('-1:1')
        self.assertEqual(record['status'], 'failed')
        self.assertIn('转正申请', record['reason'])
        # 失败时不应该有任何草稿被发到收藏夹之外的群。
        self.assertTrue(all(dest == 9 for dest, _t, _f in env['_sent']))


if __name__ == '__main__':
    import unittest
    unittest.main()
