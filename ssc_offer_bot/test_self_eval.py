import ast
import asyncio
import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from self_eval import (
    FIELD_MAX_LENGTHS,
    build_self_eval_prompt,
    collect_month_reports,
    format_self_eval_preview,
    is_daily_report,
    parse_self_eval_response,
    report_date,
)

REPORT_SEP_24 = """# 日报

[REPORT-ORG:综合行政] [LEVEL:L3] [TYPE:日报] [DATE:2026-09-24]

> 提交人: 扶摇
> 岗位: SSC主管
> 层级: L3

## 【今日结果】
- SOP 模块执行汇总：
[日常考勤] [试用转正] [离职办理] [员工反馈] [AI工具建设]
1 1人转正闭环，5人offer，1人离职
2. 准备国庆期间转正人员材料
- 关键数据打卡：
关键数据打卡：入职0人，离职1人，转正0人，异动0人。

## 【死锁阻碍】
- 卡点描述：无

## 【专项复盘】
- 异常事项：无

## 【明日动作】
- 明日 TOP 3 任务：
1节后发布转正海报 变更记录
"""

REPORT_SEP_23 = REPORT_SEP_24.replace("2026-09-24", "2026-09-23")
REPORT_AUG_20 = REPORT_SEP_24.replace("2026-09-24", "2026-08-20")

NOT_A_REPORT = "@ffuuyao 麻烦跟进一下这个候选人的offer审批"


class ClassificationTests(TestCase):
    def test_is_daily_report_requires_type_tag(self):
        self.assertTrue(is_daily_report(REPORT_SEP_24))
        self.assertFalse(is_daily_report(NOT_A_REPORT))
        self.assertFalse(is_daily_report("今天写了一份日报总结"))  # 提到"日报"两字但没有[TYPE:日报]标签

    def test_report_date_reads_date_tag(self):
        self.assertEqual(report_date(REPORT_SEP_24), date(2026, 9, 24))
        self.assertIsNone(report_date(NOT_A_REPORT))

    def test_report_date_ignores_invalid_date(self):
        broken = REPORT_SEP_24.replace("2026-09-24", "2026-13-99")
        self.assertIsNone(report_date(broken))


def fake_message(text, when):
    return NS(raw_text=text, date=when)


class CollectMonthReportsTests(TestCase):
    def test_collects_only_current_month_by_date_tag(self):
        messages = [
            fake_message(REPORT_SEP_24, datetime(2026, 9, 24, 10, tzinfo=timezone.utc)),
            fake_message(REPORT_SEP_23, datetime(2026, 9, 23, 10, tzinfo=timezone.utc)),
            fake_message(REPORT_AUG_20, datetime(2026, 8, 20, 10, tzinfo=timezone.utc)),
            fake_message(NOT_A_REPORT, datetime(2026, 9, 24, 11, tzinfo=timezone.utc)),
        ]
        reports = collect_month_reports(messages, 2026, 9)
        self.assertEqual([day.isoformat() for day, _ in reports], ["2026-09-23", "2026-09-24"])

    def test_falls_back_to_message_timestamp_when_date_tag_missing(self):
        text_without_date_tag = REPORT_SEP_24.replace("[DATE:2026-09-24] ", "").replace(
            "[DATE:2026-09-24]", ""
        )
        messages = [fake_message(text_without_date_tag, datetime(2026, 9, 24, 9, tzinfo=timezone.utc))]
        reports = collect_month_reports(messages, 2026, 9)
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0][0], date(2026, 9, 24))

    def test_empty_when_no_reports_this_month(self):
        messages = [fake_message(REPORT_AUG_20, datetime(2026, 8, 20, 10, tzinfo=timezone.utc))]
        self.assertEqual(collect_month_reports(messages, 2026, 9), [])


class PromptBuildingTests(TestCase):
    def test_prompt_includes_report_bodies_and_period_label(self):
        reports = [(date(2026, 9, 24), REPORT_SEP_24)]
        prompt = build_self_eval_prompt(reports, "2026年9月")
        self.assertIn("2026年9月", prompt)
        self.assertIn("入职0人，离职1人，转正0人，异动0人", prompt)
        self.assertIn("work_summary", prompt)
        self.assertIn("agent_usage", prompt)

    def test_prompt_states_no_reports_when_empty(self):
        prompt = build_self_eval_prompt([], "2026年9月")
        self.assertIn("本月未找到任何日报", prompt)


class ParseResponseTests(TestCase):
    def _valid_payload(self, **overrides):
        payload = {
            "work_summary": "本月完成5人offer、2人转正、1人离职，达成率100%" * 2,
            "highlight": "转正流程效率提升明显，无逾期" * 2,
            "challenge": "国庆期间人手紧张，需提前安排" * 2,
            "next_focus": "跟进国庆期间转正审批和考勤抽查" * 2,
            "agent_usage": "本月使用AI工具辅助日报整理" * 2,
        }
        payload.update(overrides)
        return payload

    def test_parses_plain_json(self):
        result = parse_self_eval_response(json.dumps(self._valid_payload()))
        self.assertEqual(set(result), set(FIELD_MAX_LENGTHS))

    def test_strips_markdown_code_fence(self):
        wrapped = "```json\n" + json.dumps(self._valid_payload()) + "\n```"
        result = parse_self_eval_response(wrapped)
        self.assertIn("work_summary", result)

    def test_truncates_to_field_max_length(self):
        overlong = self._valid_payload(highlight="很长的内容" * 100)
        result = parse_self_eval_response(json.dumps(overlong))
        self.assertLessEqual(len(result["highlight"]), FIELD_MAX_LENGTHS["highlight"])

    def test_missing_field_raises(self):
        payload = self._valid_payload()
        del payload["challenge"]
        with self.assertRaises(ValueError):
            parse_self_eval_response(json.dumps(payload))

    def test_blank_field_raises(self):
        payload = self._valid_payload(next_focus="   ")
        with self.assertRaises(ValueError):
            parse_self_eval_response(json.dumps(payload))


class PreviewFormattingTests(TestCase):
    def test_preview_includes_all_sections_and_fixed_score_note(self):
        content = {
            "work_summary": "工作说明内容",
            "highlight": "亮点内容",
            "challenge": "挑战内容",
            "next_focus": "重点内容",
            "agent_usage": "AI说明内容",
        }
        preview = format_self_eval_preview(content, "2026年9月")
        self.assertIn("2026年9月", preview)
        self.assertIn("工作说明内容", preview)
        self.assertIn("80分", preview)


# ---------------------------------------------------------------------------
# main.py 集成测试：收藏夹发"员工自评" -> 收集本月日报 -> 生成内容 -> 填表 -> 通知。
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
    source = ast.parse(Path(__file__).with_name("main.py").read_text())
    functions = [
        n for n in source.body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "on_ssc_self_eval_trigger"
    ]
    for node in functions:
        node.decorator_list = []
    from zoneinfo import ZoneInfo
    env = dict(
        collect_month_reports=collect_month_reports,
        build_self_eval_prompt=build_self_eval_prompt,
        parse_self_eval_response=parse_self_eval_response,
        format_self_eval_preview=format_self_eval_preview,
        datetime=datetime, ZoneInfo=ZoneInfo,
        asyncio=asyncio, log=__import__("logging").getLogger("test"),
    )
    env.update(overrides)
    exec(compile(ast.Module(body=functions, type_ignores=[]), "main.py", "exec"), env)
    return env


VALID_GPT_JSON = json.dumps({
    "work_summary": "本月完成5人offer、2人转正、1人离职，达成率100%" * 2,
    "highlight": "转正流程效率提升明显，无逾期" * 2,
    "challenge": "国庆期间人手紧张，需提前安排" * 2,
    "next_focus": "跟进国庆期间转正审批和考勤抽查" * 2,
    "agent_usage": "本月使用AI工具辅助日报整理" * 2,
})


class SelfEvalTriggerTests(IsolatedAsyncioTestCase):
    def setUp(self):
        self.me = NS(id=9, username="ffuuyao")
        self.sent = []
        self.fill_calls = []
        self.openai_calls = []

        async def send_message(destination, text, **kwargs):
            self.sent.append((destination, text))
            return NS(id=900 + len(self.sent))

        async def iter_messages(chat, from_user=None):
            for text, when in [
                (REPORT_SEP_24, datetime(2026, 9, 24, 10, tzinfo=timezone.utc)),
                (REPORT_SEP_23, datetime(2026, 9, 23, 10, tzinfo=timezone.utc)),
                (REPORT_AUG_20, datetime(2026, 8, 20, 10, tzinfo=timezone.utc)),
            ]:
                yield fake_message(text, when)

        def call_openai_chat(api_key, model, prompt):
            self.openai_calls.append((api_key, model, prompt))
            return VALID_GPT_JSON

        async def fill_self_eval_form(base_url, login_code, login_password, content):
            self.fill_calls.append((base_url, login_code, login_password, content))

        self.config = NS(
            EXCLUDED_CHAT_IDS=frozenset(),
            SELF_EVAL_TRIGGER_KEYWORD="员工自评",
            SELF_EVAL_ENABLED=True,
            GROUP_SSC_WORK=-2,
            OPENAI_API_KEY="sk-test",
            OPENAI_MODEL="gpt-4o-mini",
            ONEHR_BASE_URL="https://m-reportsys.cc",
            ONEHR_LOGIN_CODE="SS1132",
            ONEHR_LOGIN_PASSWORD="secret",
            DAILY_REPORT_TIMEZONE="Asia/Shanghai",
        )
        self.client = NS(iter_messages=iter_messages, send_message=send_message)
        self.env = build_env(
            client=self.client, config=self.config,
            get_ssc_reviewer=AsyncMock(return_value=self.me),
            self_eval_lock=asyncio.Lock(),
            call_openai_chat=call_openai_chat,
            fill_self_eval_form=fill_self_eval_form,
        )

    async def _fire_trigger(self, text, msg_id=200):
        event = NS(chat_id=9, raw_text=text, is_private=True, sender_id=9,
                   message=NS(id=msg_id))
        await self.env["on_ssc_self_eval_trigger"](event)

    async def test_ignores_unrelated_messages(self):
        await self._fire_trigger("随便聊两句")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.fill_calls, [])

    async def test_ignores_keyword_from_other_chat_or_sender(self):
        event = NS(chat_id=123, raw_text="员工自评", is_private=True, sender_id=9,
                   message=NS(id=1))
        await self.env["on_ssc_self_eval_trigger"](event)
        self.assertEqual(self.sent, [])

    async def test_disabled_sends_notice_and_does_nothing_else(self):
        self.config.SELF_EVAL_ENABLED = False
        await self._fire_trigger("员工自评")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("未启用", self.sent[0][1])
        self.assertEqual(self.fill_calls, [])

    async def test_happy_path_collects_reports_calls_gpt_and_fills_form(self):
        await self._fire_trigger("员工自评")

        # 只收本月(9月)的2条，8月那条不该被送进GPT的提示词。
        self.assertEqual(len(self.openai_calls), 1)
        _, model, prompt = self.openai_calls[0]
        self.assertEqual(model, "gpt-4o-mini")
        self.assertIn("2026-09-23", prompt)
        self.assertIn("2026-09-24", prompt)
        self.assertNotIn("2026-08-20", prompt)

        self.assertEqual(len(self.fill_calls), 1)
        base_url, login_code, login_password, content = self.fill_calls[0]
        self.assertEqual(base_url, "https://m-reportsys.cc")
        self.assertEqual(login_code, "SS1132")
        self.assertIn("work_summary", content)

        # 最后发一条通知回收藏夹（reviewer.id=9），带草稿预览。
        self.assertEqual(len(self.sent), 1)
        destination, text = self.sent[0]
        self.assertEqual(destination, 9)
        self.assertIn("未提交", text)
        self.assertIn("正式提交", text)

    async def test_gpt_failure_notifies_without_calling_fill_form(self):
        def broken_call(api_key, model, prompt):
            raise RuntimeError("network error")
        self.env["call_openai_chat"] = broken_call
        await self._fire_trigger("员工自评")
        self.assertEqual(self.fill_calls, [])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("生成失败", self.sent[0][1])

    async def test_fill_form_failure_notifies_with_manual_fallback_content(self):
        async def broken_fill(base_url, login_code, login_password, content):
            raise RuntimeError("login selector not found")
        self.env["fill_self_eval_form"] = broken_fill
        await self._fire_trigger("员工自评")
        self.assertEqual(len(self.sent), 1)
        self.assertIn("填表失败", self.sent[0][1])
        self.assertIn("工作说明", self.sent[0][1])  # 生成的内容仍然带在通知里，方便SSC手动填

    async def test_keyword_matches_as_substring(self):
        await self._fire_trigger("帮我填一下员工自评，谢谢")
        self.assertEqual(len(self.fill_calls), 1)


if __name__ == "__main__":
    import unittest
    unittest.main()
