import ast
import logging
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo
from batch_approval import recover_approvals, missing_approvals
from parsers import is_approval, parse_kv_fields, get_field


class BatchFlowTests(IsolatedAsyncioTestCase):
    async def test_a_b_forwarded_c_missing_first_and_repeat_does_not_resend(self):
        records = {name: dict(offer_confirm_msg_id=i, org_unit='效能中心',
                             stage='waiting_final_review',
                             **({'first_approved_msg_id': 10+i} if name != '小C' else {}))
                   for i, name in enumerate(['小A', '小B', '小C'], 1)}
        class Store:
            def get(self, name):
                return records[name]
            def update(self, name, **values):
                records[name].update(values)
            def find_by_field(self, field, value):
                return next(((name, r) for name, r in records.items() if r.get(field) == value), (None, None))
        now = datetime(2026, 9, 19, 7, tzinfo=timezone.utc)
        messages = [NS(id=i, sender_id=9, raw_text='效能中心【offer信息确认】',
                       date=now, reply_to_msg_id=None,
                       get_sender=AsyncMock(return_value=NS(username='ssc')))
                    for i in [3, 2, 1]]
        async def history(*args, **kwargs):
            for msg in messages:
                yield msg
        forward = AsyncMock(return_value=NS(id=200))
        final = AsyncMock()
        notify = AsyncMock()
        env = dict(globals(), state=Store(), log=logging.getLogger('test'),
                   client=NS(get_me=AsyncMock(return_value=NS(id=9)),
                             iter_messages=history, forward_messages=forward),
                   config=NS(DAILY_REPORT_TIMEZONE='Asia/Shanghai', GROUP_LEADERSHIP=-1,
                             LEADER_FIRST='first', LEADER_SECOND_TECH='second',
                             TECH_CENTER_KEYWORDS=['技术中心']),
                   handle_final_approved=final, _send_saved_text=notify)
        tree = ast.parse(Path(__file__).with_name('main.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.AsyncFunctionDef) and n.name == 'process_batch_final')
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'main.py', 'exec'), env)
        event = NS(message=NS(id=100, date=now))
        await env['process_batch_final'](event)
        self.assertEqual([call.args[1] for call in forward.await_args_list], [1, 2])
        self.assertEqual([call.args[0] for call in final.await_args_list], ['小A', '小B'])
        self.assertIn('小C：尚未经过一级领导 @first 的初审', notify.await_args.args[1])
        self.assertNotIn('batch_final_msg_id', records['小C'])
        self.assertEqual(records['小C']['approvals']['final']['message_id'],100)
        await env['process_batch_final'](event)
        self.assertEqual(forward.await_count, 2)
