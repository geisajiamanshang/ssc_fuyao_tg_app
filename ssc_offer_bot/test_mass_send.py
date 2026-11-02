import ast
import asyncio
import logging
import time
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

import mass_send
from telethon import errors

SSC_ID = 777


class MemoryStore:
    def __init__(self):
        self.data = {}

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value


class ParseTgListTest(TestCase):
    def test_space_separated(self):
        tgs, invalid = mass_send.parse_tg_list("@wssahfkj @lovact2026 @songyang518")
        self.assertEqual(tgs, ["@wssahfkj", "@lovact2026", "@songyang518"])
        self.assertEqual(invalid, [])

    def test_one_per_line_with_blank_lines(self):
        text = "\n\n@kai6842\n@dengshanshann\n@bruce1666\n@xiluo123321\n@songyang518\n@SCTK888\n\n\n"
        tgs, invalid = mass_send.parse_tg_list(text)
        self.assertEqual(tgs, ["@kai6842", "@dengshanshann", "@bruce1666",
                               "@xiluo123321", "@songyang518", "@SCTK888"])
        self.assertEqual(invalid, [])

    def test_mixed_separators_links_and_duplicates(self):
        tgs, invalid = mass_send.parse_tg_list("@Abcde1，@abcde1、https://t.me/zxcvb99;@qwert12\r\n@qwert12")
        self.assertEqual(tgs, ["@Abcde1", "@zxcvb99", "@qwert12"])
        self.assertEqual(invalid, [])

    def test_invalid_pieces_reported(self):
        tgs, invalid = mass_send.parse_tg_list("@good123 @ab 你好 hello")
        self.assertEqual(tgs, ["@good123"])
        self.assertEqual(invalid, ["@ab", "你好", "hello"])
        self.assertTrue(mass_send.looks_like_tg_list_attempt(tgs, invalid))

    def test_plain_chat_is_not_a_list_attempt(self):
        tgs, invalid = mass_send.parse_tg_list("员工绩效")
        self.assertFalse(mass_send.looks_like_tg_list_attempt(tgs, invalid))
        self.assertFalse(mass_send.looks_like_tg_list_attempt(*mass_send.parse_tg_list("")))

    def test_session_helpers(self):
        session = {"stage": mass_send.STAGE_WAITING_TGS_CONFIRM, "since": 1000}
        self.assertTrue(mass_send.waiting_for_confirm(session, 1100, 1800))
        self.assertFalse(mass_send.waiting_for_confirm(session, 3000, 1800))
        self.assertFalse(mass_send.waiting_for_confirm({"stage": mass_send.STAGE_WAITING_MESSAGE, "since": 1000}, 1100, 1800))
        self.assertFalse(mass_send.waiting_for_confirm(None, 1100, 1800))
        self.assertTrue(mass_send.session_expired({}, 1100, 1800))

    def test_report(self):
        text = mass_send.format_report(["@a1111"], [("@b2222", "用户名不存在")], ["@c3333"])
        self.assertTrue(text.startswith(mass_send.NOTICE_PREFIX))
        self.assertIn("共3个，成功1个，失败1个，未发送1个", text)
        self.assertIn("@b2222（用户名不存在）", text)
        self.assertIn("@c3333", text)
        self.assertNotIn("未发送", mass_send.format_report(["@a1111"], [], []))


def base_config(**overrides):
    fields = dict(
        EXCLUDED_CHAT_IDS=frozenset(), ENVIRONMENT="prod",
        MASS_SEND_TRIGGER="群发", MASS_SEND_DIFF_TRIGGER="不同群发", MASS_SEND_CONFIRM_CODE="1", MASS_SEND_ENABLED=True,
        MASS_SEND_WAIT_SECONDS=1800, MASS_SEND_MAX_RECIPIENTS=100, MASS_SEND_INTERVAL_RANGE=(0, 0),
        APPROVAL_CODES=frozenset({"1", "2"}), OFFER_APPROVAL_CODE="1",
    )
    fields.update(overrides)
    return NS(**fields)


def build_env(stored_messages=None, send_errors=None, **overrides):
    """从main.py抽出群发相关函数，用假的Telegram客户端跑。
    stored_messages：{消息ID: 消息}，get_messages按ID取；send_errors：{用户名: 异常}。"""
    source = ast.parse(Path(__file__).with_name("main.py").read_text())
    names = {"on_ssc_mass_send", "run_mass_send", "mass_send_error_reason",
             "get_ssc_reviewer", "usable_media", "on_ssc_send_approval",
             "on_ssc_diff_mass_send", "run_diff_mass_send"}
    functions = [n for n in source.body if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef))
                 and n.name in names]
    assert {f.name for f in functions} == names
    for node in functions:
        node.decorator_list = []

    notices, delivered, parse_modes = [], [], []
    send_errors = send_errors or {}

    async def send_message(destination, message, **kwargs):
        if destination == SSC_ID:
            notices.append(message)
            return NS(id=900 + len(notices))
        error = send_errors.get(destination.username)
        if error:
            raise error
        delivered.append((destination.username, message))
        if "parse_mode" in kwargs:
            parse_modes.append(kwargs["parse_mode"])

    async def get_entity(tg):
        if tg in send_errors and isinstance(send_errors[tg], ValueError):
            raise send_errors[tg]
        return NS(username=tg)

    # 往send_errors里放ValueError表示get_entity找不到；其它异常表示send_message失败。
    async def get_messages(chat_id, ids=None):
        return (stored_messages or {}).get(ids)

    client = NS(
        send_message=send_message, get_entity=get_entity, get_messages=get_messages,
        get_me=AsyncMock(return_value=NS(id=SSC_ID)),
    )
    select_pending_calls = []

    def select_pending(*args, **kwargs):
        select_pending_calls.append(args)
        return None

    env = {
        "asyncio": asyncio, "time": time, "errors": errors, "mass_send": mass_send,
        "random": NS(uniform=lambda a, b: 0),
        "config": base_config(**overrides), "log": logging.getLogger("test"),
        "client": client, "mass_send_lock": asyncio.Lock(), "mass_send_events": MemoryStore(),
        "mass_send_consumed": [], "mass_send_tasks": set(),
        "select_pending": select_pending, "ssc_send_lock": asyncio.Lock(),
        "outbox": NS(all=lambda: {}), "state": NS(all=lambda: {}),
    }

    async def get_ssc_reviewer():
        return NS(id=SSC_ID)

    exec(compile(ast.Module(body=functions, type_ignores=[]), "main.py", "exec"), env)
    env["get_ssc_reviewer"] = get_ssc_reviewer
    env["_notices"] = notices
    env["_parse_modes"] = parse_modes
    env["_delivered"] = delivered
    env["_select_pending_calls"] = select_pending_calls
    return env


_next_id = [1000]


def event_for(text, chat_id=SSC_ID, sender_id=SSC_ID, media=None, grouped_id=None, msg_id=None):
    _next_id[0] += 1
    message = NS(id=msg_id or _next_id[0], raw_text=text, media=media, grouped_id=grouped_id,
                 reply_to_msg_id=None)
    return NS(chat_id=chat_id, sender_id=sender_id, is_private=chat_id > 0, raw_text=text, message=message)


async def say(env, text, **kwargs):
    event = event_for(text, **kwargs)
    await env["on_ssc_mass_send"](event)
    return event


async def drain(env):
    while env["mass_send_tasks"]:
        await asyncio.gather(*list(env["mass_send_tasks"]))


class MassSendFlowTest(IsolatedAsyncioTestCase):
    async def test_full_flow_sends_text_and_image_to_each_tg(self):
        content = NS(id=2000, raw_text="请查收通知", media=NS(), grouped_id=None)
        env = build_env({2000: content})
        await say(env, "群发")
        self.assertIn("请发送要群发的TG", env["_notices"][-1])
        await say(env, "@wssahfkj @lovact2026\n@songyang518")
        self.assertIn("共3个TG", env["_notices"][-1])
        self.assertIn("@lovact2026", env["_notices"][-1])
        self.assertEqual(env["mass_send_events"].get("session")["stage"], mass_send.STAGE_WAITING_TGS_CONFIRM)
        await say(env, "1")
        self.assertIn("请发送要群发的图文消息", env["_notices"][-1])
        await say(env, "请查收通知", media=content.media, msg_id=2000)
        self.assertIn("已收到要群发的消息", env["_notices"][-1])
        self.assertIn("带图片/文件", env["_notices"][-1])
        self.assertEqual(env["_delivered"], [])  # 确认前不发
        await say(env, "1")
        await drain(env)
        self.assertEqual([tg for tg, _ in env["_delivered"]], ["@wssahfkj", "@lovact2026", "@songyang518"])
        self.assertTrue(all(message is content for _, message in env["_delivered"]))
        self.assertIn("成功3个，失败0个", env["_notices"][-1])
        self.assertEqual(env["mass_send_events"].get("session"), {})

    async def test_edited_content_is_used_at_send_time(self):
        original = NS(id=2000, raw_text="旧", media=None, grouped_id=None)
        env = build_env({2000: original})
        await say(env, "群发"); await say(env, "@aaaaa1"); await say(env, "1")
        await say(env, "旧", msg_id=2000)
        env["_stored"] = None
        edited = NS(id=2000, raw_text="新", media=None, grouped_id=None)
        env["client"].get_messages = AsyncMock(return_value=edited)
        await say(env, "1")
        await drain(env)
        self.assertEqual(env["_delivered"][0][1].raw_text, "新")

    async def test_bot_notices_do_not_retrigger(self):
        env = build_env()
        await say(env, "群发")
        count = len(env["_notices"])
        for notice in list(env["_notices"]):
            await say(env, notice)
        self.assertEqual(len(env["_notices"]), count)
        # 回显名单的提示里有@用户名，也不能被当成名单
        await say(env, "@aaaaa1")
        await say(env, env["_notices"][-1])
        self.assertEqual(env["mass_send_events"].get("session")["tgs"], ["@aaaaa1"])

    async def test_invalid_list_rejected_and_stays_waiting(self):
        env = build_env()
        await say(env, "群发")
        await say(env, "@good123 @ab")
        self.assertIn("@ab", env["_notices"][-1])
        self.assertIn("认不出", env["_notices"][-1])
        self.assertEqual(env["mass_send_events"].get("session")["stage"], mass_send.STAGE_WAITING_TGS)
        await say(env, "1")  # 没有名单时的1不推进
        self.assertEqual(env["mass_send_events"].get("session")["stage"], mass_send.STAGE_WAITING_TGS)

    async def test_resend_list_replaces_before_confirm(self):
        env = build_env()
        await say(env, "群发"); await say(env, "@aaaaa1"); await say(env, "@bbbbb2 @ccccc3")
        self.assertEqual(env["mass_send_events"].get("session")["tgs"], ["@bbbbb2", "@ccccc3"])

    async def test_too_many_recipients(self):
        env = build_env(MASS_SEND_MAX_RECIPIENTS=2)
        await say(env, "群发")
        await say(env, "@aaaaa1 @bbbbb2 @ccccc3")
        self.assertIn("超过一次最多2个", env["_notices"][-1])
        self.assertEqual(env["mass_send_events"].get("session")["stage"], mass_send.STAGE_WAITING_TGS)

    async def test_cancel_at_any_stage(self):
        env = build_env()
        await say(env, "群发"); await say(env, "@aaaaa1"); await say(env, "1")
        await say(env, "取消")
        self.assertIn("已取消", env["_notices"][-1])
        count = len(env["_notices"])
        await say(env, "1")
        await say(env, "随便聊聊")
        self.assertEqual(len(env["_notices"]), count)
        self.assertEqual(env["_delivered"], [])

    async def test_expired_session_is_ignored(self):
        env = build_env()
        await say(env, "群发"); await say(env, "@aaaaa1")
        session = env["mass_send_events"].get("session")
        env["mass_send_events"].set("session", {**session, "since": time.time() - 4000})
        count = len(env["_notices"])
        await say(env, "1")
        self.assertEqual(len(env["_notices"]), count)

    async def test_trigger_must_be_exact_and_from_ssc_saved_messages(self):
        env = build_env()
        await say(env, "群发一下")
        await say(env, "我要群发")
        await say(env, "群发", chat_id=-100123)
        await say(env, "群发", sender_id=555)
        self.assertEqual(env["_notices"], [])
        self.assertIsNone(env["mass_send_events"].get("session"))

    async def test_disabled_outside_prod(self):
        env = build_env(MASS_SEND_ENABLED=False, ENVIRONMENT="test", MASS_SEND_CONFIRM_CODE="测试1")
        await say(env, "群发")
        self.assertEqual(env["_notices"], [])

    async def test_waiting_message_ignores_codes_and_empty(self):
        env = build_env()
        await say(env, "群发"); await say(env, "@aaaaa1"); await say(env, "1")
        await say(env, "2")  # 别的功能的审批码不是群发内容
        await say(env, "1")
        self.assertEqual(env["mass_send_events"].get("session")["stage"], mass_send.STAGE_WAITING_MESSAGE)
        await say(env, "")
        self.assertEqual(env["mass_send_events"].get("session")["stage"], mass_send.STAGE_WAITING_MESSAGE)

    async def test_album_warning(self):
        env = build_env()
        await say(env, "群发"); await say(env, "@aaaaa1"); await say(env, "1")
        await say(env, "", media=NS(), grouped_id=123)
        self.assertIn("相册", env["_notices"][-1])

    async def test_trigger_during_sending_does_not_reset(self):
        env = build_env()
        env["mass_send_events"].set("session", {"stage": mass_send.STAGE_SENDING, "since": time.time(), "tgs": []})
        await say(env, "群发")
        self.assertIn("还在进行中", env["_notices"][-1])
        self.assertEqual(env["mass_send_events"].get("session")["stage"], mass_send.STAGE_SENDING)

    async def test_partial_failures_reported(self):
        content = NS(id=2000, raw_text="通知", media=None, grouped_id=None)
        env = build_env({2000: content}, send_errors={
            "@nouser1": ValueError("No user has nouser1"),
            "@privacy": errors.UserPrivacyRestrictedError(request=None),
        })
        await say(env, "群发"); await say(env, "@okuser1 @nouser1 @privacy @okuser2"); await say(env, "1")
        await say(env, "通知", msg_id=2000); await say(env, "1")
        await drain(env)
        self.assertEqual([tg for tg, _ in env["_delivered"]], ["@okuser1", "@okuser2"])
        report = env["_notices"][-1]
        self.assertIn("成功2个，失败2个", report)
        self.assertIn("@nouser1（找不到这个用户名）", report)
        self.assertIn("@privacy（对方隐私设置不接收陌生人消息）", report)

    async def test_peer_flood_stops_and_lists_remaining(self):
        content = NS(id=2000, raw_text="通知", media=None, grouped_id=None)
        env = build_env({2000: content}, send_errors={"@flood01": errors.PeerFloodError(request=None)})
        await say(env, "群发"); await say(env, "@okuser1 @flood01 @later01 @later02"); await say(env, "1")
        await say(env, "通知", msg_id=2000); await say(env, "1")
        await drain(env)
        self.assertEqual([tg for tg, _ in env["_delivered"]], ["@okuser1"])
        report = env["_notices"][-1]
        self.assertIn("成功1个，失败0个，未发送3个", report)
        self.assertIn("@later02", report)
        self.assertEqual(env["mass_send_events"].get("session"), {})

    async def test_content_deleted_before_send(self):
        env = build_env({})
        await say(env, "群发"); await say(env, "@aaaaa1"); await say(env, "1")
        await say(env, "通知", msg_id=2000); await say(env, "1")
        await drain(env)
        self.assertEqual(env["_delivered"], [])
        self.assertIn("找不到了", env["_notices"][-1])
        self.assertEqual(env["mass_send_events"].get("session"), {})


class ApprovalGuardTest(IsolatedAsyncioTestCase):
    async def approve(self, env, text="1", msg_id=None):
        event = event_for(text, msg_id=msg_id)
        await env["on_ssc_send_approval"](event)
        return event

    async def test_one_not_released_to_offers_while_mass_send_waits(self):
        env = build_env()
        await say(env, "群发"); await say(env, "@aaaaa1")
        await self.approve(env)
        self.assertEqual(env["_select_pending_calls"], [])

    async def test_one_after_session_handled_it_first_still_skipped(self):
        env = build_env()
        await say(env, "群发"); await say(env, "@aaaaa1")
        event = event_for("1")
        await env["on_ssc_mass_send"](event)       # 群发处理器先处理：阶段已推进到等图文
        await env["on_ssc_send_approval"](event)   # 审批处理器后到，仍要让开
        self.assertEqual(env["_select_pending_calls"], [])

    async def test_one_released_normally_without_session(self):
        env = build_env()
        await self.approve(env)
        self.assertEqual(len(env["_select_pending_calls"]), 1)

    async def test_other_codes_unaffected(self):
        env = build_env()
        await say(env, "群发"); await say(env, "@aaaaa1")
        await self.approve(env, "2")
        self.assertEqual(len(env["_select_pending_calls"]), 1)

    async def test_one_while_waiting_for_message_is_not_consumed_but_not_guarded_either(self):
        # 等图文阶段"1"不是确认码用途（被忽略），这时放行offer属于正常审批。
        env = build_env()
        await say(env, "群发"); await say(env, "@aaaaa1"); await say(env, "1")
        await self.approve(env)
        self.assertEqual(len(env["_select_pending_calls"]), 1)


TABLE = """| TG | URL |
|---|---|
| @songyang518 | https://docs.google.com/document/d/1tvKILf-eNZRbXHdaEQfXq5zVIA7sKoog4RzYgiPLD0I/edit |
| @jiangshangmu | https://docs.google.com/document/d/1xLaEmpK3JoTYJHcOCxx95g4sws9h9HVp_1bglm0-4gA/edit |
| @Deron_8 | https://docs.google.com/document/d/1pBHome72Pyzwl4plo_wu91__w_bCeqQbbB51cWzDNak/edit |"""


class ParseTgMessagesTest(TestCase):
    def test_markdown_table_skips_header_and_separator(self):
        items, bad = mass_send.parse_tg_messages(TABLE)
        self.assertEqual([tg for tg, _ in items], ["@songyang518", "@jiangshangmu", "@Deron_8"])
        self.assertTrue(items[0][1].startswith("https://docs.google.com/document/d/1tvKILf"))
        self.assertEqual(bad, [])

    def test_one_line_each(self):
        items, bad = mass_send.parse_tg_messages("@aaaaa1 你好，请查收\n\n@bbbbb2：第二条 带 空格\n@ccccc3,第三条")
        self.assertEqual(items, [("@aaaaa1", "你好，请查收"), ("@bbbbb2", "第二条 带 空格"), ("@ccccc3", "第三条")])
        self.assertEqual(bad, [])

    def test_bad_lines_and_placeholder_example(self):
        items, bad = mass_send.parse_tg_messages("tg1 消息1\n@ab 短\n@okuser1\n@okuser2 好")
        self.assertEqual(items, [("@okuser2", "好")])
        self.assertEqual(bad, ["tg1 消息1", "@ab 短", "@okuser1"])

    def test_same_tg_different_messages_kept_exact_duplicates_dropped(self):
        items, _ = mass_send.parse_tg_messages("@aaaaa1 甲\n@aaaaa1 乙\n@AAAAA1 甲")
        self.assertEqual(items, [("@aaaaa1", "甲"), ("@aaaaa1", "乙")])

    def test_attempt_detection(self):
        self.assertFalse(mass_send.looks_like_table_attempt(*mass_send.parse_tg_messages("员工绩效")))
        self.assertTrue(mass_send.looks_like_table_attempt(*mass_send.parse_tg_messages("@ab 短")))

    def test_chunk_text_and_preview(self):
        text = "\n".join("x" * 100 for _ in range(100))
        chunks = mass_send.chunk_text(text, 1000)
        self.assertTrue(all(len(c) <= 1000 for c in chunks))
        self.assertEqual("\n".join(chunks), text)
        self.assertEqual(mass_send.preview("a" * 50, 10), "a" * 10 + "…")


class DiffMassSendTest(IsolatedAsyncioTestCase):
    async def say(self, env, text, **kwargs):
        event = event_for(text, **kwargs)
        await env["on_ssc_diff_mass_send"](event)
        await env["on_ssc_mass_send"](event)
        return event

    async def test_full_flow_each_tg_gets_its_own_message(self):
        env = build_env()
        await self.say(env, "不同群发")
        self.assertIn("请发送要群发的TG和各自的消息", env["_notices"][-1])
        await self.say(env, TABLE)
        self.assertIn("共3条", env["_notices"][-1])
        self.assertIn("@Deron_8", env["_notices"][-1])
        self.assertEqual(env["_delivered"], [])
        await self.say(env, "1")
        await drain(env)
        self.assertEqual([tg for tg, _ in env["_delivered"]], ["@songyang518", "@jiangshangmu", "@Deron_8"])
        self.assertIn("1pBHome72Pyzwl4plo_wu91__w_bCeqQbbB51cWzDNak", env["_delivered"][2][1])
        self.assertNotEqual(env["_delivered"][0][1], env["_delivered"][1][1])
        self.assertEqual(set(env["_parse_modes"]), {None})  # URL里的__不能被当Markdown斜体
        self.assertIn("成功3个，失败0个", env["_notices"][-1])
        self.assertEqual(env["mass_send_events"].get("diff_session"), {})

    async def test_notices_do_not_retrigger_and_plain_group_send_untouched(self):
        env = build_env()
        await self.say(env, "不同群发")
        for notice in list(env["_notices"]):
            await self.say(env, notice)
        self.assertEqual(env["mass_send_events"].get("diff_session")["stage"], mass_send.STAGE_DIFF_WAITING_INPUT)
        self.assertFalse(env["mass_send_events"].get("session"))

    async def test_bad_lines_rejected_stay_waiting(self):
        env = build_env()
        await self.say(env, "不同群发")
        await self.say(env, "@okuser1 好\n@ab 短")
        self.assertIn("1行认不出", env["_notices"][-1])
        self.assertEqual(env["mass_send_events"].get("diff_session")["stage"], mass_send.STAGE_DIFF_WAITING_INPUT)
        await self.say(env, "1")
        self.assertEqual(env["_delivered"], [])

    async def test_resend_replaces_and_cancel(self):
        env = build_env()
        await self.say(env, "不同群发")
        await self.say(env, "@aaaaa1 甲")
        await self.say(env, "@bbbbb2 乙")
        self.assertEqual(env["mass_send_events"].get("diff_session")["items"], [["@bbbbb2", "乙"]])
        await self.say(env, "取消")
        self.assertIn("已取消", env["_notices"][-1])
        await self.say(env, "1")
        await drain(env)
        self.assertEqual(env["_delivered"], [])

    async def test_failures_and_flood_reported(self):
        env = build_env(send_errors={"@nouser1": ValueError("x"), "@flood01": errors.PeerFloodError(request=None)})
        await self.say(env, "不同群发")
        await self.say(env, "@okuser1 甲\n@nouser1 乙\n@flood01 丙\n@later01 丁")
        await self.say(env, "1")
        await drain(env)
        self.assertEqual(env["_delivered"], [("@okuser1", "甲")])
        report = env["_notices"][-1]
        self.assertIn("成功1个，失败1个，未发送2个", report)
        self.assertIn("@nouser1（找不到这个用户名）", report)

    async def test_too_many_and_long_echo_is_chunked(self):
        env = build_env(MASS_SEND_MAX_RECIPIENTS=2)
        await self.say(env, "不同群发")
        await self.say(env, "@aaaaa1 甲\n@bbbbb2 乙\n@ccccc3 丙")
        self.assertIn("超过一次最多2条", env["_notices"][-1])
        env = build_env(MASS_SEND_MAX_RECIPIENTS=500)
        await self.say(env, "不同群发")
        await self.say(env, "\n".join(f"@user{i:04d} " + "很长的消息" * 20 for i in range(150)))
        self.assertGreater(len(env["_notices"]), 2)
        self.assertTrue(all(len(n) <= 4096 for n in env["_notices"]))

    async def test_only_one_session_at_a_time(self):
        env = build_env()
        await self.say(env, "群发")
        await self.say(env, "不同群发")
        self.assertIsNone(env["mass_send_events"].get("session") or None)
        self.assertEqual(env["mass_send_events"].get("diff_session")["stage"], mass_send.STAGE_DIFF_WAITING_INPUT)
        await self.say(env, "群发")
        self.assertEqual(env["mass_send_events"].get("diff_session"), {})
        self.assertEqual(env["mass_send_events"].get("session")["stage"], mass_send.STAGE_WAITING_TGS)

    async def test_diff_trigger_not_taken_as_content_of_group_send(self):
        env = build_env()
        await self.say(env, "群发"); await self.say(env, "@aaaaa1"); await self.say(env, "1")
        await self.say(env, "不同群发")
        self.assertEqual(env["mass_send_events"].get("diff_session")["stage"], mass_send.STAGE_DIFF_WAITING_INPUT)

    async def test_trigger_during_sending_is_busy(self):
        env = build_env()
        env["mass_send_events"].set("diff_session", {"stage": mass_send.STAGE_SENDING, "since": time.time(), "items": []})
        await self.say(env, "群发")
        self.assertIn("还在进行中", env["_notices"][-1])
        await self.say(env, "不同群发")
        self.assertIn("还在进行中", env["_notices"][-1])

    async def test_disabled_outside_prod_and_exact_trigger(self):
        env = build_env(MASS_SEND_ENABLED=False)
        await self.say(env, "不同群发")
        self.assertEqual(env["_notices"], [])
        env = build_env()
        await self.say(env, "不同群发一下")
        await self.say(env, "不同群发", chat_id=-100123)
        self.assertEqual(env["_notices"], [])

    async def test_confirm_one_not_released_to_offers(self):
        env = build_env()
        await self.say(env, "不同群发"); await self.say(env, "@aaaaa1 甲")
        event = event_for("1")
        await env["on_ssc_diff_mass_send"](event)
        await env["on_ssc_send_approval"](event)
        self.assertEqual(env["_select_pending_calls"], [])
        await drain(env)
