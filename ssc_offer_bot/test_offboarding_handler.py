import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from approval_queue import select_pending
from onboarding_training import split_named_sections
from parsers import parse_kv_fields, get_field
from offboarding import (
    build_account_reclaim_text,
    classify_offboarding_sections,
    extract_offboarding_contact_tg,
    extract_offboarding_name,
    matches_offboarding_keyword,
)


SAMPLE_TEXT = """【离职确认】
花名：张三
编制组织：运营中心
离职原因：个人发展

【薪资结算】
应结工资：8000
工作TG：@zhangsan_work

【离职信息同步】
编号：HJXL001
花名：张三

【账号回收】
回收TG账号：@zhangsan

【面试评价】
工作表现良好，沟通顺畅。
"""

SAMPLE_TEXT_NO_ACCOUNT_RECLAIM = """【离职确认】
花名：李四
编制组织：技术中心

【薪资结算】
应结工资：9000
工作TG：@lisi_work

【离职信息同步】
编号：HJXL002
花名：李四
编制组织：技术中心
"""

TRIGGER_TEXT = "对张三提出离职申请"


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


class StopRetrying(BaseException):
    """测试用：让无限重试的轮询循环在断言完当前这一轮行为后停下来，
    避免真的在测试里等待/循环。"""


def make_fake_sleep(stop_after=None):
    """stop_after=None：sleep直接返回，不做等待，用于"重试几次后成功"的
    用例；stop_after=N：第N次调用后抛StopRetrying，用于断言"一直没找到，
    但已经按预期发过一次重试提示"这类无限轮询场景。"""
    calls = {"count": 0}

    async def fake_sleep(_seconds):
        calls["count"] += 1
        if stop_after is not None and calls["count"] >= stop_after:
            raise StopRetrying()

    return fake_sleep, calls


def base_config(**overrides):
    fields = dict(
        EXCLUDED_CHAT_IDS=frozenset(),
        OFFBOARDING_ENABLED=True,
        OFFBOARDING_RETRY_POLL_SECONDS=300,
        GROUP_LEADERSHIP=-1,
        GROUP_REGULARIZATION_SYNC=-2,
        GROUP_OFFBOARDING_BUSINESS_SYNC=-3,
        GROUP_ACCOUNT_REQUEST_WORK=-4,
        ALLOWED_DESTINATION_IDS={-1, -2, -3, -4},
        OFFBOARDING_FORWARD_APPROVAL_CODE='测试81',
        OFFBOARDING_SALARY_APPROVAL_CODE='测试82',
        OFFBOARDING_SYNC_APPROVAL_CODE='测试83',
        OFFBOARDING_ACCOUNT_RECLAIM_APPROVAL_CODE='测试84',
        APPROVAL_CODES=frozenset({'测试81', '测试82', '测试83', '测试84'}),
        OFFER_APPROVAL_CODE='测试1', ENVIRONMENT='test',
    )
    fields.update(overrides)
    return NS(**fields)


DEFAULT_APPROVAL_FORM_LINK = 'https://drive.google.com/file/d/default/view'


def build_env(sample_text=SAMPLE_TEXT, find_error=None, link=DEFAULT_APPROVAL_FORM_LINK,
              link_error=None,
              find_by_name=None, find_approval_form_link=None, fake_sleep=None,
              **overrides):
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'on_offboarding_trigger', 'queue_offboarding_private_message',
                                'queue_offboarding_sync_broadcast', 'get_ssc_reviewer',
                                'queue_group_message', 'on_ssc_send_approval', '_send_saved_text',
                                '_wait_for_offboarding_sync_file',
                                '_wait_for_offboarding_approval_form'}]
    for node in functions:
        node.decorator_list = []

    sent = []
    deleted = []

    async def send_message(destination, text, **kwargs):
        sent.append((destination, text, kwargs.get('file')))
        return NS(id=100 + len(sent))

    async def delete_messages(chat_id, ids):
        deleted.extend(ids)

    async def get_entity(username):
        return username

    me = NS(id=9, username='ffuuyao')
    client = NS(get_me=AsyncMock(return_value=me), send_message=send_message,
                get_messages=AsyncMock(), delete_messages=delete_messages,
                get_entity=get_entity)

    if find_by_name is None:
        def find_by_name(name):
            if find_error:
                raise find_error
            return sample_text, NS(get=lambda k: 'file-id')

    if find_approval_form_link is None:
        def find_approval_form_link(name):
            if link_error:
                raise link_error
            return link

    asyncio_ns = asyncio
    if fake_sleep is not None:
        class _AsyncioProxy:
            def __init__(self, real, sleep_fn):
                self._real = real
                self.sleep = sleep_fn

            def __getattr__(self, item):
                return getattr(self._real, item)

        asyncio_ns = _AsyncioProxy(asyncio, fake_sleep)

    env = dict(
        matches_offboarding_keyword=matches_offboarding_keyword,
        extract_offboarding_name=extract_offboarding_name,
        extract_offboarding_contact_tg=extract_offboarding_contact_tg,
        classify_offboarding_sections=classify_offboarding_sections,
        build_account_reclaim_text=build_account_reclaim_text,
        split_named_sections=split_named_sections,
        parse_kv_fields=parse_kv_fields, get_field=get_field,
        select_pending=select_pending,
        asyncio=asyncio_ns,
        log=logging.getLogger('test'),
        client=client,
        outbox=MemoryStore(), state=MemoryStore(), ssc_send_lock=asyncio.Lock(),
        offboarding_events=MemoryStore(), offboarding_lock=asyncio.Lock(),
        offboarding_drive=NS(find_by_name=find_by_name),
        offboarding_process_drive=NS(find_approval_form_link=find_approval_form_link),
        forward_onboarding_to_hrgs=AsyncMock(),
        config=base_config(),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
    env['_sent'] = sent
    env['_deleted'] = deleted
    env['_client'] = client
    return env


def trigger_event(msg_id=1, text=TRIGGER_TEXT, chat_id=-1):
    return NS(chat_id=chat_id, raw_text=text, message=NS(id=msg_id, raw_text=text))


def approve_event(code, approval_msg_id):
    return NS(chat_id=9, raw_text=code, is_private=True, sender_id=9,
              message=NS(id=approval_msg_id, reply_to_msg_id=None))


class OffboardingHandlerTests(IsolatedAsyncioTestCase):
    async def test_reference_section_sent_to_favorites_without_approval_code(self):
        env = build_env()
        await env['on_offboarding_trigger'](trigger_event())

        reference_texts = "\n".join(t for d, t, _f in env['_sent'] if d == 9)
        self.assertIn('面试评价', reference_texts)

        records = list(env['outbox'].all().values())
        self.assertFalse(any('工作表现良好' in r.get('candidate', '') for r in records))

    async def test_four_gated_sections_queued_with_independent_approval_codes(self):
        env = build_env()
        await env['on_offboarding_trigger'](trigger_event())

        records = list(env['outbox'].all().values())
        forward = next(r for r in records if r['approval_code'] == '测试81')
        salary = next(r for r in records if r['approval_code'] == '测试82')
        sync = next(r for r in records if r['approval_code'] == '测试83')
        reclaim = next(r for r in records if r['approval_code'] == '测试84')

        self.assertEqual(forward['destination'], -1)   # GROUP_LEADERSHIP
        self.assertEqual(sync['destinations'], [-2, -3])
        self.assertEqual(reclaim['destination'], -4)   # GROUP_ACCOUNT_REQUEST_WORK

        # 薪水结算走的是私聊，不受群白名单约束，目的地是员工本人工作TG。
        self.assertEqual(salary['destination'], '@zhangsan_work')

        self.assertTrue(forward['delete_draft_after_send'])
        self.assertTrue(salary['delete_draft_after_send'])
        self.assertTrue(sync['delete_draft_after_send'])
        self.assertTrue(reclaim['delete_draft_after_send'])

    async def test_account_reclaim_falls_back_to_built_text_when_section_missing(self):
        env = build_env(sample_text=SAMPLE_TEXT_NO_ACCOUNT_RECLAIM)
        await env['on_offboarding_trigger'](
            trigger_event(text='对李四提出离职申请')
        )
        reclaim = next(
            r for r in env['outbox'].all().values() if r['approval_code'] == '测试84'
        )
        draft_id = reclaim['draft_id']
        draft_text = next(t for d, t, _f in env['_sent'] if d == 9 and '员工帐号回收' in t)
        self.assertIn('花名：李四', draft_text)
        self.assertIn('编制组织：技术中心', draft_text)
        self.assertTrue(draft_id)

    async def test_missing_salary_contact_is_reported_instead_of_sent(self):
        text_no_contact = SAMPLE_TEXT.replace('工作TG：@zhangsan_work\n', '')
        env = build_env(sample_text=text_no_contact)
        await env['on_offboarding_trigger'](trigger_event())

        records = list(env['outbox'].all().values())
        self.assertFalse(any(r['approval_code'] == '测试82' for r in records))
        notice = "\n".join(t for d, t, _f in env['_sent'] if d == 9)
        self.assertIn('薪水结算信息', notice)
        self.assertIn('未找到员工本人工作TG', notice)

    async def test_approval_form_link_found_is_sent_to_favorites(self):
        env = build_env(link='https://drive.google.com/file/d/abc123/view')
        await env['on_offboarding_trigger'](trigger_event())

        notice = [t for d, t, _f in env['_sent'] if d == 9 and '员工离职审批表' in t]
        self.assertEqual(len(notice), 1)
        self.assertIn('https://drive.google.com/file/d/abc123/view', notice[0])

    async def test_approval_form_link_missing_retries_until_found(self):
        # 第一次、第二次查询都没找到，第三次才找到；期间应该只发一次"暂未
        # 找到，将重试"的提示，不刷屏，最终发一次带链接的通知。
        attempts = {"count": 0}

        def find_approval_form_link(name):
            attempts["count"] += 1
            if attempts["count"] < 3:
                return None
            return 'https://drive.google.com/file/d/xyz789/view'

        fake_sleep, sleep_calls = make_fake_sleep()
        env = build_env(find_approval_form_link=find_approval_form_link, fake_sleep=fake_sleep)
        await env['on_offboarding_trigger'](trigger_event())

        self.assertEqual(attempts["count"], 3)
        self.assertEqual(sleep_calls["count"], 2)
        waiting_notice = [t for d, t, _f in env['_sent'] if d == 9 and '暂未找到' in t and '离职审批表' in t]
        self.assertEqual(len(waiting_notice), 1)
        self.assertIn('自动重新查询', waiting_notice[0])
        found_notice = [t for d, t, _f in env['_sent'] if d == 9 and '员工离职审批表：' in t]
        self.assertEqual(len(found_notice), 1)
        self.assertIn('xyz789', found_notice[0])

    async def test_approval_form_link_still_missing_keeps_polling_without_spamming(self):
        fake_sleep, sleep_calls = make_fake_sleep(stop_after=3)
        env = build_env(link=None, fake_sleep=fake_sleep)
        with self.assertRaises(StopRetrying):
            await env['on_offboarding_trigger'](trigger_event())

        self.assertEqual(sleep_calls["count"], 3)
        waiting_notice = [t for d, t, _f in env['_sent'] if d == 9 and '暂未找到' in t and '离职审批表' in t]
        self.assertEqual(len(waiting_notice), 1)

    async def test_sync_file_not_found_notifies_once_then_retries_until_found(self):
        attempts = {"count": 0}

        def find_by_name(name):
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise FileNotFoundError("未找到")
            return SAMPLE_TEXT, NS(get=lambda k: 'file-id')

        fake_sleep, sleep_calls = make_fake_sleep()
        env = build_env(find_by_name=find_by_name, fake_sleep=fake_sleep)
        await env['on_offboarding_trigger'](trigger_event())

        self.assertEqual(attempts["count"], 2)
        self.assertEqual(sleep_calls["count"], 1)
        waiting_notice = [t for d, t, _f in env['_sent'] if d == 9 and '同步文件暂未找到' in t]
        self.assertEqual(len(waiting_notice), 1)
        self.assertIn('自动重新查询', waiting_notice[0])

        # 找到之后要继续走完整个流程，不是只报个"找到了"就结束。
        records = list(env['outbox'].all().values())
        self.assertTrue(any(r['approval_code'] == '测试81' for r in records))
        record = env['offboarding_events'].get('-1:1')
        self.assertEqual(record['status'], 'queued')

    async def test_sync_file_still_missing_keeps_polling_without_failing(self):
        fake_sleep, sleep_calls = make_fake_sleep(stop_after=2)
        env = build_env(find_error=FileNotFoundError('未找到'), fake_sleep=fake_sleep)
        with self.assertRaises(StopRetrying):
            await env['on_offboarding_trigger'](trigger_event())

        self.assertEqual(sleep_calls["count"], 2)
        waiting_notice = [t for d, t, _f in env['_sent'] if d == 9 and '同步文件暂未找到' in t]
        self.assertEqual(len(waiting_notice), 1)
        record = env['offboarding_events'].get('-1:1')
        self.assertEqual(record['status'], 'waiting_sync_file')
        # 没找到不算失败，不应该报"处理失败"。
        self.assertFalse(any('处理失败' in t for d, t, _f in env['_sent']))

    async def test_genuine_drive_error_still_fails_immediately_without_retry(self):
        # 未按【段落名】分区这种真错误（不是"文件还没上传"）不该被当成待重
        # 试，要立刻报失败，和此前行为一致。
        env = build_env(find_error=ValueError('鉴权失败'))
        await env['on_offboarding_trigger'](trigger_event())

        self.assertEqual(len(env['_sent']), 1)
        self.assertEqual(env['_sent'][0][0], 9)
        self.assertIn('处理失败', env['_sent'][0][1])
        record = env['offboarding_events'].get('-1:1')
        self.assertEqual(record['status'], 'failed')

    async def test_approving_forward_code_sends_to_leadership_and_deletes_draft(self):
        env = build_env()
        await env['on_offboarding_trigger'](trigger_event())
        draft_id = next(
            r['draft_id'] for r in env['outbox'].all().values()
            if r['approval_code'] == '测试81'
        )
        env['_client'].get_messages = AsyncMock(
            return_value=NS(id=draft_id, raw_text='花名：张三（已核对）', media=None)
        )
        await env['on_ssc_send_approval'](approve_event('测试81', 1000))

        forwarded = [t for d, t, _f in env['_sent'] if d == -1]
        self.assertEqual(len(forwarded), 1)
        self.assertIn('已核对', forwarded[0])
        self.assertIn(draft_id, env['_deleted'])

    async def test_approving_salary_code_sends_private_message_and_deletes_draft(self):
        env = build_env()
        await env['on_offboarding_trigger'](trigger_event())
        draft_id = next(
            r['draft_id'] for r in env['outbox'].all().values()
            if r['approval_code'] == '测试82'
        )
        env['_client'].get_messages = AsyncMock(
            return_value=NS(id=draft_id, raw_text='应结工资：8000（已核对）', media=None)
        )
        await env['on_ssc_send_approval'](approve_event('测试82', 1001))

        forwarded = [t for d, t, _f in env['_sent'] if d == '@zhangsan_work']
        self.assertEqual(len(forwarded), 1)
        self.assertIn(draft_id, env['_deleted'])

    async def test_approving_sync_code_sends_to_both_groups_and_deletes_draft(self):
        env = build_env()
        await env['on_offboarding_trigger'](trigger_event())
        draft_id = next(
            r['draft_id'] for r in env['outbox'].all().values()
            if r['approval_code'] == '测试83'
        )
        env['_client'].get_messages = AsyncMock(
            return_value=NS(id=draft_id, raw_text='编号：HJXL001（已核对）', media=None)
        )
        await env['on_ssc_send_approval'](approve_event('测试83', 1002))

        forwarded_sync = [t for d, t, _f in env['_sent'] if d == -2]
        forwarded_business = [t for d, t, _f in env['_sent'] if d == -3]
        self.assertEqual(len(forwarded_sync), 1)
        self.assertEqual(len(forwarded_business), 1)
        self.assertIn(draft_id, env['_deleted'])

    async def test_approving_account_reclaim_code_sends_to_work_group_and_deletes_draft(self):
        env = build_env()
        await env['on_offboarding_trigger'](trigger_event())
        draft_id = next(
            r['draft_id'] for r in env['outbox'].all().values()
            if r['approval_code'] == '测试84'
        )
        env['_client'].get_messages = AsyncMock(
            return_value=NS(id=draft_id, raw_text='【员工帐号回收】（已核对）', media=None)
        )
        await env['on_ssc_send_approval'](approve_event('测试84', 1003))

        forwarded = [t for d, t, _f in env['_sent'] if d == -4]
        self.assertEqual(len(forwarded), 1)
        self.assertIn(draft_id, env['_deleted'])

    async def test_no_keyword_is_ignored(self):
        env = build_env()
        await env['on_offboarding_trigger'](trigger_event(text='今天天气不错'))
        self.assertEqual(env['_sent'], [])

    async def test_non_leadership_group_is_ignored(self):
        env = build_env()
        await env['on_offboarding_trigger'](trigger_event(chat_id=-999))
        self.assertEqual(env['_sent'], [])

    async def test_missing_name_is_ignored_without_error(self):
        env = build_env()
        await env['on_offboarding_trigger'](trigger_event(text='劝退申请'))
        self.assertEqual(env['_sent'], [])

    async def test_disabled_when_not_enabled(self):
        env = build_env(config=base_config(OFFBOARDING_ENABLED=False))
        await env['on_offboarding_trigger'](trigger_event())
        self.assertEqual(env['_sent'], [])

    async def test_duplicate_trigger_while_waiting_for_sync_file_is_ignored(self):
        fake_sleep, sleep_calls = make_fake_sleep(stop_after=1)
        env = build_env(find_error=FileNotFoundError('未找到'), fake_sleep=fake_sleep)
        with self.assertRaises(StopRetrying):
            await env['on_offboarding_trigger'](trigger_event())

        # 同一条触发消息（同chat_id+msg_id）在还在等待重试时再次派发
        # （比如断线重连重放历史消息），不应该重新发起一轮查找/提示。
        sent_before = len(env['_sent'])
        await env['on_offboarding_trigger'](trigger_event())
        self.assertEqual(len(env['_sent']), sent_before)

    async def test_duplicate_trigger_while_waiting_for_approval_form_is_ignored(self):
        fake_sleep, sleep_calls = make_fake_sleep(stop_after=1)
        env = build_env(link=None, fake_sleep=fake_sleep)
        with self.assertRaises(StopRetrying):
            await env['on_offboarding_trigger'](trigger_event())

        record = env['offboarding_events'].get('-1:1')
        self.assertEqual(record['status'], 'waiting_approval_form')

        # 同一条触发消息还在等审批表重试时再次派发，不应该重新跑一遍整个
        # 流程（不会重新排队四段信息、不会重复发送提示）。
        sent_before = len(env['_sent'])
        await env['on_offboarding_trigger'](trigger_event())
        self.assertEqual(len(env['_sent']), sent_before)


if __name__ == '__main__':
    import unittest
    unittest.main()
