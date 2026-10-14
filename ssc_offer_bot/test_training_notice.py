# -*- coding: utf-8 -*-
"""场景十六：收藏夹"培训通知" -> 花名册（机器人）G列入职日期是今天的人 -> 学习群链接草稿
-> 审批码18放行后逐个私发私人TG(AF列)。"""

import ast
import asyncio
import random
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from zoneinfo import ZoneInfo

from training_notice import (
    TRAINING_NOTICE_MESSAGE, parse_people, plan_training_notices,
)
from training_notice import person_label as training_notice_person_label

TODAY = datetime.now(ZoneInfo("Asia/Shanghai")).date()
TODAY_STR = TODAY.isoformat()


def roster_row(c="", g="", af=""):
    row = [""] * 50
    row[2], row[6], row[31] = c, g, af      # C, G, AF
    return row


HEADER = ["h"] * 50


class LogicTests(unittest.TestCase):
    def test_message_text_exact_and_has_no_training_word(self):
        self.assertEqual(TRAINING_NOTICE_MESSAGE,
                         "https://t.me/+gL8gzMBNRNZlYWVl\n\n进群自学pdf 和 视频 并参加考试哦")
        self.assertNotIn("培训", TRAINING_NOTICE_MESSAGE)

    def test_selects_by_column_g_and_reads_column_af(self):
        rows = [HEADER,
                roster_row("甲", TODAY_STR, "@jia_user1"),
                roster_row("乙", "2020-01-01", "@yi_user12"),
                roster_row("丙", TODAY_STR, "https://t.me/bing_user"),
                roster_row("丁", TODAY_STR, ""),
                roster_row("戊", TODAY_STR, "13800000000"),
                roster_row("己", TODAY_STR, "@jia_user1"),    # 重复TG
                roster_row("庚", "不是日期", "@geng_user")]
        plan = plan_training_notices(rows, TODAY)
        self.assertEqual(len(plan["hired"]), 5)
        self.assertEqual([(p["name_c"], p["tg"]) for p in plan["to_send"]],
                         [("甲", "@jia_user1"), ("丙", "@bing_user")])
        self.assertEqual([p["name_c"] for p in plan["no_tg"]], ["丁", "戊"])

    def test_header_skipped_and_empty_rows_ignored(self):
        rows = [roster_row("表头", TODAY_STR, "@header_u1"), roster_row("", TODAY_STR, "")]
        self.assertEqual(parse_people(rows), [])


# ---------- 监听器（AST提取main.py里的函数） ----------
tree = ast.parse(Path(__file__).with_name("main.py").read_text())
names = {"on_ssc_training_notice_trigger", "on_ssc_training_notice_release",
         "_no_training_word", "on_ssc_training_sync_trigger"}
funcs = [n for n in tree.body
         if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name in names]
for n in funcs:
    n.decorator_list = []
config = NS(
    EXCLUDED_CHAT_IDS=frozenset(), TRAINING_NOTICE_TRIGGER_KEYWORD="培训通知",
    TRAINING_NOTICE_ENABLED=True, TRAINING_NOTICE_APPROVAL_CODE="18",
    TRAINING_SYNC_TRIGGER_KEYWORD="培训", TRAINING_SYNC_ENABLED=True,
    DAILY_REPORT_TIMEZONE="Asia/Shanghai",
)
ns = dict(
    config=config, asyncio=asyncio, random=random, datetime=datetime, timedelta=timedelta, ZoneInfo=ZoneInfo,
    TRAINING_NOTICE_MESSAGE=TRAINING_NOTICE_MESSAGE, plan_training_notices=plan_training_notices,
    training_notice_person_label=training_notice_person_label, TRAINING_SYNC_HEADER="【次日培训信息同步】",
)
exec(compile(ast.Module(body=funcs, type_ignores=[]), "<notice>", "exec"), ns)


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
          roster_row("甲", TODAY_STR, "@jia_user1"),
          roster_row("乙", TODAY_STR, "@yi_user12"),
          roster_row("丙", TODAY_STR, ""),
          roster_row("丁", "2020-01-01", "@ding_user")]


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.drafts = {}

        async def send_message(target, text, **kw):
            msg = NS(id=100 + len(self.drafts), raw_text=text)
            self.drafts[msg.id] = msg
            return msg

        async def get_messages(chat, ids):
            return self.drafts.get(ids)

        ns["training_notice_events"], ns["state"], ns["outbox"] = Store(), Store(), Store()
        ns["training_notice_lock"], ns["ssc_send_lock"] = asyncio.Lock(), asyncio.Lock()
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
        sleeps = []
        ns["asyncio"] = NS(to_thread=asyncio.to_thread, sleep=AsyncMock(side_effect=lambda s: sleeps.append(s)))
        self.sleeps = sleeps
        config.TRAINING_NOTICE_ENABLED = True

    def _event(self, text="培训通知", msg_id=1, chat_id=99, sender_id=99, is_private=True):
        return NS(chat_id=chat_id, sender_id=sender_id, is_private=is_private,
                  raw_text=text, message=NS(id=msg_id))

    def _sent_texts(self):
        return [c.args[1] for c in self.client.send_message.call_args_list]

    def _pending(self):
        return [i for i in ns["outbox"].all().values() if i["status"] == "pending"]

    async def test_trigger_drafts_for_people_hired_today_with_private_tg(self):
        await ns["on_ssc_training_notice_trigger"](self._event())
        self.assertEqual(sorted(i["destination"] for i in self._pending()), ["@jia_user1", "@yi_user12"])
        self.assertTrue(all(i["kind"] == "training_notice" and i["approval_code"] == "18"
                            and i["delete_draft_after_send"] for i in self._pending()))
        self.assertEqual(len([t for t in self._sent_texts() if t == TRAINING_NOTICE_MESSAGE]), 2)
        summary = self._sent_texts()[-1]
        self.assertIn("入职3人", summary)
        self.assertIn("甲 → @jia_user1", summary)
        self.assertIn("发送 18 放行", summary)
        self.assertIn("丙", summary)             # 没有私人TG的人单独列出

    async def test_nothing_the_bot_sends_contains_the_old_trigger_word(self):
        # 回归：收藏夹里机器人自己发的提示会被监听器收到，含"培训"会触发场景十三，
        # 含"培训通知"会触发自己。
        for scenario in ("normal", "fail", "disabled", "nobody"):
            self.client.send_message.reset_mock()
            ns["training_notice_events"].data.clear()
            config.TRAINING_NOTICE_ENABLED = scenario != "disabled"
            ns["training_sync_roster_repo"].load_rows.side_effect = (
                RuntimeError("培训通知 培训 403") if scenario == "fail" else None)
            ns["training_sync_roster_repo"].load_rows.return_value = [HEADER] if scenario == "nobody" else ROSTER
            await ns["on_ssc_training_notice_trigger"](self._event())
            self.assertTrue(self._sent_texts(), scenario)
            for text in self._sent_texts():
                self.assertNotIn("培训", text, scenario)
        config.TRAINING_NOTICE_ENABLED = True
        ns["training_sync_roster_repo"].load_rows.side_effect = None
        ns["training_sync_roster_repo"].load_rows.return_value = ROSTER

    async def test_old_training_sync_handler_yields_to_notice_keyword(self):
        # "培训通知"含"培训"，场景十三必须让开；单独的"培训"仍然走场景十三。
        ns["training_sync_events"] = Store()
        ns["training_sync_lock"] = asyncio.Lock()
        await ns["on_ssc_training_sync_trigger"](self._event(text="培训通知"))
        self.client.send_message.assert_not_awaited()
        ns["training_sync_roster_repo"].load_rows.assert_not_called()
        ns["parse_training_roster_rows"] = lambda rows: []; ns["TRAINING_SYNC_HEADER"] = "【次日培训信息同步】"
        ns["select_people_for_date"] = lambda people, d: []
        await ns["on_ssc_training_sync_trigger"](self._event(text="明天的培训", msg_id=2))
        ns["training_sync_roster_repo"].load_rows.assert_called_once()

    async def test_disabled_and_other_chats_and_no_keyword(self):
        config.TRAINING_NOTICE_ENABLED = False
        await ns["on_ssc_training_notice_trigger"](self._event())
        self.assertIn("未启用", self._sent_texts()[-1])
        self.assertEqual(self._pending(), [])
        config.TRAINING_NOTICE_ENABLED = True
        self.client.send_message.reset_mock()
        await ns["on_ssc_training_notice_trigger"](self._event(text="随便聊聊", msg_id=5))
        await ns["on_ssc_training_notice_trigger"](self._event(chat_id=5, is_private=False, msg_id=6))
        self.client.send_message.assert_not_awaited()

    async def test_retrigger_does_not_duplicate_and_duplicate_event_ignored(self):
        e = self._event(msg_id=1)
        await ns["on_ssc_training_notice_trigger"](e)
        count = self.client.send_message.await_count
        await ns["on_ssc_training_notice_trigger"](e)
        self.assertEqual(self.client.send_message.await_count, count)
        await ns["on_ssc_training_notice_trigger"](self._event(msg_id=2))
        self.assertEqual(len(self._pending()), 2)
        self.assertIn("已有待发送草稿", self._sent_texts()[-1])

    async def test_release_sends_exact_message_privately_with_delay_and_deletes_drafts(self):
        await ns["on_ssc_training_notice_trigger"](self._event())
        self.client.send_message.reset_mock()
        await ns["on_ssc_training_notice_release"](self._event(text="18", msg_id=50))
        sent = [(c.args[0].entity, c.args[1]) for c in self.client.send_message.call_args_list
                if hasattr(c.args[0], "entity")]
        self.assertEqual(sorted(t for t, _ in sent), ["@jia_user1", "@yi_user12"])
        self.assertTrue(all(m == TRAINING_NOTICE_MESSAGE for _, m in sent))
        self.assertEqual(self.client.delete_messages.await_count, 2)
        self.assertEqual(len(self.sleeps), 1)
        self.assertTrue(5 <= self.sleeps[0] <= 10)
        await ns["on_ssc_training_notice_trigger"](self._event(msg_id=3))
        self.assertEqual(self._pending(), [])
        self.assertIn("今天已发送过", self._sent_texts()[-1])

    async def test_release_failure_marks_failed_and_notifies_without_training_word(self):
        await ns["on_ssc_training_notice_trigger"](self._event())
        self.client.get_entity.side_effect = ValueError("培训 no such user")
        self.client.send_message.reset_mock()
        await ns["on_ssc_training_notice_release"](self._event(text="18", msg_id=50))
        self.assertEqual({i["status"] for i in ns["outbox"].all().values()}, {"failed"})
        self.assertTrue(any("失败" in t for t in self._sent_texts()))
        self.assertTrue(all("培训" not in t for t in self._sent_texts()))

    async def test_release_ignored_for_other_codes_or_disabled_or_foreign_sender(self):
        await ns["on_ssc_training_notice_trigger"](self._event())
        self.client.send_message.reset_mock()
        for kwargs in ({"text": "17"}, {"text": "181"}, {"text": "18", "sender_id": 7}):
            await ns["on_ssc_training_notice_release"](self._event(**kwargs))
        config.TRAINING_NOTICE_ENABLED = False
        await ns["on_ssc_training_notice_release"](self._event(text="18"))
        config.TRAINING_NOTICE_ENABLED = True
        self.client.send_message.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
