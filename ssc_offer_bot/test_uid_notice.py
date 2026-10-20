# -*- coding: utf-8 -*-
"""场景十八：收藏夹"通知uid" -> 等人员名单 -> 花名册按花名找工作TG -> 草稿 -> 审批码19私发。"""

import ast
import asyncio
import random
import re
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from uid_notice import (
    UID_NOTICE_MESSAGE, describe_columns, find_columns, parse_name_list, plan_uid_notices,
)


def row(name="", tg="", status="在职", width=40, name_col=2, tg_col=30, status_col=5):
    r = [""] * width
    r[name_col], r[tg_col], r[status_col] = name, tg, status
    return r


def header(name_col=2, tg_col=30, status_col=5, width=40):
    r = ["x"] * width
    r[name_col], r[tg_col], r[status_col] = "花名*", "工作TG", "在职状态*"
    return r


GROUP_ROW = [""] * 40
ROSTER = [
    ["在职花名册"], GROUP_ROW, header(),
    row("甲", "@jia_user1"),
    row("乙", "https://t.me/yi_user12"),
    row("丙", ""),
    row("丁", "同上"),
    row("张三", "@zhang3_old", status="离职"),
    row("张三", "@zhang3_now"),
    row("李四", "@li4_aaaa"),
    row("李四", "@li4_bbbb"),
    row("王 五", "@wang5_user"),
    row("赵六", "@jia_user1"),          # 工作TG和甲相同
]


class MessageTests(unittest.TestCase):
    def test_message_text_exact(self):
        self.assertEqual(UID_NOTICE_MESSAGE,
                         "请尽快注册stow钱包并填写钱包表单，注册流程在全员群，否则会影响发薪流程")
        self.assertNotIn("通知uid", UID_NOTICE_MESSAGE.casefold())


class ParseTests(unittest.TestCase):
    def test_split_on_newline_space_comma_and_dedupe(self):
        self.assertEqual(parse_name_list("甲\n乙 丙，丁、甲;戊"), ["甲", "乙", "丙", "丁", "戊"])

    def test_numbers_dropped_and_tg_kept(self):
        self.assertEqual(parse_name_list("1 甲\n2 @yi_user12\n19"), ["甲", "@yi_user12"])

    def test_sentences_and_garbage_are_not_a_list(self):
        for text in ("请把需要通知的人员名单（花名）发给我，一行一个", "已生成3条草稿：\n甲 → @jia_user1",
                     "", "   ", "123", "x" * 40, "甲 乙。"):
            self.assertIsNone(parse_name_list(text), text)

    def test_too_many_names_not_a_list(self):
        self.assertIsNone(parse_name_list(" ".join(f"n{i}x" for i in range(201))))


class PlanTests(unittest.TestCase):
    def test_columns_found_by_header_text_not_letter(self):
        self.assertEqual(find_columns(ROSTER), (2, 2, 30, 5))
        moved = [header(name_col=3, tg_col=29, status_col=6), row("甲", "@jia_user1", name_col=3, tg_col=29, status_col=6)]
        self.assertEqual(find_columns(moved), (0, 3, 29, 6))
        self.assertEqual(describe_columns(ROSTER), "花名在C列，工作TG在AE列")

    def test_missing_headers(self):
        self.assertIsNone(find_columns([["a", "b"], ["c"]]))
        self.assertIn("找不到", describe_columns([["a"]]))
        no_tg = ["花名", "别的"]
        self.assertIsNone(find_columns([no_tg]))

    def test_matching_rules(self):
        plan = plan_uid_notices(ROSTER, ["甲", "乙", "丙", "丁", "张三", "李四", "王五", "无此人", "赵六", "@wang5_user"])
        self.assertEqual([(p["name"], p["tg"]) for p in plan["to_send"]],
                         [("甲", "@jia_user1"), ("乙", "@yi_user12"), ("张三", "@zhang3_now"),
                          ("王 五", "@wang5_user")])
        self.assertEqual([p["name"] for p in plan["no_tg"]], ["丙", "丁"])
        self.assertEqual(plan["not_found"], ["无此人"])
        self.assertEqual(plan["ambiguous"], ["李四"])       # 同名两人、在职、TG不同
        # 赵六的TG和甲相同：只留一个，且赵六不再单独发

    def test_only_departed_match_is_still_listed_with_status(self):
        rows = [header(), row("老王", "@lao_wang1", status="离职")]
        plan = plan_uid_notices(rows, ["老王"])
        self.assertEqual(plan["to_send"][0]["status"], "离职")

    def test_name_normalisation(self):
        plan = plan_uid_notices(ROSTER, ["王五", "ＷＡＮＧ"])
        self.assertEqual(len(plan["to_send"]), 1)
        self.assertEqual(plan["not_found"], ["ＷＡＮＧ"])


tree = ast.parse(Path(__file__).with_name("main.py").read_text())
names = {"_no_uid_word", "_uid_label", "queue_uid_notices", "on_ssc_uid_notice_trigger",
         "on_ssc_uid_notice_names", "on_ssc_uid_notice_release"}
funcs = [n for n in tree.body
         if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name in names]
assert len(funcs) == len(names)
for n in funcs:
    n.decorator_list = []
config = NS(
    EXCLUDED_CHAT_IDS=frozenset(), UID_NOTICE_TRIGGER_KEYWORD="通知uid", UID_NOTICE_ENABLED=True,
    UID_NOTICE_APPROVAL_CODE="19", UID_NOTICE_WAIT_SECONDS=600, APPROVAL_CODES=frozenset({"1", "7", "13"}),
)
ns = dict(
    config=config, re=re, random=random, datetime=datetime, timezone=timezone,
    UID_NOTICE_MESSAGE=UID_NOTICE_MESSAGE, UID_NOTICE_WAITING_KEY="_waiting",
    parse_name_list=parse_name_list, plan_uid_notices=plan_uid_notices,
    find_uid_columns=find_columns, describe_uid_columns=describe_columns,
)
exec(compile(ast.Module(body=funcs, type_ignores=[]), "<uid>", "exec"), ns)


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
            msg = NS(id=100 + len(self.drafts), raw_text=text, to=target)
            self.drafts[msg.id] = msg
            return msg

        async def get_messages(chat, ids):
            return self.drafts.get(ids)

        ns["uid_notice_events"], ns["state"], ns["outbox"] = Store(), Store(), Store()
        ns["uid_notice_lock"], ns["ssc_send_lock"] = asyncio.Lock(), asyncio.Lock()
        ns["log"] = NS(info=lambda *a: None, warning=lambda *a: None, exception=lambda *a: None)
        ns["get_ssc_reviewer"] = AsyncMock(return_value=NS(id=99))
        self.client = NS(
            send_message=AsyncMock(side_effect=send_message),
            get_messages=AsyncMock(side_effect=get_messages),
            get_entity=AsyncMock(side_effect=lambda u: NS(entity=u)),
            delete_messages=AsyncMock(),
        )
        ns["client"] = self.client
        ns["pull_group_roster_repo"] = NS(load_rows=Mock(return_value=ROSTER))
        self.sleeps = []
        ns["asyncio"] = NS(to_thread=asyncio.to_thread,
                           sleep=AsyncMock(side_effect=lambda s: self.sleeps.append(s)))
        config.UID_NOTICE_ENABLED = True
        config.UID_NOTICE_WAIT_SECONDS = 600
        self.next_id = 1

    def _event(self, text, chat_id=99, sender_id=99, is_private=True):
        self.next_id += 1
        return NS(chat_id=chat_id, sender_id=sender_id, is_private=is_private,
                  raw_text=text, message=NS(id=self.next_id))

    def _texts(self):
        return [c.args[1] for c in self.client.send_message.call_args_list]

    def _pending(self):
        return [i for i in ns["outbox"].all().values() if i.get("status") == "pending"]

    async def _trigger_then_names(self, names):
        await ns["on_ssc_uid_notice_trigger"](self._event("通知uid"))
        await ns["on_ssc_uid_notice_names"](self._event(names))

    async def test_trigger_waits_then_names_make_drafts(self):
        await ns["on_ssc_uid_notice_trigger"](self._event("通知uid"))
        self.assertEqual(self._pending(), [])
        self.assertIn("人员名单", self._texts()[-1])
        self.assertIsNotNone(ns["uid_notice_events"].get("_waiting"))
        await ns["on_ssc_uid_notice_names"](self._event("甲\n乙\n丙\n无此人\n李四"))
        self.assertEqual(sorted(i["destination"] for i in self._pending()), ["@jia_user1", "@yi_user12"])
        self.assertTrue(all(i["kind"] == "uid_notice" and i["approval_code"] == "19"
                            and i["delete_draft_after_send"] for i in self._pending()))
        self.assertEqual(self._texts().count(UID_NOTICE_MESSAGE), 2)
        summary = self._texts()[-1]
        self.assertIn("发送 19 放行", summary)
        self.assertIn("甲 → @jia_user1", summary)
        self.assertIn("无此人", summary)
        self.assertIn("丙", summary)
        self.assertIn("李四", summary)
        self.assertIsNone(ns["uid_notice_events"].get("_waiting"))   # 名单只用一次

    async def test_trigger_case_insensitive_and_inline_names(self):
        await ns["on_ssc_uid_notice_trigger"](self._event("通知UID\n甲 乙"))
        self.assertEqual(len(self._pending()), 2)
        self.assertIsNone(ns["uid_notice_events"].get("_waiting"))

    async def test_bot_own_notices_are_not_taken_as_the_list(self):
        await ns["on_ssc_uid_notice_trigger"](self._event("通知uid"))
        # 机器人自己刚发到收藏夹的提示会作为新消息再进来
        await ns["on_ssc_uid_notice_names"](self._event(self._texts()[-1]))
        self.assertIsNotNone(ns["uid_notice_events"].get("_waiting"))
        self.assertEqual(self._pending(), [])
        # 审批码、数字、触发消息本身也不当名单
        for text in ("19", "7", "13", "通知uid", "12"):
            await ns["on_ssc_uid_notice_names"](self._event(text))
        self.assertIsNotNone(ns["uid_notice_events"].get("_waiting"))

    async def test_nothing_the_bot_sends_contains_the_trigger_word(self):
        scenarios = ["wait", "done", "fail", "disabled"]
        for scenario in scenarios:
            self.client.send_message.reset_mock()
            ns["uid_notice_events"].data.clear()
            config.UID_NOTICE_ENABLED = scenario != "disabled"
            ns["pull_group_roster_repo"].load_rows.side_effect = (
                RuntimeError("通知uid 403") if scenario == "fail" else None)
            ns["pull_group_roster_repo"].load_rows.return_value = ROSTER
            await ns["on_ssc_uid_notice_trigger"](self._event("通知uid" if scenario != "done" else "通知uid 甲"))
            if scenario == "fail":
                await ns["on_ssc_uid_notice_names"](self._event("甲"))
            for text in self._texts():
                self.assertNotIn("通知uid", text.casefold(), scenario)
        config.UID_NOTICE_ENABLED = True
        ns["pull_group_roster_repo"].load_rows.side_effect = None

    async def test_waiting_expires(self):
        await ns["on_ssc_uid_notice_trigger"](self._event("通知uid"))
        ns["uid_notice_events"].data["_waiting"]["since"] -= 601
        await ns["on_ssc_uid_notice_names"](self._event("甲"))
        self.assertEqual(self._pending(), [])
        self.assertIsNone(ns["uid_notice_events"].get("_waiting"))

    async def test_cancel(self):
        await ns["on_ssc_uid_notice_trigger"](self._event("通知uid"))
        await ns["on_ssc_uid_notice_names"](self._event("取消"))
        self.assertIsNone(ns["uid_notice_events"].get("_waiting"))
        await ns["on_ssc_uid_notice_names"](self._event("甲"))
        self.assertEqual(self._pending(), [])

    async def test_names_without_waiting_state_are_ignored(self):
        await ns["on_ssc_uid_notice_names"](self._event("甲 乙"))
        self.client.send_message.assert_not_awaited()

    async def test_other_chats_senders_and_disabled(self):
        await ns["on_ssc_uid_notice_trigger"](self._event("通知uid", chat_id=5, is_private=False))
        await ns["on_ssc_uid_notice_trigger"](self._event("通知uid", chat_id=77))
        self.client.send_message.assert_not_awaited()
        await ns["on_ssc_uid_notice_trigger"](self._event("通知uid"))
        await ns["on_ssc_uid_notice_names"](self._event("甲", sender_id=555))
        self.assertEqual(self._pending(), [])
        config.UID_NOTICE_ENABLED = False
        self.client.send_message.reset_mock()
        await ns["on_ssc_uid_notice_trigger"](self._event("通知uid"))
        self.assertIn("未启用", self._texts()[-1])

    async def test_bad_header_reports_and_makes_no_drafts(self):
        ns["pull_group_roster_repo"].load_rows.return_value = [["a", "b"], ["甲", "x"]]
        await self._trigger_then_names("甲")
        self.assertEqual(self._pending(), [])
        self.assertIn("失败", self._texts()[-1])
        ns["pull_group_roster_repo"].load_rows.return_value = ROSTER

    async def test_duplicate_event_and_pending_draft_not_duplicated(self):
        await ns["on_ssc_uid_notice_trigger"](self._event("通知uid 甲"))
        self.assertEqual(len(self._pending()), 1)
        event = self._event("通知uid 乙")
        await ns["on_ssc_uid_notice_trigger"](event)
        await ns["on_ssc_uid_notice_trigger"](event)
        self.assertEqual(len(self._pending()), 2)

    async def test_release_sends_privately_in_order_with_pauses_and_deletes_drafts(self):
        await self._trigger_then_names("甲 乙 张三")
        self.assertEqual(len(self._pending()), 3)
        self.client.send_message.reset_mock()
        await ns["on_ssc_uid_notice_release"](self._event("19"))
        sent = [(c.args[0].entity, c.args[1]) for c in self.client.send_message.call_args_list]
        self.assertEqual(sent, [("@jia_user1", UID_NOTICE_MESSAGE), ("@yi_user12", UID_NOTICE_MESSAGE),
                                ("@zhang3_now", UID_NOTICE_MESSAGE)])
        self.assertEqual(self.client.delete_messages.await_count, 3)
        self.assertEqual(self._pending(), [])
        self.assertEqual(len(self.sleeps), 2)
        self.assertTrue(all(5 <= s <= 10 for s in self.sleeps))
        # 再发19不会重复私发
        self.client.send_message.reset_mock()
        await ns["on_ssc_uid_notice_release"](self._event("19"))
        self.client.send_message.assert_not_awaited()

    async def test_release_failure_reported_and_not_retried(self):
        await self._trigger_then_names("甲 乙")
        self.client.get_entity.side_effect = [RuntimeError("PEER_FLOOD"), NS(entity="@yi_user12")]
        self.client.send_message.reset_mock()
        await ns["on_ssc_uid_notice_release"](self._event("19"))
        texts = self._texts()
        self.assertTrue(any("@jia_user1失败" in t for t in texts))
        self.assertEqual(self.client.delete_messages.await_count, 1)
        statuses = sorted(i["status"] for i in ns["outbox"].all().values())
        self.assertEqual(statuses, ["failed", "sent"])

    async def test_release_ignores_wrong_code_chat_or_sender(self):
        await self._trigger_then_names("甲")
        self.client.send_message.reset_mock()
        for ev in (self._event("18"), self._event("19", chat_id=5, is_private=False),
                   self._event("19", sender_id=555)):
            await ns["on_ssc_uid_notice_release"](ev)
        self.client.send_message.assert_not_awaited()
        self.assertEqual(len(self._pending()), 1)


if __name__ == "__main__":
    unittest.main()
