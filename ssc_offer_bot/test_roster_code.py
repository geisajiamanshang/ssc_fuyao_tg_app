import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import roster_code
from parsers import parse_kv_fields, get_field
from roster_code import RosterCodeRepository, column_index, plan_code_write

ROWS = [
    ["序号", "部门", "姓名", "候选人编码"],
    ["1", "运营", "张三", ""],
    ["2", "运营", "李 四", "HJHT0000001"],
    ["3", "技术", "王五", ""],
    ["4", "技术", "王五", ""],
]
C, D = 2, 3  # 测试表头把姓名/编码放在第3/4列，与真实表的C/D列同位置


class PlanTests(TestCase):
    def test_column_letters(self):
        self.assertEqual((column_index("C"), column_index("D"), column_index("AD")), (2, 3, 29))

    def test_empty_cell_for_unique_name_is_written(self):
        self.assertEqual(plan_code_write(ROWS, "张三", "HJHT0000126", C, D), ("written_new", 2))

    def test_name_match_ignores_inner_whitespace(self):
        self.assertEqual(plan_code_write(ROWS, "李四", "HJHT0000001", C, D), ("already_set", 3))

    def test_existing_different_code_is_never_overwritten(self):
        self.assertEqual(plan_code_write(ROWS, "李四", "HJHT0000999", C, D), ("conflict", 3))

    def test_unknown_name_not_written(self):
        self.assertEqual(plan_code_write(ROWS, "赵六", "HJHT1", C, D), ("name_not_found", None))

    def test_duplicate_names_with_several_empty_cells_are_ambiguous(self):
        self.assertEqual(plan_code_write(ROWS, "王五", "HJHT2", C, D), ("ambiguous", None))

    def test_header_row_is_never_matched(self):
        self.assertEqual(plan_code_write(ROWS, "姓名", "HJHT3", C, D)[0], "name_not_found")


class FakeResponse:
    def __init__(self, payload=None, status_code=200, text=""):
        self._payload, self.status_code, self.text = payload or {}, status_code, text

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class RepositoryTests(TestCase):
    def make(self, rows):
        calls = {"put": []}

        class Session:
            def get(self, url, params=None, timeout=None):
                if "/values/" in url:
                    return FakeResponse({"values": rows})
                return FakeResponse({"sheets": [
                    {"properties": {"sheetId": 1, "title": "other"}},
                    {"properties": {"sheetId": 1173062379, "title": "花名册'机器人'"}},
                ]})

            def put(self, url, params=None, json=None, timeout=None):
                calls["put"].append((url, params, json))
                return FakeResponse()

        repo = RosterCodeRepository("sheet-id", 1173062379, "C", "D")
        patcher = patch.object(roster_code, "_drive_session", lambda **kw: (Session(), {}))
        return repo, calls, patcher

    def test_writes_only_target_cell_with_raw_value(self):
        repo, calls, patcher = self.make(ROWS)
        with patcher:
            self.assertEqual(repo.write_code("张三", " HJHT0000126 "), ("written_new", 2))
        self.assertEqual(len(calls["put"]), 1)
        url, params, body = calls["put"][0]
        self.assertIn("D2", url.replace("%21", "!"))
        self.assertEqual(params["valueInputOption"], "RAW")
        self.assertEqual(body, {"values": [["HJHT0000126"]]})

    def test_no_write_when_not_writable_status(self):
        repo, calls, patcher = self.make(ROWS)
        with patcher:
            self.assertEqual(repo.write_code("赵六", "HJHT1")[0], "name_not_found")
        self.assertEqual(calls["put"], [])


def load_handler(config, client, repo, events_store):
    source = ast.parse(Path(__file__).with_name('main.py').read_text())
    nodes = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
             and n.name == 'record_candidate_code_to_roster']
    ns = dict(config=config, client=client, log=logging.getLogger('t'), asyncio=asyncio,
              parse_kv_fields=parse_kv_fields, get_field=get_field,
              roster_code_events=events_store, roster_code_lock=asyncio.Lock(),
              roster_code_repo=repo, get_ssc_reviewer=AsyncMock(return_value=NS(id=9)))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'main.py', 'exec'), ns)
    return ns['record_candidate_code_to_roster']


class Mem:
    def __init__(self): self.d = {}
    def get(self, k): return self.d.get(k)
    def set(self, k, v): self.d[k] = v


CONFIRM = "运营中心【入职信息确认】\n候选人编码：HJHT0000126\n候选人姓名：张三\n性别：男"


class HandlerTests(IsolatedAsyncioTestCase):
    def setup(self, result=("written_new", 2), enabled=True, error=None):
        sent = []

        async def send_message(dest, text, **kw):
            sent.append((dest, text))

        client = NS(get_me=AsyncMock(return_value=NS(id=9)), send_message=send_message)
        repo = NS(write_code=NS())
        calls = []

        def write_code(name, code):
            calls.append((name, code))
            if error:
                raise error
            return result

        repo.write_code = write_code
        config = NS(ROSTER_CODE_ENABLED=enabled, GROUP_LEADERSHIP=-1)
        store = Mem()
        return load_handler(config, client, repo, store), sent, calls, store

    def msg(self, text=CONFIRM, sender=9, msg_id=5):
        return NS(raw_text=text, sender_id=sender, id=msg_id)

    async def test_code_written_silently_on_success(self):
        handler, sent, calls, store = self.setup()
        await handler(self.msg(), -1)
        self.assertEqual(calls, [("张三", "HJHT0000126")])
        self.assertEqual(sent, [])
        self.assertEqual(store.get("-1:5")["status"], "written_new")

    async def test_same_message_not_written_twice(self):
        handler, sent, calls, _ = self.setup()
        await handler(self.msg(), -1)
        await handler(self.msg(), -1)
        self.assertEqual(len(calls), 1)

    async def test_name_not_found_notifies_ssc(self):
        handler, sent, calls, _ = self.setup(result=("name_not_found", None))
        await handler(self.msg(), -1)
        self.assertEqual(len(sent), 1)
        self.assertIn("没找到该姓名", sent[0][1])

    async def test_conflict_notifies_without_overwriting(self):
        handler, sent, calls, _ = self.setup(result=("conflict", 3))
        await handler(self.msg(), -1)
        self.assertIn("已有不同的编码", sent[0][1])

    async def test_sheet_error_notifies_ssc(self):
        handler, sent, calls, store = self.setup(error=RuntimeError("403"))
        await handler(self.msg(), -1)
        self.assertIn("失败", sent[0][1])
        self.assertEqual(store.get("-1:5")["status"], "failed")

    async def test_missing_code_skips_and_notifies(self):
        handler, sent, calls, _ = self.setup()
        await handler(self.msg(text="【入职信息确认】\n候选人姓名：张三"), -1)
        self.assertEqual(calls, [])
        self.assertIn("候选人编码", sent[0][1])

    async def test_ignored_when_disabled_other_chat_other_sender_or_other_text(self):
        for kwargs, args in (
            ({"enabled": False}, (self.msg(), -1)),
            ({}, (self.msg(), -2)),
            ({}, (self.msg(sender=8), -1)),
            ({}, (self.msg(text="随便聊聊"), -1)),
        ):
            handler, sent, calls, _ = self.setup(**kwargs)
            await handler(*args)
            self.assertEqual((calls, sent), ([], []))
