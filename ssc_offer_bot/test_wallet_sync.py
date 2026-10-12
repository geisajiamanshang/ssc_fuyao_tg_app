# -*- coding: utf-8 -*-
"""场景十二：恒睿SSC/HRBP-沟通群（跟场景一HRBP发Offer消息是同一个群）里，
@ling2089核对完员工本人的钱包收款地址后，转发/回复一条带"钱包收款地址"
关键词的确认消息——按这条消息里的"花名"，到同一个群更早的消息里找HR人工
发的【新入职员工钱包地址信息同步】草稿（钱包地址在草稿里本来就已经填好，
这条确认只是核对，不是提供新地址），去掉草稿结尾的通知行，发到SSC收藏夹，
经审批码13（测试13）放行到恒睿公司-联合管理工作群。"""

import ast
import asyncio
import re
import unittest
import unicodedata
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from parsers import parse_kv_fields, get_field

source = Path(__file__).with_name('main.py').read_text()
tree = ast.parse(source)
selected = {
    '_core_name', '_normalized_name', 'matches_wallet_sync_draft',
    'strip_wallet_sync_notice_lines', 'on_wallet_sync_confirmation',
}
config = NS(
    GROUP_HRBP=-100, GROUP_LEADERSHIP=-200, EXCLUDED_CHAT_IDS=frozenset(),
    WALLET_SYNC_TRIGGER_SENDER='ling2089', WALLET_SYNC_APPROVAL_CODE='13',
)
ns = dict(
    config=config, re=re, unicodedata=unicodedata,
    parse_kv_fields=parse_kv_fields, get_field=get_field,
    # 场景十二模块级常量：main.py里是普通赋值语句，不是函数定义，AST按
    # FunctionDef/AsyncFunctionDef筛选时不会带过来，照已有的坑手动注入。
    WALLET_SYNC_HEADER='【新入职员工钱包地址信息同步】',
)
functions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.name in selected]
for node in functions:
    # on_wallet_sync_confirmation在main.py里是@client.on(...)直接修饰的
    # 事件处理函数本身（不是另有一层薄包装），不去掉装饰器的话exec时
    # 装饰器本身就会求值，要求client/events在ns里存在，这里只测内部逻辑，
    # 不需要真的注册到client上。
    node.decorator_list = []
exec(compile(ast.Module(body=functions, type_ignores=[]), '<wallet_sync>', 'exec'), ns)


class Store:
    """StateStore的最小替身：get/set/update语义跟真实StateStore一致
    （update按setdefault处理，不要求key预先存在）。"""
    def __init__(self, data=None):
        self.data = data if data is not None else {}

    def get(self, k):
        return self.data.get(k)

    def set(self, k, v):
        self.data[k] = v

    def update(self, k, **v):
        self.data.setdefault(k, {}).update(v)


def messages(*msgs):
    async def history(*a, **kw):
        for m in msgs:
            yield m
    return history


DRAFT_TEXT = (
    "【新入职员工钱包地址信息同步】\n"
    "编号：YY6253\n"
    "花名：李光\n"
    "事业部（一级部门）：运营中心\n"
    "部门（二级部门）：AIGC原创部\n"
    "职位：运营专员\n"
    "钱包地址：THQXyg57xgh8sESMQKiyRsCbn79yjVnKak\n"
    "工作TG：@liguangggg\n"
    "工作邮箱：xiaowenlongwu@gmail.com\n"
    "入职日期：2026-10-08\n"
    "\n"
    "@ling2089 请和员工再次核对钱包地址，谢谢。\n"
    "@wean4790 请知悉"
)

EXPECTED_FINAL_TEXT = (
    "【新入职员工钱包地址信息同步】\n"
    "编号：YY6253\n"
    "花名：李光\n"
    "事业部（一级部门）：运营中心\n"
    "部门（二级部门）：AIGC原创部\n"
    "职位：运营专员\n"
    "钱包地址：THQXyg57xgh8sESMQKiyRsCbn79yjVnKak\n"
    "工作TG：@liguangggg\n"
    "工作邮箱：xiaowenlongwu@gmail.com\n"
    "入职日期：2026-10-08"
)

CONFIRMATION_TEXT = (
    "花名：李光\n"
    "员工编号：YY6253\n"
    "钱包收款地址：THQXyg57xgh8sESMQKiyRsCbn79yjVnKak\n"
    "附收款二维码"
)


class WalletSyncMatchTests(unittest.TestCase):
    def test_matches_draft_by_exact_name(self):
        self.assertTrue(ns['matches_wallet_sync_draft'](DRAFT_TEXT, '李光'))

    def test_rejects_message_without_header(self):
        # 真实场景里，@ling2089的确认消息本身也带"花名：李光"，但没有草稿
        # 固定的方括号标题，不应该被误判成草稿本身。
        self.assertFalse(ns['matches_wallet_sync_draft'](CONFIRMATION_TEXT, '李光'))

    def test_rejects_name_mismatch(self):
        other = DRAFT_TEXT.replace('花名：李光', '花名：星榆')
        self.assertFalse(ns['matches_wallet_sync_draft'](other, '李光'))

    def test_rejects_missing_name_field(self):
        text = '【新入职员工钱包地址信息同步】\n编号：YY6253\n钱包地址：ABC'
        self.assertFalse(ns['matches_wallet_sync_draft'](text, '李光'))


class StripNoticeLinesTests(unittest.TestCase):
    def test_strips_two_differently_worded_trailing_mention_lines(self):
        # 两行收尾措辞不一样（"谢谢。"/"请知悉"），不是只认"请知悉"这一种。
        self.assertEqual(ns['strip_wallet_sync_notice_lines'](DRAFT_TEXT), EXPECTED_FINAL_TEXT)

    def test_no_trailing_mentions_returns_unchanged(self):
        text = '【新入职员工钱包地址信息同步】\n花名：李光\n入职日期：2026-10-08'
        self.assertEqual(ns['strip_wallet_sync_notice_lines'](text), text)


class WalletSyncConfirmationHandlerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ns['wallet_sync_events'] = Store()
        ns['wallet_sync_lock'] = asyncio.Lock()
        ns['log'] = NS(warning=lambda *a: None, info=lambda *a: None, exception=lambda *a: None)
        ns['get_ssc_reviewer'] = AsyncMock(return_value=NS(id=99))
        ns['queue_group_message'] = AsyncMock()
        ns['client'] = NS(send_message=AsyncMock())
        config.EXCLUDED_CHAT_IDS = frozenset()
        config.WALLET_SYNC_TRIGGER_SENDER = 'ling2089'

    def _confirmation_event(self, msg_id=80, username='ling2089', text=CONFIRMATION_TEXT):
        return NS(
            chat_id=config.GROUP_HRBP,
            message=NS(id=msg_id),
            raw_text=text,
            get_sender=AsyncMock(return_value=NS(id=5, username=username)),
        )

    async def test_confirmation_from_trigger_sender_queues_matching_draft(self):
        draft = NS(id=50, raw_text=DRAFT_TEXT)
        unrelated_older = NS(id=10, raw_text='随便聊聊')
        ns['client'].iter_messages = messages(unrelated_older, draft)

        await ns['on_wallet_sync_confirmation'](self._confirmation_event())

        call = ns['queue_group_message'].call_args
        self.assertIsNotNone(call, '应该把找到的草稿发到SSC收藏夹等待审批')
        self.assertEqual(call.args[0], config.GROUP_LEADERSHIP)
        self.assertEqual(call.args[1], EXPECTED_FINAL_TEXT)
        self.assertEqual(call.kwargs['approval_code'], '13')
        ns['client'].send_message.assert_not_awaited()

    async def test_draft_posted_after_confirmation_is_not_matched(self):
        # 草稿msg_id比确认消息还新，说明是巧合撞名的另一次同步，不该被当成
        # 这次确认对应的草稿。
        later_draft = NS(id=999, raw_text=DRAFT_TEXT)
        ns['client'].iter_messages = messages(later_draft)

        await ns['on_wallet_sync_confirmation'](self._confirmation_event(msg_id=80))

        ns['queue_group_message'].assert_not_awaited()
        notice = ns['client'].send_message.call_args.args[1]
        self.assertIn('未找到对应的「新入职员工钱包地址信息同步」草稿', notice)

    async def test_non_trigger_sender_is_ignored(self):
        ns['client'].iter_messages = messages(NS(id=50, raw_text=DRAFT_TEXT))
        await ns['on_wallet_sync_confirmation'](self._confirmation_event(username='someone_else'))
        ns['queue_group_message'].assert_not_awaited()
        ns['client'].send_message.assert_not_awaited()

    async def test_message_without_keyword_is_ignored(self):
        event = self._confirmation_event(text='花名：李光\n钱包地址：THQXyg57xgh8sESMQKiyRsCbn79yjVnKak')
        await ns['on_wallet_sync_confirmation'](event)
        ns['queue_group_message'].assert_not_awaited()

    async def test_no_matching_draft_notifies_ssc_for_manual_handling(self):
        ns['client'].iter_messages = messages(NS(id=50, raw_text='随便聊聊'))
        await ns['on_wallet_sync_confirmation'](self._confirmation_event())
        ns['queue_group_message'].assert_not_awaited()
        notice = ns['client'].send_message.call_args.args[1]
        self.assertIn('李光', notice)
        self.assertIn('未找到对应的「新入职员工钱包地址信息同步」草稿', notice)

    async def test_duplicate_confirmation_event_is_not_reprocessed(self):
        draft = NS(id=50, raw_text=DRAFT_TEXT)
        ns['client'].iter_messages = messages(draft)
        event = self._confirmation_event()

        await ns['on_wallet_sync_confirmation'](event)
        ns['queue_group_message'].reset_mock()
        await ns['on_wallet_sync_confirmation'](event)

        ns['queue_group_message'].assert_not_awaited()

    async def test_excluded_chat_is_ignored(self):
        config.EXCLUDED_CHAT_IDS = frozenset({config.GROUP_HRBP})
        try:
            ns['client'].iter_messages = messages()
            await ns['on_wallet_sync_confirmation'](self._confirmation_event())
            ns['queue_group_message'].assert_not_awaited()
            ns['client'].send_message.assert_not_awaited()
        finally:
            config.EXCLUDED_CHAT_IDS = frozenset()


if __name__ == '__main__':
    unittest.main()
