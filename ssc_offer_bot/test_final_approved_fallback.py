# -*- coding: utf-8 -*-
"""终审通过后，招聘群里如果找不到带候选人编码的正式简历，退而求其次找一条
提到候选人姓名的其他消息（面试邀约、Zoom会议通知等），继续走后续流程，
而不是直接放弃并要求人工处理。"""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import unicodedata
from parsers import parse_kv_fields, get_field

source = Path(__file__).with_name('main.py').read_text()
tree = ast.parse(source)
selected = {
    'matches_recruit_candidate', 'matches_recruit_candidate_by_name',
    '_normalized_name', 'handle_final_approved',
}
config = NS(GROUP_RECRUIT=-456)
ns = dict(
    config=config, parse_kv_fields=parse_kv_fields, get_field=get_field,
    unicodedata=unicodedata,
)
exec(compile(ast.Module(
    body=[n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
          and n.name in selected],
    type_ignores=[]), '<final_approved_fallback>', 'exec'), ns)


class Store:
    def __init__(self, data):
        self.data = data

    def get(self, k):
        return self.data.get(k)

    def update(self, k, **v):
        self.data.setdefault(k, {}).update(v)


def messages(*msgs):
    async def history(*a, **kw):
        for m in msgs:
            yield m
    return history


class FinalApprovedFallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ns['state'] = Store({'shun': {}})
        ns['queue_group_message'] = AsyncMock()
        ns['get_ssc_reviewer'] = AsyncMock(return_value=NS(id=99))
        ns['client'] = NS(send_message=AsyncMock())
        ns['log'] = NS(warning=lambda *a: None, info=lambda *a: None, exception=lambda *a: None)
        ns['build_recruit_reply_message'] = lambda **kw: '入职通知草稿'

    async def test_strict_resume_match_is_unaffected(self):
        resume = NS(id=70, raw_text='候选人编码：A1\n候选人姓名：shun',
                    get_sender=AsyncMock(return_value=NS(id=8, username='recruiter')))
        ns['client'].iter_messages = messages(resume)
        rec = {'raw_fields': {'候选人编码': 'A1'}}
        await ns['handle_final_approved']('shun', rec)
        call = ns['queue_group_message'].call_args
        self.assertEqual(call.kwargs['reply_to'], 70)
        ns['client'].send_message.assert_not_awaited()

    async def test_falls_back_to_message_mentioning_name_when_no_resume(self):
        zoom_invite = NS(
            id=80,
            raw_text='候选人姓名：shun\n岗位：远程前端工程师(Android+Flutter)\n面试方式：Zoom',
            get_sender=AsyncMock(return_value=NS(id=9, username='hr_weien')),
        )
        ns['client'].iter_messages = messages(zoom_invite)
        rec = {'raw_fields': {'候选人编码': 'A1'}}
        await ns['handle_final_approved']('shun', rec)

        call = ns['queue_group_message'].call_args
        self.assertIsNotNone(call, '找到姓名线索消息时应该继续走群通知流程，而不是放弃')
        self.assertEqual(call.kwargs['reply_to'], 80)
        self.assertEqual(call.kwargs['updates']['recruiter_username'], 'hr_weien')
        # 应该告知SSC这是用姓名线索兜底的，不是正式简历，请人工核实。
        notice = ns['client'].send_message.call_args.args[1]
        self.assertIn('shun', notice)
        self.assertIn('80', notice)

    async def test_no_match_at_all_still_reports_for_manual_handling(self):
        unrelated = NS(id=90, raw_text='候选人姓名：小明\n入职部门：技术中心',
                       get_sender=AsyncMock(return_value=NS(id=1, username='other')))
        ns['client'].iter_messages = messages(unrelated)
        rec = {'raw_fields': {'候选人编码': 'A1'}}
        await ns['handle_final_approved']('shun', rec)

        ns['queue_group_message'].assert_not_awaited()
        self.assertEqual(ns['state'].data['shun']['stage'], 'final_approved_no_resume_found')
        notice = ns['client'].send_message.call_args.args[1]
        self.assertIn('也没有找到提到该姓名的其他消息', notice)


if __name__ == '__main__':
    unittest.main()
