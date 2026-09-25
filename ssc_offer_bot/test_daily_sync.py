import ast
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import config_common as cc
from daily_sync import (
    build_daily_sync_report,
    classify_and_bucket,
    classify_sync_message,
    classify_transfer_subtype,
    new_center_bucket,
    resolve_center,
)
from parsers import parse_kv_fields

ONBOARDING = (
    "【入职信息同步】\n\n"
    "日期：2026-7-27\n花名：阿紫\n简历名：阿紫\n编号：YY1941\n岗位：运营专员\n"
    "部门-小组：运营一部-免费1组\n直属上级：石坚\n简历来源：熊三明/宏景/TG\n私人TG：@xiaooaziya"
)
REGULARIZATION_OPS = (
    "【转正信息同步】\n\n北斗矩阵：恒睿\n部门-小组：运营1部-免费1组\n编号：YY1941\n花名：阿紫\n"
    "岗位：运营专员\n入职日期：2026-07-27\n转正日期：2026-09-27（中秋节生效）\n"
    "直属上级/BP评估：同意按期转正\n试用期职级：P3\n转正职级：P3"
)
REGULARIZATION_TECH = (
    "【转正信息同步】\n\n北斗矩阵：恒睿\n部门-小组：研发部-前端组\n编号：DN1465\n花名：大副\n"
    "岗位：项目经理\n入职日期：2026-05-27\n转正日期：2026-09-27\n直属上级/BP评估：同意按期转正\n"
    "试用期职级：P5-1\n转正职级：P5-1"
)
REGULARIZATION_BIZ = (
    "【转正信息同步】\n北斗矩阵：恒睿\n部门-小组：传统销售部-销售组\n编号：XS9498\n花名：张启山\n"
    "岗位：商务专员\n入职日期：2026-05-15\n转正日期：2026-07-27\n直属上级/BP评估：同意转正\n"
    "试用期职级：P1\n转正职级：P3"
)
RESIGNATION = (
    "【离职信息同步】\n编号：YY6425\n花名：沙瑞金\n服务单位：恒睿\n编制组织：运营中心\n"
    "部门-小组：ACFAN特战队-app运营组\n岗位：运营专员\n离职类型：劝退"
)
TRANSFER_NAME = (
    "【人员异动信息同步】\n\n编制组织：运营中心\n服务单位：鼎丰\n部门：运营3部-短剧1组\n"
    "异动日期：2026-09-23\n异动类型：花名变更\n员工编码：YY2552\n原花名：彦祖\n现花名：萧诧"
)


class ClassificationTests(TestCase):
    def test_classify_sync_message_by_header(self):
        self.assertEqual(classify_sync_message(ONBOARDING), "入职")
        self.assertEqual(classify_sync_message(REGULARIZATION_OPS), "转正")
        self.assertEqual(classify_sync_message(RESIGNATION), "离职")
        self.assertEqual(classify_sync_message(TRANSFER_NAME), "异动")
        self.assertIsNone(classify_sync_message("随便聊两句，没有关键词"))

    def test_department_field_now_parses_with_hyphen(self):
        # "部门-小组" 字段名里带短横线，之前的字段名正则会漏掉这一行。
        fields = parse_kv_fields(ONBOARDING)
        self.assertEqual(fields.get("部门-小组"), "运营一部-免费1组")

    def test_onboarding_and_regularization_resolve_center_via_department_keywords(self):
        fields = parse_kv_fields(ONBOARDING)
        self.assertEqual(resolve_center("入职", fields, cc.DAILY_SYNC_CENTER_DEPARTMENT_KEYWORDS,
                                        cc.DAILY_SYNC_CENTER_ORDER), "运营中心")
        self.assertEqual(resolve_center("转正", parse_kv_fields(REGULARIZATION_TECH),
                                        cc.DAILY_SYNC_CENTER_DEPARTMENT_KEYWORDS,
                                        cc.DAILY_SYNC_CENTER_ORDER), "技术中心")
        self.assertEqual(resolve_center("转正", parse_kv_fields(REGULARIZATION_BIZ),
                                        cc.DAILY_SYNC_CENTER_DEPARTMENT_KEYWORDS,
                                        cc.DAILY_SYNC_CENTER_ORDER), "商务中心")

    def test_resignation_and_transfer_resolve_center_via_org_field_not_department_table(self):
        # 离职/异动消息自带"编制组织"，直接用这个字段；部门关键词表只用它的key
        # 校验这是个合法中心名，不会去翻其中任何一个中心的部门关键词列表。
        keywords_with_empty_lists = {c: [] for c in cc.DAILY_SYNC_CENTER_ORDER}
        self.assertEqual(resolve_center("离职", parse_kv_fields(RESIGNATION),
                                        keywords_with_empty_lists, cc.DAILY_SYNC_CENTER_ORDER), "运营中心")
        self.assertEqual(resolve_center("异动", parse_kv_fields(TRANSFER_NAME),
                                        keywords_with_empty_lists, cc.DAILY_SYNC_CENTER_ORDER), "运营中心")

    def test_unresolvable_department_returns_none_instead_of_guessing(self):
        fields = {"部门-小组": "海外拓展部-东南亚组"}
        self.assertIsNone(resolve_center("入职", fields, cc.DAILY_SYNC_CENTER_DEPARTMENT_KEYWORDS,
                                         cc.DAILY_SYNC_CENTER_ORDER))

    def test_transfer_subtype_keyword_matching(self):
        self.assertEqual(classify_transfer_subtype("花名变更"), "改花名")
        self.assertEqual(classify_transfer_subtype("调小组"), "改小组")
        self.assertEqual(classify_transfer_subtype("小组变更"), "改小组")
        self.assertEqual(classify_transfer_subtype("转公司"), "改公司")
        self.assertEqual(classify_transfer_subtype("公司变更"), "改公司")
        self.assertIsNone(classify_transfer_subtype("职级调整"))
        self.assertIsNone(classify_transfer_subtype(""))


class ReportBuildingTests(TestCase):
    def setUp(self):
        self.buckets = {c: new_center_bucket() for c in cc.DAILY_SYNC_CENTER_ORDER}
        for text in [ONBOARDING, REGULARIZATION_OPS, REGULARIZATION_TECH,
                     REGULARIZATION_BIZ, RESIGNATION, TRANSFER_NAME]:
            classify_and_bucket(text, self.buckets, cc.DAILY_SYNC_CENTER_DEPARTMENT_KEYWORDS,
                               cc.DAILY_SYNC_CENTER_ORDER)

    def test_counts_land_in_the_right_center(self):
        ops = self.buckets["运营中心"]
        self.assertEqual(len(ops["入职"]), 1)
        self.assertEqual(len(ops["转正"]), 1)
        self.assertEqual(len(ops["离职"]), 1)
        self.assertEqual(len(ops["异动"]), 1)
        self.assertEqual(ops["改花名"], 1)
        self.assertEqual(ops["改小组"], 0)
        self.assertEqual(len(self.buckets["技术中心"]["转正"]), 1)
        self.assertEqual(len(self.buckets["商务中心"]["转正"]), 1)
        self.assertEqual(len(self.buckets["渠道中心"]["入职"]), 0)
        self.assertEqual(len(self.buckets["效能中心"]["入职"]), 0)

    def test_detail_report_includes_all_five_centers_and_raw_messages(self):
        text = build_daily_sync_report(self.buckets, cc.DAILY_SYNC_CENTER_ORDER,
                                       cc.DAILY_SYNC_COMPANY_LABEL, "2026/9/25", include_detail=True)
        for center in cc.DAILY_SYNC_CENTER_ORDER:
            self.assertIn(f"{center}-{cc.DAILY_SYNC_COMPANY_LABEL}", text)
        self.assertIn("今日入职人数：1", text)
        self.assertIn("花名：阿紫", text)  # 详情原文被带上了
        self.assertIn("花名：沙瑞金", text)
        self.assertIn("现花名：萧诧", text)
        self.assertEqual(text.count("花名册是否完成更新：是"), 5)
        self.assertEqual(text.count("——————————"), 4)  # 5个中心之间4条分隔线

    def test_summary_report_strips_detail_but_keeps_counts(self):
        text = build_daily_sync_report(self.buckets, cc.DAILY_SYNC_CENTER_ORDER,
                                       cc.DAILY_SYNC_COMPANY_LABEL, "2026/9/25", include_detail=False)
        self.assertIn("今日入职人数：1", text)
        self.assertNotIn("【入职信息同步】", text)
        self.assertNotIn("花名：阿紫", text)
        self.assertNotIn("离职类型", text)

    def test_empty_day_still_lists_all_five_centers_at_zero(self):
        empty_buckets = {c: new_center_bucket() for c in cc.DAILY_SYNC_CENTER_ORDER}
        text = build_daily_sync_report(empty_buckets, cc.DAILY_SYNC_CENTER_ORDER,
                                       cc.DAILY_SYNC_COMPANY_LABEL, "2026/9/25", include_detail=True)
        self.assertEqual(text.count("今日入职人数：0"), 5)
        self.assertNotIn("【", text)


# ---------------------------------------------------------------------------
# main.py 集成测试：触发"9" -> 收藏夹发两份草稿；"91"/"92" -> 分别放行到两个群。
# ---------------------------------------------------------------------------

class MemoryStore:
    def __init__(self, data=None):
        self.data = data or {}

    def get(self, key):
        return self.data.get(key)

    def all(self):
        return self.data

    def set(self, key, value):
        self.data[key] = value

    def update(self, key, **values):
        self.data.setdefault(key, {}).update(values)


def build_env(**overrides):
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'queue_group_message', 'on_ssc_daily_sync_trigger',
                                'collect_daily_sync_entries'}]
    for node in functions:
        node.decorator_list = []
    from approval_queue import select_pending
    env = dict(
        select_pending=select_pending,
        build_daily_sync_report=build_daily_sync_report,
        classify_and_bucket=classify_and_bucket,
        new_center_bucket=new_center_bucket,
        datetime=datetime, ZoneInfo=ZoneInfo,
        asyncio=asyncio, log=__import__('logging').getLogger('test'),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
    return env


def fake_message(id, text, when):
    return NS(id=id, raw_text=text, date=when)


class DailySyncTriggerTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.me = NS(id=9, username='ffuuyao')
        self.sent = []
        self.today = datetime(2026, 9, 25, 12, 0, tzinfo=timezone.utc)
        self.yesterday = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
        self.group_messages = [
            fake_message(501, TRANSFER_NAME, self.today),
            fake_message(500, RESIGNATION, self.today),
            fake_message(499, REGULARIZATION_BIZ, self.today),
            fake_message(498, REGULARIZATION_TECH, self.today),
            fake_message(497, REGULARIZATION_OPS, self.today),
            fake_message(496, ONBOARDING, self.today),
            fake_message(400, ONBOARDING, self.yesterday),  # 昨天的，不该计入今天
        ]

        async def send_message(destination, text, **kwargs):
            self.sent.append((destination, text))
            return NS(id=900 + len(self.sent))

        async def iter_messages(chat, from_user=None, limit=None):
            for m in self.group_messages:
                yield m

        self.state = MemoryStore({})
        self.outbox = MemoryStore({})
        self.config = NS(
            GROUP_LEADERSHIP=-1, GROUP_REGULARIZATION_SYNC=-2,
            ALLOWED_DESTINATION_IDS={-1, -2},
            DAILY_SYNC_TRIGGER_CODE='测试9',
            DAILY_SYNC_SUMMARY_APPROVAL_CODE='测试91',
            DAILY_SYNC_DETAIL_APPROVAL_CODE='测试92',
            DAILY_SYNC_ENABLED=True,
            DAILY_SYNC_CENTER_ORDER=cc.DAILY_SYNC_CENTER_ORDER,
            DAILY_SYNC_CENTER_DEPARTMENT_KEYWORDS=cc.DAILY_SYNC_CENTER_DEPARTMENT_KEYWORDS,
            DAILY_SYNC_COMPANY_LABEL=cc.DAILY_SYNC_COMPANY_LABEL,
            DAILY_REPORT_TIMEZONE='Asia/Shanghai',
            OFFER_APPROVAL_CODE='测试1', EXCLUDED_CHAT_IDS=frozenset(),
        )
        self.client = NS(
            get_me=AsyncMock(return_value=self.me),
            send_message=send_message,
            iter_messages=iter_messages,
        )
        self.env = build_env(
            client=self.client, state=self.state, outbox=self.outbox,
            ssc_send_lock=asyncio.Lock(), daily_sync_lock=asyncio.Lock(),
            get_ssc_reviewer=AsyncMock(return_value=self.me), config=self.config,
        )

    async def _fire_trigger(self, code, msg_id=200):
        event = NS(chat_id=9, raw_text=code, is_private=True, sender_id=9,
                  message=NS(id=msg_id, reply_to_msg_id=None))
        await self.env['on_ssc_daily_sync_trigger'](event)

    async def test_trigger_queues_two_drafts_to_favorites_with_todays_data_only(self):
        await self._fire_trigger('测试9')
        # 两条草稿都发到收藏夹（reviewer=9），不是直接发到目标群。
        self.assertEqual([dest for dest, _ in self.sent], [9, 9])
        detail_draft, summary_draft = (text for _, text in self.sent)
        self.assertIn("花名：阿紫", detail_draft)      # 今天的入职消息被计入了
        self.assertNotIn("2026-9-24", detail_draft)     # 昨天的数据没有混进来
        self.assertIn("今日入职人数：1", detail_draft)
        self.assertNotIn("【入职信息同步】", summary_draft)
        self.assertIn("今日入职人数：1", summary_draft)

        pending = list(self.outbox.data.values())
        self.assertEqual(len(pending), 2)
        detail_item = next(r for r in pending if r['kind'] == 'daily_sync_detail')
        summary_item = next(r for r in pending if r['kind'] == 'daily_sync_summary')
        self.assertEqual(detail_item['destination'], -1)           # 联合管理群
        self.assertEqual(detail_item['approval_code'], '测试92')
        self.assertEqual(summary_item['destination'], -2)          # 人事数据同步-SSC3组
        self.assertEqual(summary_item['approval_code'], '测试91')

    async def test_92_code_matches_the_detail_draft_pending_in_outbox(self):
        await self._fire_trigger('测试9')
        from approval_queue import select_pending
        item = select_pending(list(self.outbox.data.values()), self.state.data, 9, '测试92', 999, None)
        self.assertIsNotNone(item)
        self.assertEqual(item['destination'], -1)  # 联合管理群
        self.assertEqual(item['kind'], 'daily_sync_detail')

    async def test_91_code_matches_the_summary_draft_pending_in_outbox(self):
        await self._fire_trigger('测试9')
        from approval_queue import select_pending
        item = select_pending(list(self.outbox.data.values()), self.state.data, 9, '测试91', 999, None)
        self.assertIsNotNone(item)
        self.assertEqual(item['destination'], -2)  # 人事数据同步-SSC3组
        self.assertEqual(item['kind'], 'daily_sync_summary')

    async def test_disabled_when_regularization_sync_group_not_configured(self):
        self.config.DAILY_SYNC_ENABLED = False
        await self._fire_trigger('测试9')
        # 不生成草稿，但会在收藏夹提示一句"未启用"，不是静默无反应。
        self.assertEqual(len(self.sent), 1)
        self.assertIn("未启用", self.sent[0][1])
        self.assertEqual(self.outbox.data, {})

    async def test_unresolvable_department_is_reported_not_silently_dropped(self):
        self.group_messages.append(
            fake_message(600, ONBOARDING.replace("运营一部-免费1组", "海外拓展部-东南亚组"), self.today)
        )
        await self._fire_trigger('测试9')
        # 无法识别中心的那条不计入任何中心的统计。
        detail_draft = self.sent[0][1]
        self.assertIn("今日入职人数：1", detail_draft)  # 还是只有原来那1条，没多算


if __name__ == '__main__':
    import unittest
    unittest.main()
