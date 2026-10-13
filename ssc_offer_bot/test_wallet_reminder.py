# -*- coding: utf-8 -*-
"""场景十五：收藏夹"钱包提醒" -> 花名册今日入职(AR列) vs 钱包表单"首次提交（新人入职）"
条目 -> 没填写的人生成提醒草稿 -> 审批码17放行后逐个私发工作TG(AE列)。"""

import ast
import asyncio
import random
import unittest
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

from onboarding_agreement import strip_trigger_keyword
from wallet_reminder import (
    WALLET_REMINDER_MESSAGE, has_filled, normalize_work_tg, parse_roster_people,
    parse_wallet_entries, person_label, plan_wallet_reminders, select_hired_on,
)

TODAY = datetime.now(ZoneInfo("Asia/Shanghai")).date()
TODAY_STR = TODAY.isoformat()


def roster_row(b="", c="", ar="", ae=""):
    row = [""] * 44            # A..AR
    row[1], row[2], row[43] = b, c, ar
    row += [""] * 8            # ..AZ
    row[30] = ae               # AE
    return row


def form_row(c="", d="", f=""):
    row = [""] * 6
    row[2], row[3], row[5] = c, d, f
    return row


HEADER = ["h"] * 50
FIRST = "首次提交（新人入职）"


class ParsingTests(unittest.TestCase):
    def test_roster_people_and_date_filter(self):
        rows = [HEADER,
                roster_row("DN0001", "毛小婕", TODAY_STR, "@maoxiaojie01"),
                roster_row("DN0002", "郑元宝", "2020-01-01", "@zyb"),
                roster_row("", "", TODAY_STR, "@nobody"),          # B、C都空：跳过
                roster_row("DN0003", "奕辰", "not a date")]
        people = parse_roster_people(rows)
        self.assertEqual([p["key_c"] for p in people], ["毛小婕", "郑元宝", "奕辰"])
        self.assertEqual([p["key_c"] for p in select_hired_on(people, TODAY)], ["毛小婕"])
        self.assertEqual(people[0]["work_tg"], "@maoxiaojie01")

    def test_only_first_submit_new_hire_entries_count(self):
        rows = [["h"] * 6,
                form_row("DN0001", "毛小婕", FIRST),
                form_row("DN0002", "郑元宝", "变更地址"),
                form_row("DN0003", "奕辰", "首次提交(新人入职)"),   # 半角括号也认
                form_row("", "", FIRST)]
        entries = parse_wallet_entries(rows)
        self.assertEqual(len(entries), 2)

    def test_matching_is_normalized_and_order_free(self):
        entries = parse_wallet_entries([["h"] * 6, form_row("毛小婕", "dn0001 ", FIRST)])
        self.assertTrue(has_filled({"key_b": "DN0001", "key_c": "毛小婕"}, entries))
        self.assertFalse(has_filled({"key_b": "DN0001", "key_c": "别人"}, entries))   # 两个值必须都对上
        self.assertTrue(has_filled({"key_b": "", "key_c": "毛小婕"}, entries))        # 只有一个值时按这一个
        self.assertFalse(has_filled({"key_b": "", "key_c": ""}, entries))

    def test_normalize_work_tg(self):
        n = normalize_work_tg
        self.assertEqual(n("@maoxiaojie01"), "@maoxiaojie01")
        self.assertEqual(n(" maoxiaojie01 "), "@maoxiaojie01")
        self.assertEqual(n("https://t.me/maoxiaojie01"), "@maoxiaojie01")
        self.assertEqual(n("工作TG：@maoxiaojie01"), "@maoxiaojie01")
        for bad in ("", "待补充", "同上", "无", "毛小婕", "abc@gmail.com"):
            self.assertEqual(n(bad), "", bad)


class PlanTests(unittest.TestCase):
    def test_plan(self):
        roster = [HEADER,
                  roster_row("DN1", "已填", TODAY_STR, "@filled01"),
                  roster_row("DN2", "没填", TODAY_STR, "@unfilled2"),
                  roster_row("DN3", "没填没TG", TODAY_STR, "待补充"),
                  roster_row("DN4", "重复TG", TODAY_STR, "@unfilled2"),
                  roster_row("DN5", "昨天入职", "2020-01-01", "@old001")]
        wallet = [["h"] * 6,
                  form_row("DN1", "已填", FIRST),
                  form_row("DN2", "没填", "变更地址")]     # 类型不对不算填写
        plan = plan_wallet_reminders(roster, wallet, TODAY)
        self.assertEqual(len(plan["hired"]), 4)
        self.assertEqual([p["key_c"] for p in plan["filled"]], ["已填"])
        self.assertEqual([(p["key_c"], p["tg"]) for p in plan["to_remind"]], [("没填", "@unfilled2")])
        self.assertEqual([person_label(p) for p in plan["no_tg"]], ["没填没TG"])

    def test_message_text(self):
        self.assertEqual(WALLET_REMINDER_MESSAGE,
                         "请及时填写钱包表单并发送邮件给ssc，详细规则查看扶摇-ssc-bot 机器人 新人入职通知 待办事项2")
        self.assertNotIn("钱包提醒", WALLET_REMINDER_MESSAGE)


# ---------- 监听器（AST提取main.py里的函数） ----------
tree = ast.parse(Path(__file__).with_name("main.py").read_text())
names = {"on_ssc_wallet_reminder_trigger", "on_ssc_wallet_reminder_release"}
funcs = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
for n in funcs:
    n.decorator_list = []
config = NS(
    EXCLUDED_CHAT_IDS=frozenset(), WALLET_REMINDER_TRIGGER_KEYWORD="钱包提醒",
    WALLET_REMINDER_ENABLED=True, WALLET_REMINDER_APPROVAL_CODE="17",
    DAILY_REPORT_TIMEZONE="Asia/Shanghai",
)
ns = dict(
    config=config, asyncio=asyncio, random=random, datetime=datetime, ZoneInfo=ZoneInfo,
    WALLET_REMINDER_MESSAGE=WALLET_REMINDER_MESSAGE, plan_wallet_reminders=plan_wallet_reminders,
    person_label=person_label, strip_trigger_keyword=strip_trigger_keyword,
)
exec(compile(ast.Module(body=funcs, type_ignores=[]), "<wallet>", "exec"), ns)


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


ROSTER = [HEADER,
          roster_row("DN1", "已填", TODAY_STR, "@filled01"),
          roster_row("DN2", "没填甲", TODAY_STR, "@unfilled2"),
          roster_row("DN3", "没填乙", TODAY_STR, "https://t.me/unfilled3"),
          roster_row("DN4", "没TG", TODAY_STR, "")]
WALLET = [["h"] * 6, form_row("DN1", "已填", FIRST)]


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.drafts = {}

        async def send_message(target, text, **kw):
            msg = NS(id=100 + len(self.drafts), raw_text=text)
            self.drafts[msg.id] = msg
            return msg

        async def get_messages(chat, ids):
            return self.drafts.get(ids)

        ns["wallet_reminder_events"], ns["state"], ns["outbox"] = Store(), Store(), Store()
        ns["wallet_reminder_lock"], ns["ssc_send_lock"] = asyncio.Lock(), asyncio.Lock()
        ns["log"] = NS(info=lambda *a: None, warning=lambda *a: None, exception=lambda *a: None)
        ns["get_ssc_reviewer"] = AsyncMock(return_value=NS(id=99))
        self.client = NS(
            send_message=AsyncMock(side_effect=send_message),
            get_messages=AsyncMock(side_effect=get_messages),
            get_entity=AsyncMock(side_effect=lambda u: NS(entity=u)),
            delete_messages=AsyncMock(),
        )
        ns["client"] = self.client
        ns["training_sync_roster_repo"] = NS(load_rows=Mock(return_value=ROSTER))
        ns["wallet_form_repo"] = NS(load_rows=Mock(return_value=WALLET))
        sleeps = []
        ns["asyncio"] = NS(to_thread=asyncio.to_thread, sleep=AsyncMock(side_effect=lambda s: sleeps.append(s)))
        self.sleeps = sleeps
        config.WALLET_REMINDER_ENABLED = True

    def _event(self, text="钱包提醒", msg_id=1, chat_id=99, sender_id=99, is_private=True):
        return NS(chat_id=chat_id, sender_id=sender_id, is_private=is_private,
                  raw_text=text, message=NS(id=msg_id))

    def _sent_texts(self):
        return [c.args[1] for c in self.client.send_message.call_args_list]

    def _pending(self):
        return [i for i in ns["outbox"].all().values() if i["status"] == "pending"]

    async def test_trigger_drafts_only_for_people_who_have_not_filled(self):
        await ns["on_ssc_wallet_reminder_trigger"](self._event())
        self.assertEqual(sorted(i["destination"] for i in self._pending()), ["@unfilled2", "@unfilled3"])
        self.assertTrue(all(i["kind"] == "wallet_reminder" and i["approval_code"] == "17" for i in self._pending()))
        drafts = [t for t in self._sent_texts() if t == WALLET_REMINDER_MESSAGE]
        self.assertEqual(len(drafts), 2)
        summary = self._sent_texts()[-1]
        self.assertIn("今日（%s）入职4人，已填写钱包表单1人，需要提醒3人" % TODAY_STR, summary)
        self.assertIn("没填甲 → @unfilled2", summary)
        self.assertIn("发送 17 放行", summary)
        self.assertIn("没TG", summary)       # 没有工作TG的人单独列出来人工处理

    async def test_all_filled_or_nobody_today(self):
        ns["wallet_form_repo"].load_rows.return_value = [["h"] * 6] + [
            form_row(f"DN{i}", n, FIRST) for i, n in ((1, "已填"), (2, "没填甲"), (3, "没填乙"), (4, "没TG"))]
        await ns["on_ssc_wallet_reminder_trigger"](self._event(msg_id=1))
        self.assertEqual(self._pending(), [])
        self.assertIn("都已填写", self._sent_texts()[-1])
        ns["training_sync_roster_repo"].load_rows.return_value = [HEADER]
        await ns["on_ssc_wallet_reminder_trigger"](self._event(msg_id=2))
        self.assertIn("没有入职的人", self._sent_texts()[-1])
        ns["training_sync_roster_repo"].load_rows.return_value = ROSTER

    async def test_notices_never_contain_trigger_keyword(self):
        # 回归：收藏夹里机器人自己发的提示会被同一个监听器收到，不能带"钱包提醒"。
        for scenario in ("normal", "fail", "disabled", "nobody"):
            self.client.send_message.reset_mock()
            ns["wallet_reminder_events"].data.clear()
            config.WALLET_REMINDER_ENABLED = scenario != "disabled"
            ns["training_sync_roster_repo"].load_rows.side_effect = RuntimeError("钱包提醒 403") if scenario == "fail" else None
            ns["training_sync_roster_repo"].load_rows.return_value = [HEADER] if scenario == "nobody" else ROSTER
            await ns["on_ssc_wallet_reminder_trigger"](self._event())
            for text in self._sent_texts():
                self.assertNotIn("钱包提醒", text, scenario)
        config.WALLET_REMINDER_ENABLED = True
        ns["training_sync_roster_repo"].load_rows.side_effect = None
        ns["training_sync_roster_repo"].load_rows.return_value = ROSTER

    async def test_sheet_error_reported(self):
        ns["wallet_form_repo"].load_rows.side_effect = RuntimeError("403 Client Error: Forbidden")
        await ns["on_ssc_wallet_reminder_trigger"](self._event())
        self.assertIn("403", self._sent_texts()[-1])
        self.assertEqual(self._pending(), [])
        ns["wallet_form_repo"].load_rows.side_effect = None

    async def test_ignored_without_keyword_or_in_other_chats(self):
        await ns["on_ssc_wallet_reminder_trigger"](self._event(text="随便聊聊"))
        await ns["on_ssc_wallet_reminder_trigger"](self._event(chat_id=5, is_private=False))
        self.client.send_message.assert_not_awaited()

    async def test_retrigger_does_not_duplicate_pending_and_duplicate_event_ignored(self):
        e = self._event(msg_id=1)
        await ns["on_ssc_wallet_reminder_trigger"](e)
        count = self.client.send_message.await_count
        await ns["on_ssc_wallet_reminder_trigger"](e)                       # 同一条消息重复事件
        self.assertEqual(self.client.send_message.await_count, count)
        await ns["on_ssc_wallet_reminder_trigger"](self._event(msg_id=2))   # 再发一次关键词
        self.assertEqual(len(self._pending()), 2)
        self.assertIn("已有待发送草稿", self._sent_texts()[-1])

    async def test_release_sends_privately_with_delay_and_deletes_drafts(self):
        await ns["on_ssc_wallet_reminder_trigger"](self._event())
        self.client.send_message.reset_mock()
        await ns["on_ssc_wallet_reminder_release"](self._event(text="17", msg_id=50))
        sent = [(c.args[0].entity, c.args[1]) for c in self.client.send_message.call_args_list
                if hasattr(c.args[0], "entity")]
        self.assertEqual(sorted(t for t, _ in sent), ["@unfilled2", "@unfilled3"])
        self.assertTrue(all(m == WALLET_REMINDER_MESSAGE for _, m in sent))
        self.assertEqual(self.client.delete_messages.await_count, 2)
        self.assertEqual(len(self.sleeps), 1)
        self.assertTrue(5 <= self.sleeps[0] <= 10)
        self.assertEqual(ns["state"].get(f"wallet_reminder:{TODAY_STR}:@unfilled2")["stage"], "wallet_reminder_sent")
        # 已提醒过的人再触发不再出草稿
        await ns["on_ssc_wallet_reminder_trigger"](self._event(msg_id=3))
        self.assertEqual(self._pending(), [])
        self.assertIn("今天已提醒过", self._sent_texts()[-1])

    async def test_release_failure_marks_failed_and_notifies(self):
        await ns["on_ssc_wallet_reminder_trigger"](self._event())
        self.client.get_entity.side_effect = ValueError("no such user")
        self.client.send_message.reset_mock()
        await ns["on_ssc_wallet_reminder_release"](self._event(text="17", msg_id=50))
        self.assertEqual({i["status"] for i in ns["outbox"].all().values()}, {"failed"})
        self.assertTrue(any("失败" in t for t in self._sent_texts()))

    async def test_release_ignored_for_other_codes_or_disabled_or_foreign_sender(self):
        await ns["on_ssc_wallet_reminder_trigger"](self._event())
        self.client.send_message.reset_mock()
        for kwargs in ({"text": "15"}, {"text": "171"}, {"text": "17", "sender_id": 7}):
            await ns["on_ssc_wallet_reminder_release"](self._event(**kwargs))
        config.WALLET_REMINDER_ENABLED = False
        await ns["on_ssc_wallet_reminder_release"](self._event(text="17"))
        config.WALLET_REMINDER_ENABLED = True
        self.client.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
