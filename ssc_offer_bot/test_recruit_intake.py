import ast
import copy
import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
import test_flow as flow
from state_store import StateStore
from templates import build_onboarding_confirm_message
from parsers import fix_swapped_onboarding_date_contact


class RecruitIntakeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        flow.FlowTests.setUp(self)
        self.ns = dict(flow.ns)
        nodes = [copy.deepcopy(n) for n in flow.tree.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'on_private_message','replay_pending_recruiter_dm','retry_recruit_notifications'}]
        for node in nodes:
            node.decorator_list = []
        exec(compile(ast.Module(body=nodes,type_ignores=[]),'<intake>','exec'),self.ns)
        self.ns['log'].info = lambda *a: None
        self.ns['build_onboarding_confirm_message'] = build_onboarding_confirm_message
        self.ns['fix_swapped_onboarding_date_contact'] = fix_swapped_onboarding_date_contact
        self.ns['get_leader_tags'] = lambda *a: ['leader']
        self.store = StateStore.__new__(StateStore)
        self.rec = dict(stage='waiting_recruiter_dm',recruiter_id=8,org_unit='效能中心',
            offer_confirm_msg_id=10,raw_fields={'候选人姓名':'小C','入职编制组织':'效能中心'},
            offer_confirm_text='效能中心【offer信息确认】\n候选人姓名：小C\n入职编制组织：效能中心')
        self.store.data = {'小C':self.rec}
        self.store.update = lambda name,**kw: self.store.data[name].update(kw)
        self.ns['state'] = self.store
        self.ns['outbox'] = flow.Store({})
        self.text = ('3️⃣招聘信息\n招聘渠道：万天招聘部\n简历来源：齐夏\n招聘通道：个人资源\n'
                     '4️⃣入职信息\n候选人姓名：小C\n入职日期：9/16\n候选人联系方式：@example')
        self.event = NS(is_private=True,raw_text=self.text,message=NS(id=90),
                        get_sender=AsyncMock(return_value=NS(id=8,username='recruiter')))

    async def test_screenshot_dm_generates_saved_onboarding_draft(self):
        await self.ns['on_private_message'](self.event)
        call = self.ns['queue_group_message'].call_args
        self.assertIn('效能中心【入职信息确认】',call.args[1])
        self.assertIn('简历来源：齐夏',call.args[1])
        self.assertIn('入职日期：9/16',call.args[1])
        self.assertEqual(call.kwargs['expected_stage'],'waiting_ssc_onboarding')
        self.assertEqual(call.kwargs['reply_to'],10)
        self.ns['client'].send_message.assert_not_awaited()

    async def test_swapped_date_and_contact_in_dm_are_corrected(self):
        text = ('3️⃣招聘信息\n招聘渠道：万天招聘部\n简历来源：齐夏\n招聘通道：个人资源\n'
                '4️⃣入职信息\n候选人姓名：小C\n入职日期：@dashit88\n候选人联系方式：2026.10.08')
        event = NS(is_private=True, raw_text=text, message=NS(id=91),
                   get_sender=AsyncMock(return_value=NS(id=8, username='recruiter')))
        await self.ns['on_private_message'](event)
        call = self.ns['queue_group_message'].call_args
        self.assertIn('入职日期：2026.10.08', call.args[1])
        self.assertIn('候选人联系方式：@dashit88', call.args[1])

    async def test_early_verified_dm_saved_then_replayed(self):
        self.rec['stage'] = 'waiting_ssc_recruit_reply'
        self.ns['outbox'] = flow.Store({'1':dict(candidate='小C',status='pending',
                 updates={'stage':'waiting_recruiter_dm','recruiter_id':8})})
        await self.ns['on_private_message'](self.event)
        self.assertEqual(self.rec['pending_recruiter_dm']['message_id'],90)
        self.ns['queue_group_message'].assert_not_awaited()
        self.rec['stage'] = 'waiting_recruiter_dm'
        self.ns['client'].get_messages = AsyncMock(return_value=NS(raw_text=self.text,
                   get_sender=self.event.get_sender))
        await self.ns['replay_pending_recruiter_dm']('小C')
        self.ns['queue_group_message'].assert_awaited_once()
        self.assertIsNone(self.rec['pending_recruiter_dm'])

    async def test_missing_resume_stage_notifies_ssc(self):
        self.rec['stage'] = 'final_approved_no_resume_found'
        await self.ns['on_private_message'](self.event)
        self.ns['queue_group_message'].assert_not_awaited()
        self.assertIn('final_approved_no_resume_found',self.ns['client'].send_message.call_args.args[1])

    def test_resume_format_and_reused_code(self):
        match = self.ns['matches_recruit_candidate']
        text = '候选人编码 ：\u200eWTTW00101\n候选人姓名：小 A\n简历来源：个人资源'
        self.assertTrue(match(text,'小A','WTTW00101'))
        self.assertFalse(match(text,'小B','WTTW00101'))
        self.assertFalse(match(text,'小A','DIFFERENT'))

    def test_dm_reused_code_also_requires_name(self):
        self.rec['raw_fields']['候选人编码'] = 'SAME'
        self.store.data['小A'] = dict(self.rec,raw_fields={'候选人编码':'SAME'})
        name, _ = self.store.find_pending_for_recruiter('recruiter','候选人编码：SAME\n候选人姓名：小C',8)
        self.assertEqual(name,'小C')
