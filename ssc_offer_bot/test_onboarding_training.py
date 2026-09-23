import ast
import asyncio
import logging
import re
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from approval_queue import select_pending
from regularization import match_department_group
from onboarding_training import GATED_SECTION_NAMES, split_named_sections


SAMPLE_TEXT = """【新人入职通知】
祝贺 阿林 @alin65175 顺利完成新人培训考核，正式入职恒睿公司！

【入职信息同步】
部门-小组：技术中心-研发部
编号：YY2201
花名：阿林
岗位：后端工程师
入职日期：2026-09-20

【欢迎】
欢迎 阿林 加入技术/效能部大家庭，祝工作顺利！

【面试评价】
逻辑清晰，基础扎实，建议关注后端框架深入学习。

【入职登记信息】
身份证号：已核验
银行卡号：已核验
"""

TRIGGER_TEXT = "新人培训考试通过 @alin65175 @ffuuyao"

GROUP_RULES = [
    {"name": "测试-技术效能", "keywords": ["技术部", "效能部", "技术效能部", "技术中心", "研发部"],
     "chat_id": -5412973830},
]


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
        GROUP_TRAINING=-5000000001,
        ONBOARDING_TRAINING_ENABLED=True,
        ONBOARDING_TRAINING_TRIGGER_KEYWORD='新人培训考试通过',
        GROUP_LEADERSHIP=-1,
        GROUP_REGULARIZATION_SYNC=-2,
        ANNIVERSARY_GROUP_RULES=GROUP_RULES,
        ALLOWED_DESTINATION_IDS={-1, -2, -5412973830},
        ONBOARDING_TRAINING_NOTICE_APPROVAL_CODE='测试6',
        ONBOARDING_TRAINING_SYNC_APPROVAL_CODE='测试6.1',
        ONBOARDING_TRAINING_WELCOME_APPROVAL_CODE='测试6.2',
        APPROVAL_CODES=frozenset({'测试6', '测试6.1', '测试6.2'}),
        OFFER_APPROVAL_CODE='测试1', ENVIRONMENT='test',
    )
    fields.update(overrides)
    return NS(**fields)


def build_env(sample_text=SAMPLE_TEXT, **overrides):
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'on_onboarding_training_passed', 'get_ssc_reviewer',
                                'queue_group_message', 'on_ssc_send_approval',
                                '_send_saved_text'}]
    plain_functions = [n for n in source.body if isinstance(n, ast.FunctionDef)
                        and n.name in {'_training_target_username'}]
    for node in functions + plain_functions:
        node.decorator_list = []

    sent = []
    deleted = []

    async def send_message(destination, text, **kwargs):
        sent.append((destination, text, kwargs.get('file')))
        return NS(id=100 + len(sent))

    async def delete_messages(chat_id, ids):
        deleted.extend(ids)

    me = NS(id=9, username='ffuuyao')
    client = NS(get_me=AsyncMock(return_value=me), send_message=send_message,
                get_messages=AsyncMock(), delete_messages=delete_messages)

    def mentions_ssc(message):
        return bool(re.search(r'(?<![A-Za-z0-9_@])@(?:ffuuyao|oiyr90557)(?![A-Za-z0-9_])',
                               getattr(message, 'raw_text', '') or '', re.I))

    env = dict(
        GATED_SECTION_NAMES=GATED_SECTION_NAMES,
        split_named_sections=split_named_sections,
        match_department_group=match_department_group,
        mentions_ssc=mentions_ssc,
        select_pending=select_pending,
        re=re, asyncio=asyncio,
        log=logging.getLogger('test'),
        client=client,
        outbox=MemoryStore(), state=MemoryStore(), ssc_send_lock=asyncio.Lock(),
        onboarding_training_events=MemoryStore(), onboarding_training_lock=asyncio.Lock(),
        onboarding_training_drive=NS(
            find_by_username=lambda username: (sample_text, NS(get=lambda k: 'file-id')),
        ),
        forward_onboarding_to_hrgs=AsyncMock(),
        config=base_config(),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions + plain_functions, type_ignores=[]),
                 'main.py', 'exec'), env)
    env['_sent'] = sent
    env['_deleted'] = deleted
    env['_client'] = client
    return env


def trigger_event(msg_id=1, text=TRIGGER_TEXT, chat_id=-5000000001):
    return NS(chat_id=chat_id, raw_text=text, message=NS(id=msg_id, raw_text=text))


def approve_event(code, approval_msg_id):
    return NS(chat_id=9, raw_text=code, is_private=True, sender_id=9,
              message=NS(id=approval_msg_id, reply_to_msg_id=None))


class OnboardingTrainingTests(IsolatedAsyncioTestCase):
    async def test_reference_sections_sent_to_favorites_without_approval_code(self):
        env = build_env()
        await env['on_onboarding_training_passed'](trigger_event())

        # 所有内容(参考资料+待审批草稿)都先进SSC收藏夹(reviewer.id=9)。
        self.assertTrue(all(dest == 9 for dest, _text, _file in env['_sent']))

        reference_texts = "\n".join(t for _d, t, _f in env['_sent'])
        self.assertIn('面试评价', reference_texts)
        self.assertIn('入职登记信息', reference_texts)

        records = list(env['outbox'].all().values())
        # 参考资料不应该出现在需要审批放行的草稿队列里。
        self.assertFalse(any('逻辑清晰' in r.get('candidate', '') for r in records))

    async def test_three_gated_sections_queued_with_independent_approval_codes(self):
        env = build_env()
        await env['on_onboarding_training_passed'](trigger_event())

        records = list(env['outbox'].all().values())
        notice = next(r for r in records if r['approval_code'] == '测试6')
        sync = next(r for r in records if r['approval_code'] == '测试6.1')
        welcome = next(r for r in records if r['approval_code'] == '测试6.2')

        self.assertEqual(notice['destination'], -1)   # GROUP_LEADERSHIP
        self.assertEqual(sync['destination'], -2)      # GROUP_REGULARIZATION_SYNC
        self.assertEqual(welcome['destination'], -5412973830)  # 技术/效能部全员群

        self.assertTrue(notice['delete_draft_after_send'])
        self.assertTrue(sync['delete_draft_after_send'])
        self.assertTrue(welcome['delete_draft_after_send'])

    async def test_approving_each_code_forwards_and_deletes_favorites_draft(self):
        env = build_env()
        await env['on_onboarding_training_passed'](trigger_event())

        draft_id = next(
            r['draft_id'] for r in env['outbox'].all().values()
            if r['approval_code'] == '测试6'
        )
        env['_client'].get_messages = AsyncMock(
            return_value=NS(id=draft_id, raw_text='祝贺 阿林 顺利入职（已核对）', media=None)
        )
        await env['on_ssc_send_approval'](approve_event('测试6', 1000))

        forwarded = [t for d, t, _f in env['_sent'] if d == -1]
        self.assertEqual(len(forwarded), 1)
        self.assertIn('已核对', forwarded[0])
        self.assertIn(draft_id, env['_deleted'])

    async def test_welcome_routes_by_department_from_sync_section(self):
        env = build_env()
        await env['on_onboarding_training_passed'](trigger_event())

        welcome = next(
            r for r in env['outbox'].all().values()
            if r['approval_code'] == '测试6.2'
        )
        self.assertEqual(welcome['destination'], -5412973830)

    async def test_missing_username_is_ignored_without_error(self):
        env = build_env()
        await env['on_onboarding_training_passed'](
            trigger_event(text='新人培训考试通过 @ffuuyao')
        )
        self.assertEqual(env['_sent'], [])

    async def test_non_training_group_message_is_ignored(self):
        env = build_env()
        await env['on_onboarding_training_passed'](
            trigger_event(chat_id=-999)
        )
        self.assertEqual(env['_sent'], [])

    async def test_disabled_when_group_training_not_configured(self):
        env = build_env(config=base_config(ONBOARDING_TRAINING_ENABLED=False))
        await env['on_onboarding_training_passed'](trigger_event())
        self.assertEqual(env['_sent'], [])


if __name__ == '__main__':
    import unittest
    unittest.main()
