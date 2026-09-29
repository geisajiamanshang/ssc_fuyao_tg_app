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
    build_account_application_text,
    merge_rosters,
    needs_account_application,
    parse_roster_csv,
    parse_roster_date,
)
from approval_queue import select_pending


ROSTER_HEADER = ",".join(["header"] * 31)


def roster_row(name, effective_date, department, status_ad, status_ae):
    cells = ["" for _ in range(31)]
    cells[2] = name
    cells[5] = effective_date
    cells[14] = department
    cells[29] = status_ad
    cells[30] = status_ae
    return ",".join(cells)


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
        ACCOUNT_APPLICATION_ENABLED=True,
        ACCOUNT_APPLICATION_TRIGGER_KEYWORD="帐号申请",
        ACCOUNT_APPLICATION_APPROVAL_CODE="测试111",
        ACCOUNT_APPLICATION_NAME_COLUMN="C",
        ACCOUNT_APPLICATION_EFFECTIVE_DATE_COLUMN="F",
        ACCOUNT_APPLICATION_DEPARTMENT_COLUMN="O",
        ACCOUNT_APPLICATION_STATUS_COLUMNS=("AD", "AE"),
        ACCOUNT_APPLICATION_MIN_DAYS_SINCE_EFFECTIVE=6,
        ACCOUNT_APPLICATION_TECH_DEPARTMENTS=("研发部", "效能部"),
        ACCOUNT_APPLICATION_OTHER_REASON_CUTOVER_DATE="2026-10-01",
        DAILY_REPORT_TIMEZONE="Asia/Shanghai",
        GROUP_ACCOUNT_REQUEST_WORK=-5309896717,
        ALLOWED_DESTINATION_IDS={-5309896717},
        APPROVAL_CODES=frozenset({"测试1"}),
        OFFER_APPROVAL_CODE="测试1", ENVIRONMENT="test",
    )
    fields.update(overrides)
    return NS(**fields)


def build_env(*, primary_csv, secondary_csv, template_text="【帐号申请模版】", load_error=None,
              today=None, **overrides):
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
        return primary_csv, secondary_csv

    def load_template():
        return template_text

    client = NS(
        get_me=AsyncMock(return_value=me),
        send_message=send_message,
        get_messages=AsyncMock(),
        delete_messages=AsyncMock(),
    )

    env = dict(
        account_application_reason=account_application_reason,
        build_account_application_text=build_account_application_text,
        merge_rosters=merge_rosters,
        needs_account_application=needs_account_application,
        parse_roster_csv=parse_roster_csv,
        parse_roster_date=parse_roster_date,
        select_pending=select_pending,
        asyncio=asyncio, random=random, datetime=datetime, ZoneInfo=ZoneInfo,
        log=logging.getLogger('test'),
        client=client,
        outbox=MemoryStore(), state=MemoryStore(),
        ssc_send_lock=asyncio.Lock(), account_application_lock=asyncio.Lock(),
        account_application_drive=NS(load_rosters=load_rosters, load_template=load_template),
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


class AccountApplicationTriggerTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.primary_csv = "\n".join([
            ROSTER_HEADER,
            roster_row("廖伊波", "2026-09-01", "效能中心-效能部", "已申请", "未申请"),
            roster_row("张三", "2026-09-05", "运营中心-运营1部", "已申请", "未申请"),
        ])
        self.secondary_csv = "\n".join([ROSTER_HEADER])

    async def test_generates_one_draft_per_qualifying_candidate(self):
        # 廖伊波（研发部/效能部）符合条件；张三（其他部门、生效日期在
        # 2026-10-1之前）不符合cutover日期，本轮不处理。
        env = build_env(primary_csv=self.primary_csv, secondary_csv=self.secondary_csv)
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))

        drafts = [t for d, t, _f in env['_sent'] if d == 9]
        self.assertEqual(len(drafts), 1)
        self.assertIn('候选人姓名：廖伊波', drafts[0])
        self.assertIn('新人入职工作需要', drafts[0])
        self.assertNotIn('张三', drafts[0])

        records = [r for r in env['outbox'].all().values() if r['kind'] == 'account_application']
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['destination'], -5309896717)
        self.assertEqual(records[0]['approval_code'], '测试111')

    async def test_duplicate_name_across_sheets_prefers_primary_and_notifies(self):
        secondary_with_dup = "\n".join([
            ROSTER_HEADER,
            roster_row("廖伊波", "2020-01-01", "机器人来源部门", "x", "x"),
        ])
        env = build_env(primary_csv=self.primary_csv, secondary_csv=secondary_with_dup)
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        notices = [t for d, t, _f in env['_sent'] if d == 9 and '重复' in t]
        self.assertEqual(len(notices), 1)
        self.assertIn('廖伊波', notices[0])

    async def test_disabled_reports_to_favorites(self):
        env = build_env(primary_csv=self.primary_csv, secondary_csv=self.secondary_csv,
                        config=base_config(ACCOUNT_APPLICATION_ENABLED=False))
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        self.assertEqual(len(env['_sent']), 1)
        self.assertIn('未启用', env['_sent'][0][1])

    async def test_no_keyword_is_ignored(self):
        env = build_env(primary_csv=self.primary_csv, secondary_csv=self.secondary_csv)
        await env['on_ssc_account_application_trigger'](fav_event('今天天气不错'))
        self.assertEqual(env['_sent'], [])

    async def test_drive_load_failure_reports_to_favorites(self):
        env = build_env(primary_csv=self.primary_csv, secondary_csv=self.secondary_csv,
                        load_error=FileNotFoundError('未找到'))
        await env['on_ssc_account_application_trigger'](fav_event('帐号申请'))
        self.assertEqual(len(env['_sent']), 1)
        self.assertIn('失败', env['_sent'][0][1])

    async def test_no_qualifying_candidate_reports_to_favorites(self):
        csv_text = "\n".join([
            ROSTER_HEADER,
            roster_row("李四", "2026-09-08", "运营中心-运营1部", "已申请", "已申请"),
        ])
        env = build_env(primary_csv=csv_text, secondary_csv=self.secondary_csv)
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

    async def test_releases_all_pending_drafts_in_order_and_deletes_each(self):
        env = build_env(primary_csv="", secondary_csv="")
        await self._seed_two_pending_drafts(env)
        env['_client'].get_messages = AsyncMock(side_effect=[
            NS(id=100, raw_text='草稿A', media=None),
            NS(id=101, raw_text='草稿B', media=None),
        ])
        # 避免测试真的等5-10秒。
        env['asyncio'] = asyncio
        orig_sleep = asyncio.sleep
        slept = []

        async def fake_sleep(seconds):
            slept.append(seconds)

        env['random'] = NS(uniform=lambda a, b: 7)
        import types
        fake_asyncio = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio) if not k.startswith('_')})
        fake_asyncio.sleep = fake_sleep
        env['asyncio'] = fake_asyncio

        await env['on_ssc_account_application_release'](fav_event('测试111', msg_id=2000))

        forwarded = [t for d, t, _f in env['_sent'] if d == -5309896717]
        self.assertEqual(forwarded, ['草稿A', '草稿B'])
        self.assertEqual(slept, [7])  # 只在两条之间等一次，不在最后一条之后等
        self.assertEqual(env['_client'].delete_messages.await_count, 2)
        statuses = {r['draft_id']: r['status'] for r in env['outbox'].all().values()}
        self.assertEqual(statuses, {100: 'sent', 101: 'sent'})

    async def test_wrong_code_does_not_release(self):
        env = build_env(primary_csv="", secondary_csv="")
        await self._seed_two_pending_drafts(env)
        await env['on_ssc_account_application_release'](fav_event('测试1', msg_id=2000))
        self.assertEqual(env['_sent'], [])
        statuses = {r['status'] for r in env['outbox'].all().values()}
        self.assertEqual(statuses, {'pending'})

    async def test_no_pending_drafts_is_silent(self):
        env = build_env(primary_csv="", secondary_csv="")
        await env['on_ssc_account_application_release'](fav_event('测试111', msg_id=2000))
        self.assertEqual(env['_sent'], [])

    async def test_empty_draft_marked_failed_and_does_not_block_others(self):
        env = build_env(primary_csv="", secondary_csv="")
        await self._seed_two_pending_drafts(env)
        env['_client'].get_messages = AsyncMock(side_effect=[
            NS(id=100, raw_text='', media=None),
            NS(id=101, raw_text='草稿B', media=None),
        ])
        import types
        fake_asyncio = types.SimpleNamespace(**{k: getattr(asyncio, k) for k in dir(asyncio) if not k.startswith('_')})

        async def fake_sleep(seconds):
            return None

        fake_asyncio.sleep = fake_sleep
        env['asyncio'] = fake_asyncio

        await env['on_ssc_account_application_release'](fav_event('测试111', msg_id=2000))
        forwarded = [t for d, t, _f in env['_sent'] if d == -5309896717]
        self.assertEqual(forwarded, ['草稿B'])
        statuses = {r['draft_id']: r['status'] for r in env['outbox'].all().values()}
        self.assertEqual(statuses, {100: 'failed', 101: 'sent'})


if __name__ == '__main__':
    import unittest
    unittest.main()
