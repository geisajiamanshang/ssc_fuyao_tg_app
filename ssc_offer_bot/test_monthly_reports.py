# -*- coding: utf-8 -*-
"""场景十九：收藏夹"员工绩效" -> 日报群里扶摇当月的所有日报 -> Word文档发回收藏夹。"""

import ast
import asyncio
import io
import logging
import unittest
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from monthly_reports_doc import build_reports_docx, mask_trigger_keywords
from self_eval import collect_month_reports

ZONE = ZoneInfo("Asia/Shanghai")
NOW = datetime.now(ZONE)
MONTH_START = NOW.replace(day=1, hour=10, minute=0, second=0, microsecond=0)
LAST_MONTH = MONTH_START - timedelta(days=12)

REPORT = """# 日报

[REPORT-ORG:综合行政] [LEVEL:L2] [TYPE:日报] [DATE:{day}]

> 提交人: 扶摇
> 岗位: SSC专员

## 【今日结果】

- SOP 模块执行汇总：
1 2人离职 & 处理<1>人被盗号
2 与bp核对7人钱包地址
"""


def report(day):
    return REPORT.format(day=day.isoformat())


def docx_text(data):
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert zf.testzip() is None
        return zf.read("word/document.xml").decode("utf-8")


class DocBuilderTests(unittest.TestCase):
    def setUp(self):
        self.reports = [(date(2026, 10, 22), report(date(2026, 10, 22))),
                        (date(2026, 10, 23), report(date(2026, 10, 23)))]
        self.data = build_reports_docx(self.reports, "扶摇", "2026年10月", datetime(2026, 10, 28, 15, 40))

    def test_valid_docx_package(self):
        with zipfile.ZipFile(io.BytesIO(self.data)) as zf:
            names = set(zf.namelist())
        self.assertEqual(names, {"[Content_Types].xml", "_rels/.rels", "word/_rels/document.xml.rels",
                                 "word/styles.xml", "word/document.xml"})

    def test_title_summary_dates_and_weekdays(self):
        xml = docx_text(self.data)
        self.assertIn("扶摇 2026年10月日报汇总", xml)
        self.assertIn("共2篇日报，日期范围2026-10-22至2026-10-23", xml)
        self.assertIn("2026-10-22（周四）", xml)
        self.assertIn("2026-10-23（周五）", xml)
        self.assertLess(xml.index("2026-10-22（周四）"), xml.index("2026-10-23（周五）"))

    def test_report_text_kept_and_xml_escaped(self):
        xml = docx_text(self.data)
        self.assertIn("2人离职 &amp; 处理&lt;1&gt;人被盗号", xml)
        self.assertIn("与bp核对7人钱包地址", xml)
        self.assertIn("【今日结果】", xml)
        self.assertNotIn("## ", xml)
        self.assertNotIn("# 日报", xml)       # 每篇日报用日期做标题，不重复

    def test_page_break_between_reports_but_not_before_first(self):
        xml = docx_text(self.data)
        self.assertEqual(xml.count("<w:pageBreakBefore/>"), 1)

    def test_control_characters_are_dropped(self):
        data = build_reports_docx([(date(2026, 10, 22), "正文\x0b中间\x00结尾")], "扶摇", "2026年10月", NOW)
        self.assertIn("正文中间结尾", docx_text(data))

    def test_mask_trigger_keywords(self):
        masked = mask_trigger_keywords("员工绩效文档", ("员工绩效",))
        self.assertNotIn("员工绩效", masked)
        self.assertIn("员工·绩效", masked)

    def test_readable_by_python_docx_when_available(self):
        try:
            import docx
        except ImportError:
            self.skipTest("python-docx not installed")
        document = docx.Document(io.BytesIO(self.data))
        texts = [p.text for p in document.paragraphs]
        self.assertEqual(texts[0], "扶摇 2026年10月日报汇总")
        self.assertIn("1 2人离职 & 处理<1>人被盗号", texts)


tree = ast.parse(Path(__file__).with_name("main.py").read_text())
funcs = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)
         and n.name in {"on_ssc_monthly_reports_trigger", "load_month_reports"}]
assert len(funcs) == 2
for n in funcs:
    n.decorator_list = []


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.me = NS(id=9, username="ffuuyao")
        self.sent, self.files, self.iter_calls, self.visited = [], [], [], []

        async def send_message(destination, text, **kwargs):
            self.sent.append((destination, text))
            return NS(id=900 + len(self.sent))

        async def send_file(destination, file, **kwargs):
            self.files.append((destination, file.name, file.getvalue(), kwargs))
            return NS(id=800 + len(self.files))

        self.messages = [
            NS(raw_text=report(NOW.date()), date=NOW),
            NS(raw_text="@ffuuyao 麻烦跟进一下这个候选人的offer审批", date=NOW - timedelta(minutes=5)),
            NS(raw_text=report(MONTH_START.date()), date=MONTH_START),
            NS(raw_text=report(LAST_MONTH.date()), date=LAST_MONTH),
            NS(raw_text=report(LAST_MONTH.date()), date=LAST_MONTH - timedelta(days=200)),
        ]

        async def iter_messages(chat, from_user=None):
            self.iter_calls.append((chat, from_user))
            for message in self.messages:
                self.visited.append(message.date)
                yield message

        self.config = NS(
            EXCLUDED_CHAT_IDS=frozenset(), MONTHLY_REPORTS_TRIGGER_KEYWORD="员工绩效",
            MONTHLY_REPORTS_ENABLED=True, MONTHLY_REPORTS_SOURCE_CHAT=-5116852931,
            DAILY_REPORT_TIMEZONE="Asia/Shanghai",
        )
        self.client = NS(iter_messages=iter_messages, send_message=send_message, send_file=send_file)
        self.env = dict(
            client=self.client, config=self.config, get_ssc_reviewer=AsyncMock(return_value=self.me),
            monthly_reports_lock=asyncio.Lock(), collect_month_reports=collect_month_reports,
            build_reports_docx=build_reports_docx, mask_trigger_keywords=mask_trigger_keywords,
            datetime=datetime, timedelta=timedelta, ZoneInfo=ZoneInfo, io=io,
            log=logging.getLogger("test"),
        )
        exec(compile(ast.Module(body=funcs, type_ignores=[]), "main.py", "exec"), self.env)

    async def _fire(self, text="员工绩效", chat_id=9, sender_id=9, is_private=True):
        event = NS(chat_id=chat_id, raw_text=text, is_private=is_private, sender_id=sender_id,
                   message=NS(id=200))
        await self.env["on_ssc_monthly_reports_trigger"](event)

    async def test_sends_docx_with_this_months_reports_to_favorites(self):
        await self._fire()
        self.assertEqual(self.iter_calls, [(-5116852931, 9)])      # 日报群里扶摇（收藏夹账号）发的
        self.assertEqual(len(self.files), 1)
        destination, name, data, kwargs = self.files[0]
        self.assertEqual(destination, 9)
        self.assertEqual(name, f"扶摇-{NOW.year}年{NOW.month}月日报汇总.docx")
        self.assertTrue(kwargs["force_document"])
        xml = docx_text(data)
        self.assertIn(f"{NOW.date().isoformat()}（周", xml)
        self.assertIn(f"{MONTH_START.date().isoformat()}（周", xml)
        self.assertNotIn(LAST_MONTH.date().isoformat(), xml)
        self.assertNotIn("麻烦跟进一下这个候选人", xml)
        self.assertIn("共", kwargs["caption"])

    async def test_stops_reading_history_before_last_month(self):
        await self._fire()
        self.assertNotIn(LAST_MONTH - timedelta(days=200), self.visited)

    async def test_nothing_the_bot_sends_contains_the_trigger_word(self):
        # 回归：机器人发到收藏夹的提示/文件说明会被同一监听器收到，含完整触发词会自己触发自己。
        await self._fire()
        self.messages[:] = []
        await self._fire()
        self.config.MONTHLY_REPORTS_ENABLED = False
        await self._fire()
        texts = [t for _, t in self.sent] + [f[3]["caption"] for f in self.files]
        self.assertEqual(len(texts), 3)
        for text in texts:
            self.assertNotIn("员工绩效", text)

    async def test_no_reports_this_month_says_so_and_sends_no_file(self):
        self.messages[:] = [NS(raw_text=report(LAST_MONTH.date()), date=LAST_MONTH)]
        await self._fire()
        self.assertEqual(self.files, [])
        self.assertIn("没找到", self.sent[0][1])

    async def test_failure_notifies(self):
        async def boom(*a, **k):
            raise RuntimeError("员工绩效 flood")
        self.client.send_file = boom
        await self._fire()
        self.assertIn("生成失败", self.sent[0][1])
        self.assertNotIn("员工绩效", self.sent[0][1])

    async def test_disabled_notice(self):
        self.config.MONTHLY_REPORTS_ENABLED = False
        await self._fire()
        self.assertIn("未启用", self.sent[0][1])
        self.assertEqual(self.files, [])

    async def test_ignores_other_text_chats_and_senders(self):
        await self._fire(text="随便聊聊")
        await self._fire(chat_id=123)
        await self._fire(sender_id=555)
        await self._fire(is_private=False)
        self.assertEqual((self.sent, self.files), ([], []))

    async def test_self_eval_keyword_does_not_trigger_this(self):
        await self._fire(text="员工自评")
        self.assertEqual((self.sent, self.files), ([], []))


if __name__ == "__main__":
    unittest.main()
