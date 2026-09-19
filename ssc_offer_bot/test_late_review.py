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
        config.GROUP_RECRUIT = -456
        rec = dict(org_unit='技术中心', stage='waiting_second_review',
                   offer_confirm_msg_id=10, raw_fields={'候选人编码':'B1'},
                   approvals={'first':{'message_id':20},
                              'final':{'message_id':30,'sender_id':3}})
        ns['state'] = Store({'小B':rec})
        ns['approval_target'] = AsyncMock(return_value=('小B',rec))
        ns['recover_approval_evidence'] = AsyncMock()
        ns['build_recruit_reply_message'] = build_recruit_reply_message
        fn = next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef)
                  and n.name == 'handle_final_approved')
        exec(compile(ast.Module(body=[fn],type_ignores=[]),'<flow>','exec'),ns)
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
                   get_sender=AsyncMock(return_value=NS(username='second_user')))
        await ns['process_leadership_reply'](event)
        call = ns['queue_group_message'].call_args
        self.assertEqual(call.args[0],config.GROUP_RECRUIT)
        self.assertEqual(call.kwargs['reply_to'],70)
        self.assertEqual(call.kwargs['expected_stage'],'waiting_ssc_recruit_reply')
        self.assertEqual(call.kwargs['updates']['stage'],'waiting_recruiter_dm')
        self.assertEqual(rec['approvals']['final']['message_id'],30)
        self.assertEqual(rec['approvals']['second']['message_id'],40)
        ns['client'].send_message.assert_not_awaited()
        await ns['process_leadership_reply'](event)
        self.assertEqual(ns['queue_group_message'].await_count,1)
