# -*- coding: utf-8 -*-
"""场景十三：SSC在自己的收藏夹发带"培训"关键词的消息，触发按花名册
（机器人）AR列日期筛出"明天"要培训的人，按编制组织分组生成【次日培训
信息同步】草稿发到收藏夹，经审批码14（测试14）放行到共享服务中心-远程
培训沟通群。

重点覆盖一个容易忽略的自触发循环风险：草稿标题本身带"培训"两个字，
草稿一发到收藏夹就会被同一个监听器自己收到；"没匹配到人"/"未启用"/
"生成失败"这几条诊断提示也可能被反复触发（尤其"没匹配到人"在日常运行
里很常见），所以这几条提示也特意避免"培训"两个字连在一起出现。"""

import ast
import asyncio
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from zoneinfo import ZoneInfo

from training_sync import (
    TRAINING_SYNC_HEADER,
    build_training_sync_report,
    parse_training_date,
    parse_training_roster_rows,
    select_people_for_date,
)

# ==================== 纯逻辑：花名册解析/日期筛选/报告拼装 ====================

CENTER_ORDER = ["运营中心", "技术中心", "渠道中心", "商务中心", "效能中心"]
COMPANY_LABEL = "恒睿"


def _row(name="", org_unit="", department="", position="", training_date=""):
    """按真实花名册（机器人）列位置（简历名=E，编制组织=M，部门=P，
    岗位=U，培训日期=AR）拼一行，其余列留空，跟真实表格里大量未使用的
    列保持一致的稀疏结构。"""
    row = [""] * 45  # 0-based，下标43是AR列（第44列）
    row[4] = name            # E
    row[12] = org_unit       # M
    row[15] = department     # P
    row[20] = position       # U
    row[43] = training_date  # AR
    return row


class ParseTrainingDateTests(unittest.TestCase):
    def test_parses_iso_format(self):
        self.assertEqual(parse_training_date("2026-10-13"), date(2026, 10, 13))

    def test_parses_slash_format(self):
        self.assertEqual(parse_training_date("2026/10/13"), date(2026, 10, 13))

    def test_blank_returns_none(self):
        self.assertIsNone(parse_training_date(""))
        self.assertIsNone(parse_training_date(None))

    def test_unrecognized_format_returns_none(self):
        self.assertIsNone(parse_training_date("明天"))


class ParseTrainingRosterRowsTests(unittest.TestCase):
    def test_skips_single_header_row_and_reads_columns(self):
        rows = [
            ["花名册（机器人）表头行占位"],
            _row(name="毛毛", org_unit="运营中心", department="AIGC原创部",
                 position="AI 视频生成师", training_date="2026-10-13"),
        ]
        people = parse_training_roster_rows(rows)
        self.assertEqual(len(people), 1)
        self.assertEqual(people[0], {
            "name": "毛毛", "org_unit": "运营中心", "department": "AIGC原创部",
            "position": "AI 视频生成师", "training_date_raw": "2026-10-13",
        })

    def test_skips_rows_with_blank_resume_name(self):
        rows = [
            ["表头"],
            _row(name="", org_unit="运营中心", training_date="2026-10-13"),
        ]
        self.assertEqual(parse_training_roster_rows(rows), [])

    def test_short_rows_missing_trailing_columns_are_tolerated(self):
        # 真实Sheets API返回行尾空单元格会被省略，AR列(下标43)可能整个
        # 不在返回的行里。
        rows = [["表头"], ["", "", "", "", "毛毛"]]
        people = parse_training_roster_rows(rows)
        self.assertEqual(people[0]["name"], "毛毛")
        self.assertEqual(people[0]["training_date_raw"], "")


class SelectPeopleForDateTests(unittest.TestCase):
    def test_filters_to_exact_target_date(self):
        people = [
            {"name": "毛毛", "training_date_raw": "2026-10-13"},
            {"name": "元宝", "training_date_raw": "2026-10-14"},
        ]
        selected = select_people_for_date(people, date(2026, 10, 13))
        self.assertEqual([p["name"] for p in selected], ["毛毛"])

    def test_unparseable_date_is_silently_skipped(self):
        people = [{"name": "某人", "training_date_raw": "待定"}]
        self.assertEqual(select_people_for_date(people, date(2026, 10, 13)), [])


class BuildTrainingSyncReportTests(unittest.TestCase):
    def test_matches_the_exact_example_format(self):
        # 跟用户给出的真实例子逐字核对：单个编制组织，3个人。
        people = [
            {"name": "毛毛", "org_unit": "运营中心", "department": "AIGC原创部",
             "position": "AI 视频生成师"},
            {"name": "小海螺", "org_unit": "运营中心", "department": "AIGC原创部",
             "position": "AI 视频生成师"},
            {"name": "元宝", "org_unit": "运营中心", "department": "运营1部-产品运营组",
             "position": "运营专员"},
        ]
        report = build_training_sync_report(people, CENTER_ORDER, COMPANY_LABEL, "2026-10-13")
        expected = (
            "【次日培训信息同步】\n\n"
            "运营中心-恒睿 3人\n"
            "入职时间：2026-10-13\n岗位：AI 视频生成师\n部门：AIGC原创部\n简历名：毛毛\n\n"
            "入职时间：2026-10-13\n岗位：AI 视频生成师\n部门：AIGC原创部\n简历名：小海螺\n\n"
            "入职时间：2026-10-13\n岗位：运营专员\n部门：运营1部-产品运营组\n简历名：元宝"
        )
        self.assertEqual(report, expected)

    def test_multiple_centers_split_into_separate_paragraphs_in_center_order(self):
        people = [
            {"name": "甲", "org_unit": "技术中心", "department": "研发部", "position": "后端工程师"},
            {"name": "乙", "org_unit": "运营中心", "department": "运营1部", "position": "运营专员"},
        ]
        report = build_training_sync_report(people, CENTER_ORDER, COMPANY_LABEL, "2026-10-13")
        # center_order里"运营中心"排在"技术中心"前面，即使乙在people列表里
        # 排在后面，段落顺序也要按center_order来，不是按people的原始顺序。
        self.assertIn("运营中心-恒睿 1人", report)
        self.assertIn("技术中心-恒睿 1人", report)
        self.assertLess(report.index("运营中心-恒睿"), report.index("技术中心-恒睿"))

    def test_center_not_in_order_list_appended_last_by_first_seen(self):
        people = [
            {"name": "甲", "org_unit": "海外中心", "department": "x", "position": "y"},
            {"name": "乙", "org_unit": "运营中心", "department": "x", "position": "y"},
        ]
        report = build_training_sync_report(people, CENTER_ORDER, COMPANY_LABEL, "2026-10-13")
        self.assertLess(report.index("运营中心-恒睿"), report.index("海外中心-恒睿"))

    def test_center_with_no_matches_does_not_appear(self):
        # 跟daily_sync.py"永远列出全部中心"的习惯不一样：这里没人就不起
        # 这一段。
        people = [{"name": "甲", "org_unit": "运营中心", "department": "x", "position": "y"}]
        report = build_training_sync_report(people, CENTER_ORDER, COMPANY_LABEL, "2026-10-13")
        for center in ("技术中心", "渠道中心", "商务中心", "效能中心"):
            self.assertNotIn(center, report)


# ==================== Telegram事件处理器：AST提取main.py里的函数体测试 ====================

source = Path(__file__).with_name("main.py").read_text()
tree = ast.parse(source)
selected = {"on_ssc_training_sync_trigger"}
functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name in selected]
for node in functions:
    # on_ssc_training_sync_trigger在main.py里是@client.on(...)直接修饰的
    # 事件处理函数本身，不去掉装饰器的话exec时装饰器本身就会求值，要求
    # client/events在ns里存在；这里只测内部逻辑，不需要真的注册到client上
    # （跟test_wallet_sync.py同样的坑，同样的解法）。
    node.decorator_list = []

config = NS(
    EXCLUDED_CHAT_IDS=frozenset(),
    TRAINING_SYNC_HEADER=TRAINING_SYNC_HEADER,
    TRAINING_SYNC_TRIGGER_KEYWORD="培训",
    TRAINING_SYNC_ENABLED=True,
    TRAINING_SYNC_APPROVAL_CODE="14",
    GROUP_REMOTE_TRAINING=-200,
    DAILY_REPORT_TIMEZONE="Asia/Shanghai",
    DAILY_SYNC_CENTER_ORDER=CENTER_ORDER,
    DAILY_SYNC_COMPANY_LABEL=COMPANY_LABEL,
)
ns = dict(
    config=config, asyncio=asyncio, ZoneInfo=ZoneInfo,
    TRAINING_SYNC_HEADER=TRAINING_SYNC_HEADER,
    parse_training_roster_rows=parse_training_roster_rows,
    select_people_for_date=select_people_for_date,
    build_training_sync_report=build_training_sync_report,
)
# 补上main.py顶部 `from datetime import datetime, timedelta, timezone` 这一组，
# AST按FunctionDef/AsyncFunctionDef筛选只带函数定义，不带这些顶层import。
from datetime import datetime, timedelta  # noqa: E402

ns["datetime"] = datetime
ns["timedelta"] = timedelta
exec(compile(ast.Module(body=functions, type_ignores=[]), "<training_sync_handler>", "exec"), ns)


EXAMPLE_ROWS = [
    ["表头"],
    _row(name="毛毛", org_unit="运营中心", department="AIGC原创部",
         position="AI 视频生成师", training_date="2026-10-13"),
    _row(name="小海螺", org_unit="运营中心", department="AIGC原创部",
         position="AI 视频生成师", training_date="2026-10-13"),
    _row(name="元宝", org_unit="运营中心", department="运营1部-产品运营组",
         position="运营专员", training_date="2026-10-13"),
    _row(name="跟明天无关的人", org_unit="运营中心", department="x",
         position="y", training_date="2099-01-01"),
]


class Store:
    """StateStore的最小替身，跟test_wallet_sync.py同一套语义。"""
    def __init__(self, data=None):
        self.data = data if data is not None else {}

    def get(self, k):
        return self.data.get(k)

    def set(self, k, v):
        self.data[k] = v

    def update(self, k, **v):
        self.data.setdefault(k, {}).update(v)


class TrainingSyncTriggerHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ns["training_sync_events"] = Store()
        ns["training_sync_lock"] = asyncio.Lock()
        ns["log"] = NS(warning=lambda *a: None, info=lambda *a: None, exception=lambda *a: None)
        ns["get_ssc_reviewer"] = AsyncMock(return_value=NS(id=99))
        ns["queue_group_message"] = AsyncMock()
        ns["client"] = NS(send_message=AsyncMock())
        ns["training_sync_roster_repo"] = NS(load_rows=Mock(return_value=EXAMPLE_ROWS))
        config.EXCLUDED_CHAT_IDS = frozenset()
        config.TRAINING_SYNC_ENABLED = True

    def _event(self, msg_id=10, text="培训", chat_id=99, sender_id=99, is_private=True):
        return NS(
            chat_id=chat_id, sender_id=sender_id, is_private=is_private,
            raw_text=text, message=NS(id=msg_id),
        )

    async def test_trigger_from_reviewer_generates_grouped_report(self):
        await ns["on_ssc_training_sync_trigger"](self._event())

        call = ns["queue_group_message"].call_args
        self.assertIsNotNone(call, "应该把生成的报告草稿发到SSC收藏夹等待审批")
        self.assertEqual(call.args[0], config.GROUP_REMOTE_TRAINING)
        self.assertTrue(call.args[1].startswith(TRAINING_SYNC_HEADER))
        self.assertIn("运营中心-恒睿 3人", call.args[1])
        self.assertNotIn("跟明天无关的人", call.args[1])
        self.assertEqual(call.kwargs["approval_code"], "14")
        ns["client"].send_message.assert_not_awaited()

    async def test_message_without_keyword_is_ignored(self):
        await ns["on_ssc_training_sync_trigger"](self._event(text="随便聊聊"))
        ns["queue_group_message"].assert_not_awaited()
        ns["client"].send_message.assert_not_awaited()

    async def test_own_report_draft_does_not_retrigger_itself(self):
        # 回归测试：草稿标题本身带"培训"两个字，草稿发到收藏夹后会被这个
        # 监听器自己收到，必须被正确地当成"这是报告本身"而忽略，否则会
        # 无限重复生成下去。
        draft_text = TRAINING_SYNC_HEADER + "\n\n运营中心-恒睿 1人\n入职时间：2026-10-13"
        await ns["on_ssc_training_sync_trigger"](self._event(text=draft_text))
        ns["queue_group_message"].assert_not_awaited()
        ns["client"].send_message.assert_not_awaited()

    async def test_non_reviewer_sender_is_ignored(self):
        await ns["on_ssc_training_sync_trigger"](self._event(sender_id=1))
        ns["queue_group_message"].assert_not_awaited()

    async def test_non_private_chat_is_ignored(self):
        await ns["on_ssc_training_sync_trigger"](self._event(is_private=False))
        ns["queue_group_message"].assert_not_awaited()

    async def test_excluded_chat_is_ignored(self):
        config.EXCLUDED_CHAT_IDS = frozenset({99})
        try:
            await ns["on_ssc_training_sync_trigger"](self._event())
            ns["queue_group_message"].assert_not_awaited()
            ns["client"].send_message.assert_not_awaited()
        finally:
            config.EXCLUDED_CHAT_IDS = frozenset()

    async def test_disabled_sends_notice_that_cannot_retrigger_itself(self):
        config.TRAINING_SYNC_ENABLED = False
        await ns["on_ssc_training_sync_trigger"](self._event())
        ns["queue_group_message"].assert_not_awaited()
        notice = ns["client"].send_message.call_args.args[1]
        self.assertNotIn("培训", notice, "未启用提示不能带触发关键词，否则发到收藏夹后会自己再触发一次")

    async def test_no_match_sends_notice_that_cannot_retrigger_itself(self):
        ns["training_sync_roster_repo"].load_rows.return_value = [
            ["表头"],
            _row(name="跟明天无关的人", org_unit="运营中心", training_date="2099-01-01"),
        ]
        await ns["on_ssc_training_sync_trigger"](self._event())
        ns["queue_group_message"].assert_not_awaited()
        notice = ns["client"].send_message.call_args.args[1]
        self.assertNotIn("培训", notice, "没匹配到人的提示不能带触发关键词，否则发到收藏夹后会自己再触发一次")

    async def test_failure_sends_notice_that_cannot_retrigger_itself(self):
        ns["training_sync_roster_repo"].load_rows.side_effect = RuntimeError("凭证未配置")
        await ns["on_ssc_training_sync_trigger"](self._event())
        ns["queue_group_message"].assert_not_awaited()
        notice = ns["client"].send_message.call_args.args[1]
        self.assertNotIn("培训", notice, "失败提示不能带触发关键词，否则发到收藏夹后会自己再触发一次")
        self.assertIn("凭证未配置", notice)

    async def test_duplicate_event_is_not_reprocessed(self):
        event = self._event()
        await ns["on_ssc_training_sync_trigger"](event)
        ns["queue_group_message"].reset_mock()
        await ns["on_ssc_training_sync_trigger"](event)
        ns["queue_group_message"].assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
