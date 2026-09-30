import ast
import asyncio
import logging
import random
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from account_application import (
    account_application_reason,
    account_application_text_from_onboarding,
    build_account_application_text,
    is_tech_department,
    merge_rosters,
    needs_account_application,
    parse_roster_date,
    parse_roster_rows,
)
from approval_queue import select_pending
from parsers import get_field, parse_kv_fields


def roster_sheet_rows(*data_rows):
    title_row = ["在职花名册"]
    group_header_row = ["基础身份"]
    field_header_row = ["序号", "员工编码（新）", "花名*", "姓名/简历名（选填）",
                         "在职状态*", "生效日期（入/调）"]
    return [title_row, group_header_row, field_header_row, *data_rows]


def data_row(*, employee_code="", name="", resume_name="", effective_date="",
             org_unit="", service_unit="", department="", work_tg="", personal_contact=""):
    cells = ["" for _ in range(31)]
    cells[1] = employee_code
    cells[2] = name
    cells[3] = resume_name
    cells[5] = effective_date
    cells[11] = org_unit
    cells[13] = service_unit
    cells[14] = department
    cells[29] = work_tg
    cells[30] = personal_contact
    return cells


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


class FakeDateTime:
    """冻结 on_ssc_account_application_trigger 里 datetime.now(...).date() 用到
    的"今天"，让草稿里"申请日期"字段的值在测试里确定、不随容器实际时钟
    漂移（生效日期筛选现在只看cutover_date，不再依赖"今天"，但"申请日期"
    字段仍然要填"今天"）。datetime.strptime 原样转发给真正的 datetime，
    因为解析cutover日期字符串不需要冻结。
    """
    _fixed_now = datetime(2026, 10, 10, 12, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls._fixed_now.replace(tzinfo=tz) if tz is not None else cls._fixed_now

    @staticmethod
    def strptime(date_string, fmt):
        return datetime.strptime(date_string, fmt)


def base_config(**overrides):
    fields = dict(
        EXCLUDED_CHAT_IDS=frozenset(),
        ACCOUNT_APPLICATION_ENABLED=True,
        ACCOUNT_APPLICATION_TRIGGER_KEYWORD="帐号申请",
        ACCOUNT_APPLICATION_APPROVAL_CODE="测试111",
        ACCOUNT_APPLICATION_TECH_DEPARTMENTS=("研发部", "效能部"),
        ACCOUNT_APPLICATION_CUTOVER_DATE="2026-10-01",
        ACCOUNT_APPLICATION_MIN_DAYS_SINCE_EFFECTIVE=6,
        ACCOUNT_APPLICATION_FROM_ONBOARDING_ENABLED=True,
        DAILY_REPORT_TIMEZONE="Asia/Shanghai",
        GROUP_LEADERSHIP=-100111,
        GROUP_ACCOUNT_REQUEST_WORK=-5309896717,
        ALLOWED_DESTINATION_IDS={-5309896717},
        APPROVAL_CODES=frozenset({"测试1"}),
        OFFER_APPROVAL_CODE="测试1",
        PRE_ONBOARDING_APPROVAL_CODE="测试11",
        ENVIRONMENT="test",
    )
    fields.update(overrides)
    return NS(**fields)


def build_env(*, primary_rows, secondary_rows, load_error=None, **overrides):
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'on_ssc_account_application_trigger',
                                'on_ssc_account_application_release',
                                'get_ssc_reviewer', 'queue_group_message'}]
    for node in functions:
        node.decorator_list = []

    sent = []

    async def send_message(destination, text, **kwargs):
        sent.append((destination, text, kwargs.get('file')))
        return NS(id=100 + len(sent))

    me = NS(id=9, username='ffuuyao')

    def load_rosters():
        if load_error:
            raise load_error
        return primary_rows, secondary_rows

    client = NS(
        get_me=AsyncMock(return_value=me),
        send_message=send_message,
        get_messages=AsyncMock(),
        delete_messages=AsyncMock(),
    )

    env = dict(
        account_application_reason=account_application_reason,
        build_account_application_text=build_account_application_text,
        is_tech_department=is_tech_department,
        merge_rosters=merge_rosters,
        needs_account_application=needs_account_application,
        parse_roster_date=parse_roster_date,
        parse_roster_rows=parse_roster_rows,
        select_pending=select_pending,
        asyncio=asyncio, random=random, datetime=FakeDateTime, ZoneInfo=ZoneInfo,
        log=logging.getLogger('test'),
        client=client,
        outbox=MemoryStore(), state=MemoryStore(),
        ssc_send_lock=asyncio.Lock(), account_application_lock=asyncio.Lock(),
        account_application_sheets=NS(load_rosters=load_rosters),
        config=base_config(),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
    env['_sent'] = sent
    env['_client'] = client
    return env


def fav_event(text, msg_id=1):
    return NS(chat_id=9, is_private=True, sender_id=9, raw_text=text,
              message=NS(id=msg_id))


def onboarding_message(text, msg_id=1, sender_id=9):
    return NS(raw_text=text, id=msg_id, sender_id=sender_id)


def build_onboarding_env(**overrides):
    """给 forward_onboarding_to_account_application 单独搭一套执行环境：跟
    build_env() 提取的handler不同，这个函数依赖 queue_group_message、
    parse_kv_fields/get_field、account_application_text_from_onboarding，
    以及一份独立的去重StateStore（account_application_onboarding_forwards）
    和锁，跟花名册扫描那条路径完全不共用状态。
    """
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'forward_onboarding_to_account_application',
                                'get_ssc_reviewer', 'queue_group_message'}]
    for node in functions:
        node.decorator_list = []

    sent = []

    async def send_message(destination, text, **kwargs):
        sent.append((destination, text, kwargs.get('file')))
        return NS(id=100 + len(sent))

    me = NS(id=9, username='ffuuyao')

    client = NS(
        get_me=AsyncMock(return_value=me),
        send_message=send_message,
        get_messages=AsyncMock(),
        delete_messages=AsyncMock(),
    )

    env = dict(
        account_application_text_from_onboarding=account_application_text_from_onboarding,
        parse_kv_fields=parse_kv_fields, get_field=get_field,
        select_pending=select_pending,
        asyncio=asyncio, datetime=FakeDateTime, ZoneInfo=ZoneInfo,
        log=logging.getLogger('test'),
        client=client,
        outbox=MemoryStore(), state=MemoryStore(),
        ssc_send_lock=asyncio.Lock(),
        account_application_onboarding_forwards=MemoryStore(),
        account_application_onboarding_lock=asyncio.Lock(),
        config=base_config(),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
    env['_sent'] = sent
    env['_client'] = client
    return env


class ForwardOnboardingToAccountApplicationTests(IsolatedAsyncioTestCase):
    """联合管理群贴出入职信息确认后，入职部门是研发部/效能部时直接生成一条
    【员工账号申请】草稿，复用预入职登记的审批码(测试11/11)放行到工作帐号
    需求群-SSC3组——这条路径完全独立于花名册扫描(帐号申请自动化)，不看
    生效日期/天数。
    """

    def _text(self, **fields):
        defaults = {
            "候选人编码": "DN6284",
            "候选人姓名": "木梨",
            "简历名": "muli",
            "入职编制组织": "技术中心",
            "入职服务单位": "恒睿",
            "入职部门": "效能部",
            "候选人联系方式": "@muli_q",
        }
        defaults.update(fields)
        return "【入职信息确认】\n" + "\n".join(f"{k}：{v}" for k, v in defaults.items())

    async def test_tech_department_queues_draft_with_pre_onboarding_code(self):
        env = build_onboarding_env()
        await env['forward_onboarding_to_account_application'](
            onboarding_message(self._text()), -100111,
        )
        drafts = [t for d, t, _f in env['_sent'] if d == 9]
        self.assertEqual(len(drafts), 1)
        self.assertTrue(drafts[0].startswith('【员工账号申请】'))
        self.assertIn('编号：DN6284', drafts[0])
        self.assertIn('花名：木梨', drafts[0])
        self.assertIn('简历名：muli', drafts[0])
        self.assertIn('需求：TG×1、邮箱×1', drafts[0])
        self.assertIn('联系TG：@muli_q', drafts[0])

        records = [r for r in env['outbox'].all().values()
                   if r['kind'] == 'account_application_onboarding']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['destination'], -5309896717)
        self.assertEqual(records[0]['approval_code'], '测试11')

    async def test_non_tech_department_does_not_queue(self):
        env = build_onboarding_env()
        await env['forward_onboarding_to_account_application'](
            onboarding_message(self._text(入职部门="运营1部")), -100111,
        )
        self.assertEqual(env['_sent'], [])
        self.assertEqual(env['outbox'].all(), {})

    async def test_disabled_flag_skips(self):
        env = build_onboarding_env(
            config=base_config(ACCOUNT_APPLICATION_FROM_ONBOARDING_ENABLED=False)
        )
        await env['forward_onboarding_to_account_application'](
            onboarding_message(self._text()), -100111,
        )
        self.assertEqual(env['_sent'], [])

    async def test_other_chat_is_ignored(self):
        env = build_onboarding_env()
        await env['forward_onboarding_to_account_application'](
            onboarding_message(self._text()), -999,
        )
        self.assertEqual(env['_sent'], [])

    async def test_message_without_keyword_is_ignored(self):
        env = build_onboarding_env()
        await env['forward_onboarding_to_account_application'](
            onboarding_message("跟入职确认无关的一条消息"), -100111,
        )
        self.assertEqual(env['_sent'], [])

    async def test_message_from_other_sender_is_ignored(self):
        # 只处理登录账号自己发布的入职确认，不是别人在联合管理群发的其他消息。
        env = build_onboarding_env()
        await env['forward_onboarding_to_account_application'](
            onboarding_message(self._text(), sender_id=42), -100111,
        )
        self.assertEqual(env['_sent'], [])

    async def test_duplicate_message_is_not_queued_twice(self):
        env = build_onboarding_env()
        msg = onboarding_message(self._text(), msg_id=7)
        await env['forward_onboarding_to_account_application'](msg, -100111)
        await env['forward_onboarding_to_account_application'](msg, -100111)
        drafts = [t for d, t, _f in env['_sent'] if d == 9]
        self.assertEqual(len(drafts), 1)


class AccountApplicationTriggerTests(IsolatedAsyncioTestCase):
    def setUp(self):
        # 冻结"今天"=2026-10-10（见FakeDateTime）。cutover=2026-10-01和
        # min_days=6两个条件都要满足：生效日期"2026-10-01"距今天10-10正好
        # 9天，两条都满足。
        # 廖伊波：效能部，生效日期在cutover当天，AD==AE（还没申请）→ 应该
        # 生成【员工账号申请】草稿。
        # 张三：运营1部，生效日期在cutover(2026-10-01)之前 → 按理由判断跳过。
        self.primary_rows = roster_sheet_rows(
            data_row(employee_code="NX4325", name="廖伊波", resume_name="廖伊波",
                     effective_date="2026-10-01", org_unit="效能中心",
                     service_unit="恒睿", department="效能部",
                     work_tg="@heather80130", personal_contact="@heather80130"),
            data_row(employee_code="YY0001", name="张三", effective_date="2026-09-20",
                     org_unit="运营中心", service_unit="恒睿", department="运营1部",
                     work_tg="@x", personal_contact="@x"),
        )
        self.secondary_rows = roster_sheet_rows()

    async def test_generates_one_draft_per_qualifying_candidate(self):
        env = build_env(primary_rows=self.primary_rows, secondary_rows=self.secondary_rows)
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))

        drafts = [t for d, t, _f in env['_sent'] if d == 9]
        self.assertEqual(len(drafts), 1)
        self.assertTrue(drafts[0].startswith('【员工账号申请】'))
        self.assertIn('花名：廖伊波', drafts[0])
        self.assertIn('申请原因：新人入职工作需要', drafts[0])
        self.assertNotIn('张三', drafts[0])

        records = [r for r in env['outbox'].all().values() if r['kind'] == 'account_application']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['destination'], -5309896717)
        self.assertEqual(records[0]['approval_code'], '测试111')

    async def test_already_applied_candidate_is_not_queued(self):
        rows = roster_sheet_rows(
            data_row(name="范谦和", effective_date="2026-09-01", department="效能部",
                     work_tg="@fanqianhe1108", personal_contact="@fanqianhe123"),
        )
        env = build_env(primary_rows=rows, secondary_rows=self.secondary_rows)
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        self.assertEqual(len(env['_sent']), 1)
        self.assertIn('没有找到需要处理的人', env['_sent'][0][1])

    async def test_tech_department_before_cutover_is_excluded(self):
        # 回归测试：修复前研发部/效能部会绕过cutover直接生成草稿，导致生效
        # 日期早于2026-10-1的人也被提前处理（线上真实反馈：阿林、muli、
        # 方清屿、李光、Shun、李达华、大华等本不该在这批出现）。现在不论
        # 部门，生效日期必须>=cutover才处理。
        rows = roster_sheet_rows(
            data_row(name="阿林", effective_date="2026-09-01", department="效能部",
                     work_tg="@alin65175", personal_contact="@alin65175"),
        )
        env = build_env(primary_rows=rows, secondary_rows=self.secondary_rows)
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        self.assertEqual(len(env['_sent']), 1)
        self.assertIn('没有找到需要处理的人', env['_sent'][0][1])

    async def test_not_enough_days_elapsed_is_excluded(self):
        # SSC反馈需要恢复"生效满6天"限制：生效日期已经过了cutover，但距
        # 今(2026-10-10)不满6天的，先不处理。
        rows = roster_sheet_rows(
            data_row(name="大华", effective_date="2026-10-08", department="效能部",
                     work_tg="", personal_contact="@dahua123"),
        )
        env = build_env(primary_rows=rows, secondary_rows=self.secondary_rows)
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        self.assertEqual(len(env['_sent']), 1)
        self.assertIn('没有找到需要处理的人', env['_sent'][0][1])

    async def test_blank_work_tg_generates_draft(self):
        # AD列完全空白也算还没申请，不再要求AD/AE都非空才处理。
        rows = roster_sheet_rows(
            data_row(name="李光", effective_date="2026-10-01", department="效能部",
                     work_tg="", personal_contact="@liguang123"),
        )
        env = build_env(primary_rows=rows, secondary_rows=self.secondary_rows)
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        drafts = [t for d, t, _f in env['_sent'] if d == 9]
        self.assertEqual(len(drafts), 1)
        self.assertIn('花名：李光', drafts[0])

    async def test_placeholder_work_tg_text_generates_draft(self):
        # AD列填"同上"这类占位文字，等价于AD==AE，也算还没申请。
        rows = roster_sheet_rows(
            data_row(name="李达华", effective_date="2026-10-01", department="运营1部",
                     work_tg="同上", personal_contact="@lidahua88"),
        )
        env = build_env(primary_rows=rows, secondary_rows=self.secondary_rows)
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        drafts = [t for d, t, _f in env['_sent'] if d == 9]
        self.assertEqual(len(drafts), 1)
        self.assertIn('花名：李达华', drafts[0])

    async def test_other_department_uses_different_format(self):
        rows = roster_sheet_rows(
            data_row(name="江亦白", effective_date="2026-10-01", department="运营1部",
                     org_unit="运营中心", service_unit="恒睿", employee_code="YY6342",
                     work_tg="@yibai7798", personal_contact="@yibai7798"),
        )
        env = build_env(primary_rows=rows, secondary_rows=self.secondary_rows)
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        drafts = [t for d, t, _f in env['_sent'] if d == 9]
        self.assertEqual(len(drafts), 1)
        self.assertTrue(drafts[0].startswith('【员工工作帐号申请】'))
        self.assertIn('申请原因：新人入职满7天', drafts[0])
        self.assertIn('申请数量：1个', drafts[0])

    async def test_duplicate_name_across_sheets_prefers_primary_without_notifying(self):
        # 同名冲突按"花名册"为准静默处理，不再发收藏夹提示打扰SSC（只记
        # 日志）；用"别的部门"的数据验证草稿确实用的是primary(花名册)的
        # 内容，不是secondary(花名册（机器人）)的。
        secondary_with_dup = roster_sheet_rows(
            data_row(name="廖伊波", effective_date="2020-01-01", department="别的部门",
                     work_tg="x", personal_contact="y"),
        )
        env = build_env(primary_rows=self.primary_rows, secondary_rows=secondary_with_dup)
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        notices = [t for d, t, _f in env['_sent'] if '重复' in t]
        self.assertEqual(notices, [])
        drafts = [t for d, t, _f in env['_sent'] if d == 9]
        self.assertEqual(len(drafts), 1)
        self.assertTrue(drafts[0].startswith('【员工账号申请】'))
        self.assertIn('花名：廖伊波', drafts[0])

    async def test_disabled_reports_to_favorites(self):
        env = build_env(primary_rows=self.primary_rows, secondary_rows=self.secondary_rows,
                        config=base_config(ACCOUNT_APPLICATION_ENABLED=False))
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        self.assertEqual(len(env['_sent']), 1)
        self.assertIn('未启用', env['_sent'][0][1])

    async def test_no_keyword_is_ignored(self):
        env = build_env(primary_rows=self.primary_rows, secondary_rows=self.secondary_rows)
        await env['on_ssc_account_application_trigger'](fav_event('今天天气不错'))
        self.assertEqual(env['_sent'], [])

    async def test_drive_load_failure_reports_to_favorites(self):
        env = build_env(primary_rows=self.primary_rows, secondary_rows=self.secondary_rows,
                        load_error=FileNotFoundError('未找到'))
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        self.assertEqual(len(env['_sent']), 1)
        self.assertIn('失败', env['_sent'][0][1])

    async def test_no_qualifying_candidate_reports_to_favorites(self):
        rows = roster_sheet_rows(
            data_row(name="李四", effective_date="2026-09-20", department="运营1部",
                     work_tg="@a", personal_contact="@b"),
        )
        env = build_env(primary_rows=rows, secondary_rows=self.secondary_rows)
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        self.assertEqual(len(env['_sent']), 1)
        self.assertIn('没有找到需要处理的人', env['_sent'][0][1])


class AccountApplicationReleaseTests(IsolatedAsyncioTestCase):
    async def _seed_two_pending_drafts(self, env):
        env['outbox'].set('100', {
            'draft_id': 100, 'destination': -5309896717, 'candidate': 'account_application:a',
            'expected_stage': 'waiting_ssc_account_application', 'updates': {'stage': 'x'},
            'kind': 'account_application', 'status': 'pending', 'review_chat_id': 9,
            'approval_code': '测试111',
        })
        env['outbox'].set('101', {
            'draft_id': 101, 'destination': -5309896717, 'candidate': 'account_application:b',
            'expected_stage': 'waiting_ssc_account_application', 'updates': {'stage': 'x'},
            'kind': 'account_application', 'status': 'pending', 'review_chat_id': 9,
            'approval_code': '测试111',
        })

    def _no_sleep_env(self, env):
        import types
        fake_asyncio = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio) if not k.startswith('_')})

        async def fake_sleep(seconds):
            env.setdefault('_slept', []).append(seconds)

        fake_asyncio.sleep = fake_sleep
        env['asyncio'] = fake_asyncio
        return env

    async def test_releases_all_pending_drafts_in_order_and_deletes_each(self):
        env = build_env(primary_rows=[], secondary_rows=[])
        await self._seed_two_pending_drafts(env)
        env['_client'].get_messages = AsyncMock(side_effect=[
            NS(id=100, raw_text='草稿A', media=None),
            NS(id=101, raw_text='草稿B', media=None),
        ])
        env['random'] = NS(uniform=lambda a, b: 7)
        env = self._no_sleep_env(env)

        await env['on_ssc_account_application_release'](fav_event('测试111', msg_id=2000))

        forwarded = [t for d, t, _f in env['_sent'] if d == -5309896717]
        self.assertEqual(forwarded, ['草稿A', '草稿B'])
        self.assertEqual(env.get('_slept', []), [7])
        self.assertEqual(env['_client'].delete_messages.await_count, 2)
        statuses = {r['draft_id']: r['status'] for r in env['outbox'].all().values()}
        self.assertEqual(statuses, {100: 'sent', 101: 'sent'})

    async def test_wrong_code_does_not_release(self):
        env = build_env(primary_rows=[], secondary_rows=[])
        await self._seed_two_pending_drafts(env)
        await env['on_ssc_account_application_release'](fav_event('测试1', msg_id=2000))
        self.assertEqual(env['_sent'], [])
        statuses = {r['status'] for r in env['outbox'].all().values()}
        self.assertEqual(statuses, {'pending'})

    async def test_no_pending_drafts_is_silent(self):
        env = build_env(primary_rows=[], secondary_rows=[])
        await env['on_ssc_account_application_release'](fav_event('测试111', msg_id=2000))
        self.assertEqual(env['_sent'], [])

    async def test_empty_draft_marked_failed_and_does_not_block_others(self):
        env = build_env(primary_rows=[], secondary_rows=[])
        await self._seed_two_pending_drafts(env)
        env['_client'].get_messages = AsyncMock(side_effect=[
            NS(id=100, raw_text='', media=None),
            NS(id=101, raw_text='草稿B', media=None),
        ])
        env = self._no_sleep_env(env)

        await env['on_ssc_account_application_release'](fav_event('测试111', msg_id=2000))
        forwarded = [t for d, t, _f in env['_sent'] if d == -5309896717]
        self.assertEqual(forwarded, ['草稿B'])
        statuses = {r['draft_id']: r['status'] for r in env['outbox'].all().values()}
        self.assertEqual(statuses, {100: 'failed', 101: 'sent'})


if __name__ == '__main__':
    import unittest
    unittest.main()
