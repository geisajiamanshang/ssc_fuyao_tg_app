# -*- coding: utf-8 -*-
"""场景十四：SSC收藏夹收到"入职协议"关键词 -> 取当日入职信息文件里的每个人 ->
按"花名_入职协议_日期"到Drive找协议文件链接 -> 每人一条草稿进收藏夹 -> 审批码15
放行后逐个私发工作TG（没有用私人TG）。缺协议文件/缺TG的人不硬发。"""

import ast
import asyncio
import io
import zipfile
import onboarding_agreement
import random
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

from onboarding_agreement import (
    AGREEMENT_LINK_MESSAGE, OnboardingAgreementFilesRepository, build_agreement_message, build_agreement_recipients,
    docx_to_text, extract_agreement_link, extract_contact_tg, matches_daily_file_name,
    matches_agreement_file_name, split_person_records, strip_trigger_keyword,
)

LINK_A = "https://docs.google.com/document/d/AAA/edit"
LINK_B = "https://docs.google.com/document/d/BBB/edit"

# 按《步骤》模版生成的入职信息文件：每人一段【新人入职通知】，文件里没有任何链接。
TEMPLATE_FILE = """【新人入职通知】

日期：2026-10-13
花名：毛小婕
简历名：甲
编号：DN0001
岗位：前端工程师
部门-小组：研发部-前端组
私人tg：@mxj_private
工作 tg: @maoxiaojie01  
（备注：和私人tg一样就是 待补充）
工作gmail: 待补充

备注：已培训完成，@DaBai10010 @wdz999 请知悉

【新人入职通知】

日期：2026-10-13
花名：郑元宝
岗位：运营专员
私人tg：@zhengyuanbao
工作 tg: 待补充

【入职信息同步】

入职日期：2026-10-13
花名：毛小婕
私人TG：@mxj_private

【欢迎】

🎉 欢迎 毛小婕 @maoxiaojie01 加入恒睿大家庭！
"""

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
        self.assertEqual(extract_agreement_link(f"入职协议：{LINK_A}"), LINK_A)

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
        self.assertEqual(AGREEMENT_LINK_MESSAGE, "这是你的入职协议链接，请签字哦")
        self.assertEqual(build_agreement_message(LINK_A), f"{AGREEMENT_LINK_MESSAGE}\n{LINK_A}")

    def test_template_file_one_person_per_notice_section(self):
        recipients = build_agreement_recipients([TEMPLATE_FILE])
        self.assertEqual([(r["name"], r["tg"], r["tg_source"], r["link"]) for r in recipients], [
            ("毛小婕", "@maoxiaojie01", "工作TG", ""),   # "工作 tg:"带空格、小写
            ("郑元宝", "@zhengyuanbao", "私人TG", ""),   # 工作tg待补充 -> 退回私人tg
        ])

    def test_same_person_in_two_files_deduped_even_without_tg(self):
        recipients = build_agreement_recipients(["花名：甲\n岗位：x", "花名：甲\n岗位：x"])
        self.assertEqual(len(recipients), 1)


class AgreementFileTests(unittest.TestCase):
    def test_name_pattern(self):
        ok = matches_agreement_file_name
        self.assertTrue(ok("毛小婕_入职协议_20261013.docx", "毛小婕", "2026-10-13"))
        self.assertTrue(ok("阿林_入职协议_20260923_新版.docx", "阿林", "2026-09-23"))
        self.assertTrue(ok("毛小婕_入职协议_2026-10-13", "毛小婕", "2026-10-13"))
        self.assertTrue(ok("毛小婕_入职协议_2026-10-13", "毛小婕", "2026-10-13"))
        self.assertTrue(ok("毛小婕_入职协议_2026-10-5", "毛小婕", "2026-10-05"))

    def test_name_pattern_rejects(self):
        ok = matches_agreement_file_name
        self.assertFalse(ok("郑元宝_入职协议_20261013.docx", "元宝", "2026-10-13"))      # 花名必须开头
        self.assertFalse(ok("毛小婕_入职协议_20261012.docx", "毛小婕", "2026-10-13"))    # 别的日期
        self.assertFalse(ok("毛小婕_入职信息_20261013.docx", "毛小婕", "2026-10-13"))    # 不是协议
        self.assertFalse(ok("毛小婕_入职协议_20261013.docx", "", "2026-10-13"))

    def test_repository_picks_newest_and_searches_all_folders(self):
        files = {
            "out": [
                {"id": "1", "name": "毛小婕_入职协议_20261013.docx", "mimeType": "application/x", "modifiedTime": "2026-10-13T01:00:00Z"},
                {"id": "2", "name": "毛小婕_入职协议_20261013", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "2026-10-13T03:00:00Z"},
            ],
            "up": [{"id": "3", "name": "郑元宝_入职协议_20261013.docx", "mimeType": "application/x", "modifiedTime": "2026-10-13T02:00:00Z"}],
        }
        orig = (onboarding_agreement._drive_session, onboarding_agreement.collect_folder_files)
        onboarding_agreement._drive_session = lambda **kw: (None, {})
        onboarding_agreement.collect_folder_files = lambda session, auth, folder: files[folder]
        try:
            links = OnboardingAgreementFilesRepository(["out", "up"]).find_agreement_links(
                "2026-10-13", ["毛小婕", "郑元宝", "奕辰"])
        finally:
            onboarding_agreement._drive_session, onboarding_agreement.collect_folder_files = orig
        self.assertEqual(links, {
            "毛小婕": "https://docs.google.com/document/d/2/edit",
            "郑元宝": "https://drive.google.com/file/d/3/view",
        })


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
    strip_trigger_keyword=strip_trigger_keyword, AGREEMENT_LINK_MESSAGE=AGREEMENT_LINK_MESSAGE,
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
        self.find_links = Mock(return_value={})
        ns["agreement_files"] = NS(find_agreement_links=self.find_links)
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

    async def test_missing_file_or_tg_not_drafted_but_reported(self):
        ns["agreement_drive"].find_daily_files.return_value = ([
            "花名：甲\n工作TG：@jiajia1\n花名：乙\n转正审批表：" + LINK_A
        ], [])
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        self.assertEqual(ns["outbox"].all(), {})
        summary = self._sent_texts()[-1]
        self.assertIn("甲：没找到", summary)
        self.assertIn("乙：没有工作TG/私人TG", summary)

    async def test_links_come_from_agreement_files_in_drive(self):
        ns["agreement_drive"].find_daily_files.return_value = ([TEMPLATE_FILE], [])
        self.find_links.return_value = {"毛小婕": LINK_A, "郑元宝": LINK_B}
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        self.find_links.assert_called_once()
        self.assertEqual(self.find_links.call_args.args[1], ["毛小婕", "郑元宝"])
        drafts = [t for t in self._sent_texts() if t.startswith(AGREEMENT_LINK_MESSAGE)]
        self.assertEqual(sorted(drafts), sorted([f"{AGREEMENT_LINK_MESSAGE}\n{LINK_A}", f"{AGREEMENT_LINK_MESSAGE}\n{LINK_B}"]))

    async def test_person_without_agreement_file_reported_others_still_drafted(self):
        ns["agreement_drive"].find_daily_files.return_value = ([TEMPLATE_FILE], [])
        self.find_links.return_value = {"毛小婕": LINK_A}
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        pending = [i for i in ns["outbox"].all().values() if i["status"] == "pending"]
        self.assertEqual([i["destination"] for i in pending], ["@maoxiaojie01"])
        self.assertIn("郑元宝：没找到", self._sent_texts()[-1])

    async def test_own_draft_in_saved_messages_does_not_retrigger(self):
        # 回归：草稿文案含"入职协议"，机器人把它发进收藏夹后会收到自己的消息。
        await ns["on_ssc_onboarding_agreement_trigger"](self._event(text=build_agreement_message(LINK_A)))
        self.client.send_message.assert_not_awaited()
        ns["agreement_drive"].find_daily_files.assert_not_called()

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
                if text.startswith(AGREEMENT_LINK_MESSAGE):
                    continue  # 草稿是发给员工的文案，本来就带关键词，由监听器开头的守卫忽略
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
