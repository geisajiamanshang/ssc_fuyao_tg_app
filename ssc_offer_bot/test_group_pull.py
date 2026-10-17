# -*- coding: utf-8 -*-
"""场景十七：收藏夹"拉人" -> 花名册M列技术中心的人 -> AE列工作TG拉进群，并列出名单。"""

import ast
import asyncio
import random
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock

from telethon import errors

from group_pull import (
    check_headers, chunk_lines, find_header_row, format_people, plan_group_pull,
)


def row(c="", m="", ae="", ad=""):
    r = [""] * 31
    r[2], r[12], r[29], r[30] = c, m, ad, ae      # C, M, AD, AE
    return r


def header(c="花名*", m="编制组织*", ae="工作TG"):
    return row(c, m, ae)


ROWS = [["在职花名册"] + [""] * 30, ["分组"] + [""] * 30, header(),
        row("甲", "技术中心", "@jia_user1"),
        row("乙", "运营中心", "@yi_user12"),
        row("丙", "技术中心", "https://t.me/bing_user"),
        row("丁", "技术中心", ""),
        row("戊", "技术中心", "13800000000"),
        row("己", "技术中心", "@jia_user1"),      # 重复TG
        row("", "技术中心", "@noname_u1")]        # 没花名


class LogicTests(unittest.TestCase):
    def test_header_row_found_and_valid(self):
        self.assertEqual(find_header_row(ROWS), 2)
        self.assertEqual(check_headers(ROWS), (True, ""))

    def test_header_mismatch_reports_actual_headers_and_suggests_columns(self):
        # 花名册别处记录的布局：编制组织在L列、工作TG在AD列、AE是私人联系方式
        r = [""] * 31
        r[2], r[11], r[29], r[30] = "花名*", "编制组织*", "工作TG", "私人联系方式"
        r[12] = "服务单位"
        ok, why = check_headers([r])
        self.assertFalse(ok)
        self.assertIn("M列表头是“服务单位”", why)
        self.assertIn("AE列表头是“私人联系方式”", why)
        self.assertIn("含“编制组织”的列是L", why)
        self.assertIn("含“工作TG”的列是AD", why)

    def test_no_header_row(self):
        ok, why = check_headers([["x"], ["y"]])
        self.assertFalse(ok)
        self.assertIn("找不到", why)

    def test_plan_selects_center_and_parses_tg(self):
        plan = plan_group_pull(ROWS)
        self.assertEqual([(p["name"], p["tg"]) for p in plan["people"]],
                         [("甲", "@jia_user1"), ("丙", "@bing_user")])
        self.assertEqual([p["name"] for p in plan["no_tg"]], ["丁", "戊"])

    def test_header_row_itself_is_not_a_person(self):
        rows = [header("花名", "技术中心", "@x_header1")]
        self.assertEqual(plan_group_pull(rows)["people"], [])

    def test_format_and_chunk(self):
        people = [{"name": "甲", "tg": "@a_user1"}, {"name": "乙", "tg": "@b_user1"}]
        self.assertEqual(format_people(people), "甲 @a_user1\n乙 @b_user1")
        text = "\n".join(f"花名{i} @user_{i:04d}" for i in range(600))
        chunks = chunk_lines(text, limit=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(c) <= 500 for c in chunks))
        self.assertEqual("\n".join(chunks), text)


# ---------- 监听器（AST提取main.py里的函数） ----------
tree = ast.parse(Path(__file__).with_name("main.py").read_text())
names = {"on_ssc_pull_group_trigger", "add_member_to_group"}
funcs = [n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name in names]
for n in funcs:
    n.decorator_list = []
config = NS(
    EXCLUDED_CHAT_IDS=frozenset(), PULL_GROUP_TRIGGER="拉人", PULL_GROUP_ENABLED=True,
    PULL_GROUP_CHAT_ID=-5517058150, PULL_GROUP_CENTER="技术中心",
)


class FakeChannel:
    id = 1


class Store:
    def __init__(self):
        self.data = {}

    def get(self, k):
        return self.data.get(k)

    def set(self, k, v):
        self.data[k] = v

    def update(self, k, **v):
        self.data.setdefault(k, {}).update(v)


ns = dict(
    config=config, asyncio=asyncio, random=random, errors=errors, Channel=FakeChannel,
    check_headers=check_headers, chunk_lines=chunk_lines, format_people=format_people,
    plan_group_pull=plan_group_pull,
    AddChatUserRequest=lambda **kw: ("add_chat", kw),
    InviteToChannelRequest=lambda group, users: ("invite", group, users),
)
exec(compile(ast.Module(body=funcs, type_ignores=[]), "<pull>", "exec"), ns)


def err(cls, *a):
    e = cls.__new__(cls)
    e.args = a
    return e


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.group = NS(id=5517058150)
        self.calls = []
        self.outcomes = {}

        async def client_call(request):
            self.calls.append(request)
            tg = request[1]["user_id"].tg if request[0] == "add_chat" else request[2][0].tg
            outcome = self.outcomes.get(tg)
            if outcome:
                raise outcome

        async def get_entity(x):
            if x == config.PULL_GROUP_CHAT_ID:
                return self.group
            return NS(tg=x)

        self.sent = []
        self.client = Mock(side_effect=client_call)
        self.client = AsyncMock(side_effect=client_call)
        self.client.send_message = AsyncMock(side_effect=lambda t, m, **kw: self.sent.append(m))
        self.client.get_entity = AsyncMock(side_effect=get_entity)
        ns["client"] = self.client
        ns["pull_group_events"], ns["pull_group_lock"] = Store(), asyncio.Lock()
        ns["log"] = NS(info=lambda *a: None, warning=lambda *a: None, exception=lambda *a: None)
        ns["get_ssc_reviewer"] = AsyncMock(return_value=NS(id=99))
        ns["pull_group_roster_repo"] = NS(load_rows=Mock(return_value=ROWS))
        sleeps = []
        ns["asyncio"] = NS(to_thread=asyncio.to_thread, sleep=AsyncMock(side_effect=lambda s: sleeps.append(s)))
        self.sleeps = sleeps
        config.PULL_GROUP_ENABLED = True

    def _event(self, text="拉人", msg_id=1, chat_id=99, sender_id=99, is_private=True):
        return NS(chat_id=chat_id, sender_id=sender_id, is_private=is_private,
                  raw_text=text, message=NS(id=msg_id))

    async def test_lists_people_then_adds_each_to_basic_group_and_reports(self):
        await ns["on_ssc_pull_group_trigger"](self._event())
        self.assertEqual([c[1]["user_id"].tg for c in self.calls], ["@jia_user1", "@bing_user"])
        self.assertTrue(all(c[0] == "add_chat" and c[1]["chat_id"] == 5517058150 for c in self.calls))
        self.assertEqual(len(self.sleeps), 1)
        self.assertTrue(5 <= self.sleeps[0] <= 10)
        listing = self.sent[0]
        self.assertIn("技术中心共2人（花名 工作tg）", listing)
        self.assertIn("甲 @jia_user1\n丙 @bing_user", listing)
        self.assertIn("丁 （空）", listing)                  # 没TG的单独列出
        self.assertIn("戊 13800000000", listing)
        report = self.sent[-1]
        self.assertIn("成功2人", report)
        self.assertIn("失败0人", report)

    async def test_supergroup_uses_invite_to_channel(self):
        self.group = FakeChannel()
        await ns["on_ssc_pull_group_trigger"](self._event())
        self.assertTrue(all(c[0] == "invite" for c in self.calls))
        self.assertEqual(len(self.calls), 2)

    async def test_already_member_and_other_failures_do_not_stop_the_rest(self):
        self.outcomes["@jia_user1"] = err(errors.UserAlreadyParticipantError, "x")
        self.outcomes["@bing_user"] = err(errors.UserPrivacyRestrictedError, "x")
        await ns["on_ssc_pull_group_trigger"](self._event())
        report = self.sent[-1]
        self.assertIn("成功0人，本来就在群里1人，失败1人", report)
        self.assertIn("丙 @bing_user（UserPrivacyRestrictedError", report)

    async def test_flood_stops_immediately_and_lists_remaining(self):
        self.outcomes["@jia_user1"] = err(errors.PeerFloodError, "x")
        await ns["on_ssc_pull_group_trigger"](self._event())
        self.assertEqual(len(self.calls), 1)
        report = self.sent[-1]
        self.assertIn("因限流停止", report)
        self.assertIn("丙 @bing_user", report.split("因限流停止")[1])
        self.assertEqual(self.sleeps, [])

    async def test_header_mismatch_adds_nobody(self):
        bad = [r[:] for r in ROWS]
        bad[2] = header(m="服务单位", ae="私人联系方式")
        ns["pull_group_roster_repo"].load_rows.return_value = bad
        await ns["on_ssc_pull_group_trigger"](self._event())
        self.assertEqual(self.calls, [])
        self.assertIn("没有拉人", self.sent[-1])
        self.assertIn("表头对不上", self.sent[-1])

    async def test_only_exact_command_from_ssc_private_chat_triggers(self):
        for kwargs in ({"text": "拉人吗"}, {"text": "帮我拉人"}, {"text": "拉人 技术中心"},
                       {"sender_id": 7}, {"chat_id": 5, "is_private": False}):
            await ns["on_ssc_pull_group_trigger"](self._event(**kwargs))
        self.assertEqual(self.calls, [])
        self.assertEqual(self.sent, [])
        await ns["on_ssc_pull_group_trigger"](self._event(text=" 拉人 ", msg_id=2))
        self.assertEqual(len(self.calls), 2)

    async def test_disabled_and_duplicate_event(self):
        config.PULL_GROUP_ENABLED = False
        await ns["on_ssc_pull_group_trigger"](self._event())
        self.assertIn("未启用", self.sent[-1])
        self.assertEqual(self.calls, [])
        config.PULL_GROUP_ENABLED = True
        e = self._event(msg_id=3)
        await ns["on_ssc_pull_group_trigger"](e)
        n = len(self.calls)
        await ns["on_ssc_pull_group_trigger"](e)
        self.assertEqual(len(self.calls), n)

    async def test_sheet_error_reported_and_nobody_added(self):
        ns["pull_group_roster_repo"].load_rows.side_effect = RuntimeError("403 Forbidden")
        await ns["on_ssc_pull_group_trigger"](self._event())
        self.assertIn("403", self.sent[-1])
        self.assertEqual(self.calls, [])
        ns["pull_group_roster_repo"].load_rows.side_effect = None

    async def test_nobody_in_center(self):
        ns["pull_group_roster_repo"].load_rows.return_value = ROWS[:3] + [row("乙", "运营中心", "@yi_user12")]
        await ns["on_ssc_pull_group_trigger"](self._event())
        self.assertIn("没有M列是“技术中心”的人", self.sent[-1])
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
