# -*- coding: utf-8 -*-
"""场景十四：SSC收藏夹收到"入职协议"关键词 -> 取当日入职信息文件里每个人的转正
审批表链接 -> 每人一条草稿进收藏夹 -> 审批码15放行后逐个私发工作TG（没有用私人TG）。
入职信息文件的真实排版没有样例，这里覆盖几种可能的排版，缺链接/缺TG的人不硬发。"""

import ast
import asyncio
import io
import zipfile
import random
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

from onboarding_agreement import (
    AGREEMENT_LINK_MESSAGE, build_agreement_message, build_agreement_recipients,
    docx_to_text, extract_agreement_link, extract_contact_tg, matches_daily_file_name,
    split_person_records, strip_trigger_keyword,
)

LINK_A = "https://docs.google.com/document/d/AAA/edit"
LINK_B = "https://docs.google.com/document/d/BBB/edit"

MULTI_SECTION = f"""【入职信息同步】
花名：毛小婕
工作TG：@maoxiaojie01
私人TG：@mxj_private
转正审批表：{LINK_A}

【入职信息同步】
花名：郑元宝
工作TG：同上
私人TG：@zhengyuanbao
转正审批表
{LINK_B}
"""


class MatchFileNameTests(unittest.TestCase):
    def test_date_prefix(self):
        self.assertTrue(matches_daily_file_name("2026-10-13_入职信息_毛小婕_郑元宝.gdoc", "2026-10-13"))

    def test_compact_date_suffix_legacy(self):
        self.assertTrue(matches_daily_file_name("心昕_木梨_入职信息_20261013 (1).txt", "2026-10-13"))

    def test_other_day_or_other_file(self):
        self.assertFalse(matches_daily_file_name("2026-10-12_入职信息_x.gdoc", "2026-10-13"))
        self.assertFalse(matches_daily_file_name("2026-10-13_模版.gdoc", "2026-10-13"))


class ParsingTests(unittest.TestCase):
    def test_split_by_repeated_header(self):
        self.assertEqual(len(split_person_records(MULTI_SECTION)), 2)

    def test_split_by_name_lines_without_headers(self):
        text = "花名：甲\n工作TG：@jiajia\n花名：乙\n工作TG：@yiyiyi"
        self.assertEqual(len(split_person_records(text)), 2)

    def test_single_person_not_split(self):
        self.assertEqual(len(split_person_records("花名：甲\n工作TG：@jiajia")), 1)

    def test_link_same_line_and_next_line(self):
        a, b = split_person_records(MULTI_SECTION)
        self.assertEqual(extract_agreement_link(a), LINK_A)
        self.assertEqual(extract_agreement_link(b), LINK_B)

    def test_link_missing(self):
        self.assertEqual(extract_agreement_link("花名：甲\n工作TG：@jiajia"), "")

    def test_work_tg_preferred_then_personal_fallback(self):
        a, b = split_person_records(MULTI_SECTION)
        self.assertEqual(extract_contact_tg(a), ("@maoxiaojie01", "工作TG"))
        self.assertEqual(extract_contact_tg(b), ("@zhengyuanbao", "私人TG"))  # 工作TG填"同上"

    def test_no_tg(self):
        self.assertEqual(extract_contact_tg("花名：甲"), ("", ""))

    def test_recipients_dedupe_same_tg(self):
        recipients = build_agreement_recipients([MULTI_SECTION, MULTI_SECTION])
        self.assertEqual([r["name"] for r in recipients], ["毛小婕", "郑元宝"])

    def test_message_text(self):
        self.assertEqual(build_agreement_message(LINK_A), f"{AGREEMENT_LINK_MESSAGE}\n{LINK_A}")
        self.assertNotIn("入职协议", AGREEMENT_LINK_MESSAGE)


def _make_docx():
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    body = (
        f'<w:document xmlns:w="{w}" xmlns:r="{r}"><w:body>'
        '<w:p><w:r><w:t>【入职信息同步】</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>花名</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:t>毛小婕</w:t></w:r></w:p></w:tc></w:tr>'
        '<w:tr><w:tc><w:p><w:r><w:t>工作TG</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:t>@maoxiaojie01</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
        '<w:p><w:r><w:t>转正审批表：</w:t></w:r>'
        '<w:hyperlink r:id="rId9"><w:r><w:t>点击打开</w:t></w:r></w:hyperlink></w:p>'
        '</w:body></w:document>'
    )
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f'<Relationship Id="rId9" Target="{LINK_A}" TargetMode="External"/></Relationships>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", body)
        zf.writestr("word/_rels/document.xml.rels", rels)
    return buf.getvalue()


class DocxTests(unittest.TestCase):
    def test_docx_table_rows_and_hyperlink_target_are_extracted(self):
        text = docx_to_text(_make_docx())
        self.assertIn("花名：毛小婕", text)
        self.assertEqual(extract_contact_tg(text), ("@maoxiaojie01", "工作TG"))
        # 显示文字是"点击打开"，真实地址在超链接关系里，必须能取到。
        self.assertEqual(extract_agreement_link(text), LINK_A)

    def test_strip_trigger_keyword(self):
        out = strip_trigger_keyword("远程员工入职协议书.docx", "入职协议")
        self.assertNotIn("入职协议", out)
        self.assertIn("入职", out)


# ---------- 监听器（AST提取main.py里的函数） ----------
tree = ast.parse(Path(__file__).with_name("main.py").read_text())
names = {"on_ssc_onboarding_agreement_trigger", "on_ssc_onboarding_agreement_release"}
funcs = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
for n in funcs:
    n.decorator_list = []
config = NS(
    EXCLUDED_CHAT_IDS=frozenset(), ONBOARDING_AGREEMENT_TRIGGER_KEYWORD="入职协议",
    ONBOARDING_AGREEMENT_ENABLED=True, ONBOARDING_AGREEMENT_APPROVAL_CODE="15",
    DAILY_REPORT_TIMEZONE="Asia/Shanghai",
)
ns = dict(
    config=config, asyncio=asyncio, random=random, datetime=datetime, ZoneInfo=ZoneInfo,
    build_agreement_message=build_agreement_message,
    build_agreement_recipients=build_agreement_recipients,
    strip_trigger_keyword=strip_trigger_keyword,
)
exec(compile(ast.Module(body=funcs, type_ignores=[]), "<agreement>", "exec"), ns)


class Store:
    def __init__(self):
        self.data = {}

    def get(self, k):
        return self.data.get(k)

    def set(self, k, v):
        self.data[k] = v

    def update(self, k, **v):
        self.data.setdefault(k, {}).update(v)

    def all(self):
        return self.data


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.drafts = {}

        async def send_message(target, text, **kw):
            msg = NS(id=100 + len(self.drafts), raw_text=text)
            self.drafts[msg.id] = msg
            return msg

        async def get_messages(chat, ids):
            return self.drafts.get(ids)

        ns["agreement_events"], ns["state"], ns["outbox"] = Store(), Store(), Store()
        ns["agreement_lock"], ns["ssc_send_lock"] = asyncio.Lock(), asyncio.Lock()
        ns["log"] = NS(info=lambda *a: None, warning=lambda *a: None, exception=lambda *a: None)
        ns["get_ssc_reviewer"] = AsyncMock(return_value=NS(id=99))
        self.client = NS(
            send_message=AsyncMock(side_effect=send_message),
            get_messages=AsyncMock(side_effect=get_messages),
            get_entity=AsyncMock(side_effect=lambda u: NS(entity=u)),
            delete_messages=AsyncMock(),
        )
        ns["client"] = self.client
        ns["agreement_drive"] = NS(find_daily_files=Mock(return_value=([MULTI_SECTION], ["a.docx"])))
        sleeps = []
        ns["asyncio"] = NS(to_thread=asyncio.to_thread, sleep=AsyncMock(side_effect=lambda s: sleeps.append(s)))
        self.sleeps = sleeps
        config.ONBOARDING_AGREEMENT_ENABLED = True

    def _event(self, text="入职协议", msg_id=1, chat_id=99, sender_id=99, is_private=True):
        return NS(chat_id=chat_id, sender_id=sender_id, is_private=is_private,
                  raw_text=text, message=NS(id=msg_id))

    def _sent_texts(self):
        return [c.args[1] for c in self.client.send_message.call_args_list]

    async def test_trigger_creates_one_draft_per_person(self):
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        pending = [i for i in ns["outbox"].all().values() if i["status"] == "pending"]
        self.assertEqual(sorted(i["destination"] for i in pending), ["@maoxiaojie01", "@zhengyuanbao"])
        self.assertTrue(all(i["kind"] == "onboarding_agreement_link" for i in pending))
        self.assertTrue(all(i["approval_code"] == "15" for i in pending))
        summary = self._sent_texts()[-1]
        self.assertIn("毛小婕 → @maoxiaojie01（工作TG）", summary)
        self.assertIn("郑元宝 → @zhengyuanbao（私人TG）", summary)

    async def test_missing_link_or_tg_not_drafted_but_reported(self):
        ns["agreement_drive"].find_daily_files.return_value = ([
            f"花名：甲\n工作TG：@jiajia1\n花名：乙\n转正审批表：{LINK_A}"
        ], [])
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        self.assertEqual(ns["outbox"].all(), {})
        summary = self._sent_texts()[-1]
        self.assertIn("甲：文件里没找到转正审批表链接", summary)
        self.assertIn("乙：没有工作TG/私人TG", summary)

    async def test_notices_never_contain_trigger_keyword(self):
        # 回归：收藏夹里机器人自己发的提示会被同一个监听器收到，不能带"入职协议"。
        for scenario in ("normal", "nofile", "fail", "disabled", "problems"):
            self.client.send_message.reset_mock()
            ns["agreement_events"].data.clear()
            config.ONBOARDING_AGREEMENT_ENABLED = scenario != "disabled"
            find = ns["agreement_drive"].find_daily_files
            find.side_effect = RuntimeError("boom") if scenario == "fail" else None
            find.return_value = ([], ["远程员工入职协议书.docx"]) if scenario == "nofile" else (
                (["花名：甲"], []) if scenario == "problems" else ([MULTI_SECTION], []))
            await ns["on_ssc_onboarding_agreement_trigger"](self._event())
            for text in self._sent_texts():
                self.assertNotIn("入职协议", text, scenario)
        config.ONBOARDING_AGREEMENT_ENABLED = True

    async def test_no_file_notice_lists_what_the_bot_actually_saw(self):
        ns["agreement_drive"].find_daily_files.return_value = ([], ["旧文件.txt", "远程员工入职协议书.docx"])
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        notice = self._sent_texts()[-1]
        self.assertIn("实际看到2个文件", notice)
        self.assertIn("旧文件.txt", notice)
        self.assertNotIn("入职协议", notice)

    async def test_no_file_and_zero_seen_hints_at_sharing(self):
        ns["agreement_drive"].find_daily_files.return_value = ([], [])
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        self.assertIn("没有分享给机器人的Google服务账号", self._sent_texts()[-1])

    async def test_message_without_keyword_or_wrong_chat_ignored(self):
        await ns["on_ssc_onboarding_agreement_trigger"](self._event(text="随便聊聊"))
        await ns["on_ssc_onboarding_agreement_trigger"](self._event(chat_id=5, is_private=False))
        self.client.send_message.assert_not_awaited()

    async def test_duplicate_event_ignored(self):
        e = self._event()
        await ns["on_ssc_onboarding_agreement_trigger"](e)
        count = self.client.send_message.await_count
        await ns["on_ssc_onboarding_agreement_trigger"](e)
        self.assertEqual(self.client.send_message.await_count, count)

    async def test_retrigger_does_not_duplicate_pending_drafts(self):
        await ns["on_ssc_onboarding_agreement_trigger"](self._event(msg_id=1))
        await ns["on_ssc_onboarding_agreement_trigger"](self._event(msg_id=2))
        self.assertEqual(len([i for i in ns["outbox"].all().values() if i["status"] == "pending"]), 2)

    async def test_release_sends_each_privately_with_delay_and_deletes_drafts(self):
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        self.client.send_message.reset_mock()
        await ns["on_ssc_onboarding_agreement_release"](self._event(text="15", msg_id=50))
        sent = [(c.args[0].entity, c.args[1]) for c in self.client.send_message.call_args_list
                if hasattr(c.args[0], "entity")]
        self.assertEqual({t for t, _ in sent}, {"@maoxiaojie01", "@zhengyuanbao"})
        self.assertIn(build_agreement_message(LINK_A), [m for _, m in sent])
        self.assertEqual(self.client.delete_messages.await_count, 2)
        self.assertEqual(len(self.sleeps), 1)
        self.assertTrue(5 <= self.sleeps[0] <= 10)
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        self.assertEqual(ns["state"].get(f"agreement_link:{today}:@maoxiaojie01")["stage"], "agreement_link_sent")
        # 已发送的人再次触发不再生成草稿
        self.client.send_message.reset_mock()
        await ns["on_ssc_onboarding_agreement_trigger"](self._event(msg_id=3))
        self.assertEqual(len([i for i in ns["outbox"].all().values() if i["status"] == "pending"]), 0)

    async def test_release_failure_marks_failed_and_notifies(self):
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        self.client.get_entity.side_effect = ValueError("no such user")
        self.client.send_message.reset_mock()
        await ns["on_ssc_onboarding_agreement_release"](self._event(text="15", msg_id=50))
        statuses = {i["status"] for i in ns["outbox"].all().values()}
        self.assertEqual(statuses, {"failed"})
        self.assertTrue(any("失败" in t for t in self._sent_texts()))

    async def test_release_ignored_when_not_code_or_disabled(self):
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        self.client.send_message.reset_mock()
        await ns["on_ssc_onboarding_agreement_release"](self._event(text="14"))
        config.ONBOARDING_AGREEMENT_ENABLED = False
        await ns["on_ssc_onboarding_agreement_release"](self._event(text="15"))
        self.client.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
