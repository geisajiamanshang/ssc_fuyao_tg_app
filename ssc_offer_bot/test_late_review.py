import ast
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from unittest import IsolatedAsyncioTestCase
import test_flow as flow
from test_flow import ns, tree, Store, config
from templates import build_recruit_reply_message


class LateReviewTests(IsolatedAsyncioTestCase):
    def setUp(self):
        flow.FlowTests.setUp(self)

    async def test_saved_final_then_late_second_queues_recruitment_once(self):
        await self.check_late_review('技术中心', 'second', 'second_user',
                                     {'first':{'message_id':20}})

    async def test_effect_center_late_first_with_shared_test_leader(self):
        original = config.LEADER_SECOND_TECH
        config.LEADER_SECOND_TECH = config.LEADER_FIRST
        try:
            await self.check_late_review('效能中心', 'first', 'first_user', {})
        finally:
            config.LEADER_SECOND_TECH = original

    async def check_late_review(self, org, role, username, previous):
        config.GROUP_RECRUIT = -456
        rec = dict(org_unit=org, stage='waiting_second_review' if role == 'second' else 'sent_to_leadership',
                   offer_confirm_msg_id=10, raw_fields={'候选人编码':'B1'},
                   approvals={**previous,
                              'final':{'message_id':30,'sender_id':3}})
        ns['state'] = Store({'小B':rec})
        ns['approval_target'] = AsyncMock(return_value=('小B',rec))
        ns['recover_approval_evidence'] = AsyncMock()
        ns['build_recruit_reply_message'] = build_recruit_reply_message
        needed = {'handle_final_approved', '_pick_preferred_recruit_message',
                  'matches_recruit_candidate_by_name'}
        nodes = [n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name in needed]
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<flow>','exec'),ns)
        resume = NS(id=70,raw_text='候选人编码：B1\n候选人姓名：小B',
                    get_sender=AsyncMock(return_value=NS(id=8,username='recruiter')))
        async def history(*a,**kw):
            yield resume
        ns['client'].iter_messages = history
        ns['log'].info = lambda *a: None
        async def queue(*args,**kwargs):
            ns['state'].update(kwargs['candidate'],stage=kwargs['expected_stage'])
        ns['queue_group_message'] = AsyncMock(side_effect=queue)
        event = NS(message=NS(id=40,raw_text='好的'),sender_id=2,
                   get_sender=AsyncMock(return_value=NS(username=username)))
        await ns['process_leadership_reply'](event)
        call = ns['queue_group_message'].call_args
        self.assertEqual(call.args[0],config.GROUP_RECRUIT)
        self.assertEqual(call.kwargs['reply_to'],70)
        self.assertEqual(call.kwargs['expected_stage'],'waiting_ssc_recruit_reply')
        self.assertEqual(call.kwargs['updates']['stage'],'waiting_recruiter_dm')
        self.assertEqual(rec['approvals']['final']['message_id'],30)
        self.assertEqual(rec['approvals'][role]['message_id'],40)
        ns['client'].send_message.assert_not_awaited()
        await ns['process_leadership_reply'](event)
        self.assertEqual(ns['queue_group_message'].await_count,1)

    def test_shared_leader_replay_does_not_approve_two_levels(self):
        original = config.LEADER_SECOND_TECH
        config.LEADER_SECOND_TECH = config.LEADER_FIRST
        try:
            sender = NS(username='first_user')
            rec = {'org_unit':'技术中心', 'approvals':{}}
            self.assertEqual(ns['approval_role'](sender, rec, 20), 'first')
            ns['apply_approval_evidence'](rec, 'first', 20, 1)
            self.assertEqual(ns['approval_role'](sender, rec, 20), 'first')
            self.assertEqual(ns['approval_role'](sender, rec, 21), 'second')
        finally:
            config.LEADER_SECOND_TECH = original
