# -*- coding: utf-8 -*-
"""场景二：领导直接在@他的审批提示消息上点表情（如👌）也算审批通过，
不用非得回复文字。"""

import ast
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from types import SimpleNamespace
import unicodedata

from parsers import is_approval, parse_kv_fields, get_field

source = Path(__file__).with_name('main.py').read_text()
tree = ast.parse(source)
selected = {
    'approval_roles', 'role_username', 'approval_role', 'apply_approval_evidence',
    'advance_offer', 'notify_missing', '_offer_record_for_message',
    '_find_approval_reactor', 'process_leadership_reaction',
}
config = NS(
    LEADER_FIRST='first_user', LEADER_SECOND_TECH='second_user', LEADER_FINAL='final_user',
    GROUP_LEADERSHIP=-123, EXCLUDED_CHAT_IDS=frozenset(),
    APPROVAL_REACTION_EMOJIS=frozenset({'👌'}),
)
def _get_peer_id(peer):
    return getattr(peer, 'fake_peer_id', -123)


class _FakeReactionEmoji:
    def __init__(self, emoticon):
        self.emoticon = emoticon


def _get_message_reactions_list_request(peer, id, reaction, limit):
    return NS(peer=peer, id=id, reaction=reaction, limit=limit)


ns = dict(
    config=config, unicodedata=unicodedata, is_approval=is_approval,
    parse_kv_fields=parse_kv_fields, get_field=get_field,
    utils=NS(get_peer_id=_get_peer_id),
    SimpleNamespace=SimpleNamespace,
    ReactionEmoji=_FakeReactionEmoji,
    GetMessageReactionsListRequest=_get_message_reactions_list_request,
)
exec(compile(ast.Module(
    body=[n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
          and n.name in selected],
    type_ignores=[]), '<leadership_reaction>', 'exec'), ns)


class MockClient:
    """client(SomeRequest(...))这种可调用写法在telethon里很常见，SimpleNamespace
    不支持让实例本身可调用，所以单独写一个最小的替身类。"""
    def __init__(self):
        self.call_mock = None

    async def __call__(self, *args, **kwargs):
        return await self.call_mock(*args, **kwargs)


class Store:
    def __init__(self, data):
        self.data = data

    def get(self, k):
        return self.data.get(k)

    def update(self, k, **v):
        self.data[k].update(v)

    def find_by_field(self, key, value):
        return next(((n, r) for n, r in self.data.items() if r.get(key) == value), (None, None))


def reactions_result(*users):
    """模拟GetMessageReactionsListRequest的返回：每个user对应一条回应记录。"""
    return NS(
        users=list(users),
        reactions=[NS(peer_id=NS(user_id=u.id)) for u in users],
    )


class LeadershipReactionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ns['queue_group_message'] = AsyncMock()
        ns['handle_final_approved'] = AsyncMock()
        ns['get_ssc_reviewer'] = AsyncMock(return_value=NS(id=99))
        client = MockClient()
        client.send_message = AsyncMock()
        client.get_me = AsyncMock(return_value=NS(id=99))
        ns['client'] = client
        ns['log'] = NS(warning=lambda *a: None, exception=lambda *a: None)

    async def test_second_leader_thumbsup_reaction_advances_to_final(self):
        rec = {
            'org_unit': '技术中心', 'stage': 'waiting_second_review',
            'offer_confirm_msg_id': 10, 'second_review_msg_id': 20,
            'approvals': {'first': {'message_id': 15, 'sender_id': 1}},
        }
        ns['state'] = Store({'里昂': rec})
        message = NS(id=20, sender_id=99, raw_text='@second_user 初审已通过，请领导二级审批，谢谢')
        ns['client'].get_messages = AsyncMock(return_value=message)
        second_leader = NS(id=2, username='second_user')
        other_member = NS(id=3, username='unrelated_member')
        ns['client'].call_mock = AsyncMock(return_value=reactions_result(other_member, second_leader))

        await ns['process_leadership_reaction'](NS(peer=NS(), msg_id=20))

        self.assertIn('second', rec['approvals'])
        self.assertEqual(rec['approvals']['second']['sender_id'], 2)
        call = ns['queue_group_message'].call_args
        self.assertIn('终审', call.args[1])
        self.assertEqual(call.kwargs['reply_to'], 10)

    async def test_unrelated_member_reaction_is_ignored(self):
        rec = {
            'org_unit': '技术中心', 'stage': 'waiting_second_review',
            'offer_confirm_msg_id': 10, 'second_review_msg_id': 20,
            'approvals': {'first': {'message_id': 15, 'sender_id': 1}},
        }
        ns['state'] = Store({'里昂': rec})
        message = NS(id=20, sender_id=99, raw_text='@second_user 初审已通过，请领导二级审批，谢谢')
        ns['client'].get_messages = AsyncMock(return_value=message)
        other_member = NS(id=3, username='unrelated_member')
        ns['client'].call_mock = AsyncMock(return_value=reactions_result(other_member))

        await ns['process_leadership_reaction'](NS(peer=NS(), msg_id=20))

        self.assertNotIn('second', rec['approvals'])
        ns['queue_group_message'].assert_not_awaited()

    async def test_reaction_on_unrelated_message_is_ignored(self):
        ns['state'] = Store({})
        message = NS(id=999, sender_id=99, raw_text='随便聊聊')
        ns['client'].get_messages = AsyncMock(return_value=message)
        ns['client'].call_mock = AsyncMock()

        await ns['process_leadership_reaction'](NS(peer=NS(), msg_id=999))

        ns['client'].call_mock.assert_not_awaited()

    async def test_excluded_chat_is_ignored(self):
        config.EXCLUDED_CHAT_IDS = frozenset({-123})
        try:
            ns['client'].get_messages = AsyncMock()
            await ns['process_leadership_reaction'](NS(peer=NS(), msg_id=20))
            ns['client'].get_messages.assert_not_awaited()
        finally:
            config.EXCLUDED_CHAT_IDS = frozenset()

    async def test_final_leader_reaction_on_already_approved_second_is_ignored_for_second_role(self):
        # 终审领导误点了二级审批消息上的👌，approval_role应识别不出角色，不应记为二级审批。
        rec = {
            'org_unit': '技术中心', 'stage': 'waiting_second_review',
            'offer_confirm_msg_id': 10, 'second_review_msg_id': 20,
            'approvals': {'first': {'message_id': 15, 'sender_id': 1}},
        }
        ns['state'] = Store({'里昂': rec})
        message = NS(id=20, sender_id=99, raw_text='@second_user 初审已通过，请领导二级审批，谢谢')
        ns['client'].get_messages = AsyncMock(return_value=message)
        final_leader = NS(id=4, username='final_user')
        ns['client'].call_mock = AsyncMock(return_value=reactions_result(final_leader))

        await ns['process_leadership_reaction'](NS(peer=NS(), msg_id=20))

        # final_user是被approval_reactor接受的候选人（在配置的三个领导名单内），
        # 但approval_role按approval_roles(org_unit)过滤后角色对不上二级，不应记账。
        self.assertNotIn('second', rec['approvals'])
        ns['queue_group_message'].assert_not_awaited()


if __name__ == '__main__':
    unittest.main()
