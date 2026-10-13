# -*- coding: utf-8 -*-
"""场景十四：SSC收藏夹收到"入职协议"关键词 -> 到入职协议文件夹的当月文件夹找当日入职
的协议 -> 读协议里的私人TG -> 每人一条"协议链接"草稿进收藏夹 -> 审批码15放行后
逐个私发。读不到TG的人不硬发。"""

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

import onboarding_agreement
from onboarding_agreement import (
    AGREEMENT_LINK_MESSAGE, OnboardingAgreementRepository, build_agreement_message,
    docx_to_text, drive_file_link, extract_private_tg, matches_agreement_file_name,
    matches_month_folder, person_name_from_file_name, strip_trigger_keyword,
)

LINK_A = "https://docs.google.com/document/d/AAA/edit"
LINK_B = "https://drive.google.com/file/d/BBB/view"

AGREEMENT_TEXT_A = """远程员工入职协议书
甲方：恒睿
乙方（员工）：毛小婕
私人TG：@mxj_private
工作TG：@maoxiaojie01
SSC签字：扶摇
"""
AGREEMENT_TEXT_B = "乙方：郑元宝\n私人 tg: @zhengyuanbao  \n联系邮箱：zyb@gmail.com\n"


class NameMatchingTests(unittest.TestCase):
    def test_month_folder_variants(self):
        for name in ("2026年-10月", "2026年10月", "2026-10", "202610", "2026年-10月 入职协议"):
            self.assertTrue(matches_month_folder(name, "2026-10-13"), name)

    def test_month_folder_rejects_other_months(self):
        for name in ("2026年-9月", "2025年-10月", "2026年-11月", "模版"):
            self.assertFalse(matches_month_folder(name, "2026-10-13"), name)

    def test_agreement_file_name(self):
        ok = matches_agreement_file_name
        self.assertTrue(ok("毛小婕_入职协议_20261013.docx", "2026-10-13"))
        self.assertTrue(ok("毛小婕_入职协议_2026-10-13", "2026-10-13"))
        self.assertTrue(ok("阿林_入职协议_20261005_新版.docx", "2026-10-05"))
        self.assertFalse(ok("毛小婕_入职协议_20261012.docx", "2026-10-13"))   # 别的日期
        self.assertFalse(ok("毛小婕_入职信息_20261013.docx", "2026-10-13"))   # 不是协议
        self.assertFalse(ok("远程员工入职协议书.docx", "2026-10-13"))          # 模版无日期

    def test_person_name_from_file_name(self):
        self.assertEqual(person_name_from_file_name("毛小婕_入职协议_20261013.docx"), "毛小婕")
        self.assertEqual(person_name_from_file_name("入职协议_20261013.docx"), "")

    def test_drive_link(self):
        self.assertEqual(drive_file_link({"id": "X", "mimeType": "application/vnd.google-apps.document"}),
                         "https://docs.google.com/document/d/X/edit")
        self.assertEqual(drive_file_link({"id": "X", "mimeType": "application/x"}),
                         "https://drive.google.com/file/d/X/view")
        self.assertEqual(drive_file_link({"id": "X", "webViewLink": "https://w"}), "https://w")


class PrivateTgTests(unittest.TestCase):
    def test_private_tg_preferred_over_work_tg(self):
        self.assertEqual(extract_private_tg(AGREEMENT_TEXT_A), ("@mxj_private", "私人TG"))

    def test_spaced_lowercase_key_and_email_ignored(self):
        self.assertEqual(extract_private_tg(AGREEMENT_TEXT_B), ("@zhengyuanbao", "私人TG"))

    def test_falls_back_to_work_tg_when_private_is_placeholder(self):
        self.assertEqual(extract_private_tg("私人TG：待补充\n工作TG：@work888"), ("@work888", "工作TG"))

    def test_unique_handle_in_body(self):
        self.assertEqual(extract_private_tg("乙方联系：@solo_user88 请知悉"), ("@solo_user88", "协议内TG"))

    def test_ambiguous_or_missing(self):
        self.assertEqual(extract_private_tg("甲方 @company1 乙方 @person22"), ("", ""))
        self.assertEqual(extract_private_tg("邮箱 abc@gmail.com"), ("", ""))
        self.assertEqual(extract_private_tg(""), ("", ""))

    def test_message_text(self):
        self.assertEqual(AGREEMENT_LINK_MESSAGE, "这是你的入职协议，签字哦")
        self.assertEqual(build_agreement_message(LINK_A), f"{AGREEMENT_LINK_MESSAGE}\n{LINK_A}")


def _make_docx():
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = (
        f'<w:document xmlns:w="{w}"><w:body>'
        '<w:p><w:r><w:t>远程员工入职协议书</w:t></w:r></w:p>'
        '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>私人TG</w:t></w:r></w:p></w:tc>'
        '<w:tc><w:p><w:r><w:t>@maoxiaojie01</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
        '</w:body></w:document>'
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", body)
    return buf.getvalue()


class DocxTests(unittest.TestCase):
    def test_docx_table_row_gives_private_tg(self):
        text = docx_to_text(_make_docx())
        self.assertIn("私人TG：@maoxiaojie01", text)
        self.assertEqual(extract_private_tg(text), ("@maoxiaojie01", "私人TG"))

    def test_strip_trigger_keyword(self):
        out = strip_trigger_keyword("远程员工入职协议书.docx", "入职协议")
        self.assertNotIn("入职协议", out)
        self.assertIn("入职", out)


class RepositoryTests(unittest.TestCase):
    def _run(self, top, month_files, downloads):
        orig = (onboarding_agreement._drive_session,
                onboarding_agreement.OnboardingTrainingDriveRepository._list_children,
                onboarding_agreement.collect_folder_files,
                OnboardingAgreementRepository._download_text)
        onboarding_agreement._drive_session = lambda **kw: (None, {})
        onboarding_agreement.OnboardingTrainingDriveRepository._list_children = staticmethod(
            lambda session, auth, folder: top)
        onboarding_agreement.collect_folder_files = lambda session, auth, folder: month_files[folder]

        def download(session, auth, drive_file):
            result = downloads[drive_file["id"]]
            if isinstance(result, Exception):
                raise result
            return result
        OnboardingAgreementRepository._download_text = staticmethod(download)
        try:
            return OnboardingAgreementRepository("root").find_today_agreements("2026-10-13")
        finally:
            (onboarding_agreement._drive_session,
             onboarding_agreement.OnboardingTrainingDriveRepository._list_children,
             onboarding_agreement.collect_folder_files,
             OnboardingAgreementRepository._download_text) = orig

    FOLDER = "application/vnd.google-apps.folder"

    def test_finds_month_folder_filters_today_and_picks_newest_per_person(self):
        top = [{"id": "m9", "name": "2026年-9月", "mimeType": self.FOLDER},
               {"id": "m10", "name": "2026年-10月", "mimeType": self.FOLDER}]
        files = {"m10": [
            {"id": "1", "name": "毛小婕_入职协议_20261013.docx", "mimeType": "application/x", "modifiedTime": "2026-10-13T01:00:00Z"},
            {"id": "2", "name": "毛小婕_入职协议_20261013", "mimeType": "application/vnd.google-apps.document", "modifiedTime": "2026-10-13T03:00:00Z"},
            {"id": "3", "name": "郑元宝_入职协议_20261013.docx", "mimeType": "application/x", "modifiedTime": "2026-10-13T02:00:00Z"},
            {"id": "4", "name": "奕辰_入职协议_20261012.docx", "mimeType": "application/x", "modifiedTime": "2026-10-12T02:00:00Z"},
        ]}
        agreements, diag = self._run(top, files, {"2": AGREEMENT_TEXT_A, "3": AGREEMENT_TEXT_B})
        self.assertEqual([(a["name"], a["link"], a["error"]) for a in agreements], [
            ("毛小婕", "https://docs.google.com/document/d/2/edit", ""),
            ("郑元宝", "https://drive.google.com/file/d/3/view", ""),
        ])
        self.assertEqual(agreements[0]["text"], AGREEMENT_TEXT_A)
        self.assertEqual(diag["month_folders"], ["2026年-10月"])
        self.assertEqual(len(diag["files"]), 4)

    def test_download_failure_recorded_per_person(self):
        top = [{"id": "m10", "name": "2026年-10月", "mimeType": self.FOLDER}]
        files = {"m10": [
            {"id": "1", "name": "甲_入职协议_20261013.docx", "mimeType": "application/x"},
            {"id": "2", "name": "乙_入职协议_20261013.docx", "mimeType": "application/x"},
        ]}
        agreements, _ = self._run(top, files, {"1": ValueError("坏文件"), "2": AGREEMENT_TEXT_B})
        by_name = {a["name"]: a for a in agreements}
        self.assertIn("坏文件", by_name["甲"]["error"])
        self.assertEqual(by_name["乙"]["error"], "")

    def test_no_month_folder_reports_what_was_seen(self):
        top = [{"id": "m9", "name": "2026年-9月", "mimeType": self.FOLDER}]
        agreements, diag = self._run(top, {}, {})
        self.assertEqual(agreements, [])
        self.assertEqual(diag["month_folders"], [])
        self.assertEqual(diag["root_folders"], ["2026年-9月"])


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
    extract_private_tg=extract_private_tg,
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
        self.agreements = [
            {"name": "毛小婕", "file_name": "毛小婕_入职协议_20261013.docx", "link": LINK_A,
             "text": AGREEMENT_TEXT_A, "error": ""},
            {"name": "郑元宝", "file_name": "郑元宝_入职协议_20261013.docx", "link": LINK_B,
             "text": AGREEMENT_TEXT_B, "error": ""},
        ]
        self.diag = {"root_folders": ["2026年-10月"], "month_folders": ["2026年-10月"], "files": ["a", "b"]}
        self.find = Mock(return_value=(self.agreements, self.diag))
        ns["agreement_repo"] = NS(find_today_agreements=self.find)
        sleeps = []
        ns["asyncio"] = NS(to_thread=asyncio.to_thread, sleep=AsyncMock(side_effect=lambda s: sleeps.append(s)))
        self.sleeps = sleeps
        config.ONBOARDING_AGREEMENT_ENABLED = True

    def _event(self, text="入职协议", msg_id=1, chat_id=99, sender_id=99, is_private=True):
        return NS(chat_id=chat_id, sender_id=sender_id, is_private=is_private,
                  raw_text=text, message=NS(id=msg_id))

    def _sent_texts(self):
        return [c.args[1] for c in self.client.send_message.call_args_list]

    async def test_trigger_creates_one_draft_per_person_with_private_tg(self):
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        pending = [i for i in ns["outbox"].all().values() if i["status"] == "pending"]
        self.assertEqual(sorted(i["destination"] for i in pending), ["@mxj_private", "@zhengyuanbao"])
        self.assertTrue(all(i["kind"] == "onboarding_agreement_link" for i in pending))
        self.assertTrue(all(i["approval_code"] == "15" for i in pending))
        drafts = [t for t in self._sent_texts() if t.startswith(AGREEMENT_LINK_MESSAGE)]
        self.assertEqual(sorted(drafts), sorted([f"这是你的入职协议，签字哦\n{LINK_A}", f"这是你的入职协议，签字哦\n{LINK_B}"]))
        summary = self._sent_texts()[-1]
        self.assertIn("毛小婕 → @mxj_private（私人TG）", summary)
        self.assertIn("郑元宝 → @zhengyuanbao（私人TG）", summary)
        self.assertEqual(self.find.call_args.args[0], datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat())

    async def test_person_without_tg_or_unreadable_file_reported_not_drafted(self):
        self.agreements[0]["text"] = "甲方 @company1 乙方 @person22"
        self.agreements[1]["error"] = "坏文件"
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        self.assertEqual(ns["outbox"].all(), {})
        summary = self._sent_texts()[-1]
        self.assertIn("毛小婕：协议里没找到私人TG", summary)
        self.assertIn("郑元宝：协议文件读取失败（坏文件）", summary)

    async def test_one_bad_person_does_not_block_others(self):
        self.agreements[0]["text"] = "没有任何TG"
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        pending = [i for i in ns["outbox"].all().values() if i["status"] == "pending"]
        self.assertEqual([i["destination"] for i in pending], ["@zhengyuanbao"])
        self.assertIn("毛小婕：协议里没找到私人TG", self._sent_texts()[-1])

    async def test_own_draft_in_saved_messages_does_not_retrigger(self):
        # 回归：草稿文案含"入职协议"，机器人把它发进收藏夹后会收到自己的消息。
        await ns["on_ssc_onboarding_agreement_trigger"](self._event(text=build_agreement_message(LINK_A)))
        self.client.send_message.assert_not_awaited()
        self.find.assert_not_called()

    async def test_notices_never_contain_trigger_keyword(self):
        # 回归：收藏夹里机器人自己发的提示会被同一个监听器收到，不能带"入职协议"。
        scenarios = {
            "normal": (self.agreements, self.diag),
            "no_month": ([], {"root_folders": ["入职协议模版"], "month_folders": [], "files": []}),
            "empty_month": ([], {"root_folders": [], "month_folders": ["2026年-10月"], "files": ["旧入职协议.docx"]}),
            "nothing_seen": ([], {"root_folders": [], "month_folders": [], "files": []}),
        }
        for name, result in scenarios.items():
            self.client.send_message.reset_mock()
            ns["agreement_events"].data.clear()
            self.find.side_effect = None
            self.find.return_value = result
            await ns["on_ssc_onboarding_agreement_trigger"](self._event())
            for text in self._sent_texts():
                if text.startswith(AGREEMENT_LINK_MESSAGE):
                    continue  # 草稿是发给员工的文案，本来就带关键词，由监听器开头的守卫忽略
                self.assertNotIn("入职协议", text, name)
        for name in ("fail", "disabled"):
            self.client.send_message.reset_mock()
            ns["agreement_events"].data.clear()
            self.find.return_value = (self.agreements, self.diag)
            self.find.side_effect = RuntimeError("boom") if name == "fail" else None
            config.ONBOARDING_AGREEMENT_ENABLED = name != "disabled"
            await ns["on_ssc_onboarding_agreement_trigger"](self._event())
            for text in self._sent_texts():
                self.assertNotIn("入职协议", text, name)
        config.ONBOARDING_AGREEMENT_ENABLED = True

    async def test_no_month_folder_notice_lists_what_was_seen(self):
        self.find.return_value = ([], {"root_folders": ["2026年-9月", "模版"], "month_folders": [], "files": []})
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        notice = self._sent_texts()[-1]
        self.assertIn("没有找到当月文件夹", notice)
        self.assertIn("2026年-9月", notice)
        self.assertNotIn("没有分享给机器人", notice)

    async def test_month_folder_without_todays_files_notice(self):
        self.find.return_value = ([], {"root_folders": ["2026年-10月"], "month_folders": ["2026年-10月"],
                                       "files": ["毛小婕_入职协议_20261012.docx"]})
        await ns["on_ssc_onboarding_agreement_trigger"](self._event())
        notice = self._sent_texts()[-1]
        self.assertIn("2026年-10月", notice)
        self.assertIn("实际看到1个文件", notice)

    async def test_nothing_visible_hints_at_sharing(self):
        self.find.return_value = ([], {"root_folders": [], "month_folders": [], "files": []})
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
        self.assertEqual({t for t, _ in sent}, {"@mxj_private", "@zhengyuanbao"})
        self.assertIn(build_agreement_message(LINK_A), [m for _, m in sent])
        self.assertEqual(self.client.delete_messages.await_count, 2)
        self.assertEqual(len(self.sleeps), 1)
        self.assertTrue(5 <= self.sleeps[0] <= 10)
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        self.assertEqual(ns["state"].get(f"agreement_link:{today}:@mxj_private")["stage"], "agreement_link_sent")
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
