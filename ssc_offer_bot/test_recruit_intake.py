import ast
import asyncio
import copy
import random
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
        # on_private_message/retry_onboarding_confirmations还要用到
        # config.GROUP_RECRUIT和config.EXCLUDED_CHAT_IDS，flow.config没有
        # 这两个字段；这里换一份本地的config，不去改共享的flow.config，
        # 避免影响其它引用flow.ns的测试文件。
        self.ns['config'] = NS(GROUP_LEADERSHIP=flow.config.GROUP_LEADERSHIP,
                                GROUP_RECRUIT=-777, EXCLUDED_CHAT_IDS=frozenset())
        nodes = [copy.deepcopy(n) for n in flow.tree.body if isinstance(n, ast.AsyncFunctionDef)
                 and n.name in {'on_private_message','replay_pending_recruiter_dm',
                                 'retry_recruit_notifications','retry_onboarding_confirmations',
                                 'find_and_replay_recruiter_dm','generate_onboarding_confirmation',
                                 'on_ssc_favorites_candidate_info'}]
        for node in nodes:
            node.decorator_list = []
        self.ns['asyncio'] = asyncio
        self.ns['random'] = random
        # 招聘私聊我发候选人信息时会顺带点个表情确认收到，这个功能有自己
        # 独立的测试文件(test_recruit_private_sent_reaction.py)，这里只
        # 关心私聊信息合并这一件事，用AsyncMock占位，不拉入真实实现。
        self.ns['_send_delayed_reaction'] = AsyncMock()
        # on_ssc_favorites_candidate_info引用的两个模块级常量。
        self.ns['CANDIDATE_INFO_SECTION_MARKERS'] = ("3️⃣招聘信息", "4️⃣入职信息")
        self.ns['BOT_OWN_DRAFT_MARKERS'] = ("【入职信息确认】", "【offer信息确认】", "【员工账号申请】")
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
        self.event = NS(is_private=True,raw_text=self.text,message=NS(id=90),chat_id=8,
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
        event = NS(is_private=True, raw_text=text, message=NS(id=91), chat_id=8,
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
        self.ns['client'].get_messages = AsyncMock(return_value=NS(raw_text=self.text, id=90,
                   get_sender=self.event.get_sender))
        await self.ns['replay_pending_recruiter_dm']('小C')
        self.ns['queue_group_message'].assert_awaited_once()
        self.assertIsNone(self.rec['pending_recruiter_dm'])

    async def test_missing_resume_stage_notifies_ssc(self):
        self.rec['stage'] = 'final_approved_no_resume_found'
        await self.ns['on_private_message'](self.event)
        self.ns['queue_group_message'].assert_not_awaited()
        self.assertIn('final_approved_no_resume_found',self.ns['client'].send_message.call_args.args[1])

    async def test_generation_failure_keeps_pending_dm_for_retry(self):
        # 真实事故：部门领导名单没配置（比如新部门"AIGC原创部"），入职确认
        # 生成失败；这条私聊消息不能丢，要留着给"重试入职确认"用。
        self.ns['get_leader_tags'] = lambda *a: []
        await self.ns['on_private_message'](self.event)
        self.ns['queue_group_message'].assert_not_awaited()
        self.assertEqual(self.rec['stage'], 'waiting_recruiter_dm')
        self.assertEqual(self.rec['pending_recruiter_dm']['message_id'], 90)
        notice = self.ns['client'].send_message.call_args.args[1]
        self.assertIn('未匹配通知名单', notice)
        self.assertIn('重试入职确认', notice)

    async def test_retry_onboarding_confirmations_regenerates_after_config_fixed(self):
        # 第一次因为部门领导名单未配置失败，记录卡在waiting_recruiter_dm，
        # 招聘那条私聊消息记录成了pending_recruiter_dm。
        self.ns['get_leader_tags'] = lambda *a: []
        await self.ns['on_private_message'](self.event)
        self.assertEqual(self.rec['pending_recruiter_dm']['message_id'], 90)
        self.ns['queue_group_message'].assert_not_awaited()
        # 补上部门领导配置后，SSC在收藏夹发"重试入职确认"，不用麻烦招聘重发。
        self.ns['get_leader_tags'] = lambda *a: ['leader']
        self.ns['client'].get_me = AsyncMock(return_value=NS(id=99))
        self.ns['client'].get_messages = AsyncMock(return_value=NS(raw_text=self.text, id=90,
                   get_sender=self.event.get_sender))
        retry_event = NS(chat_id=99, raw_text='重试入职确认', is_private=True, sender_id=99)
        await self.ns['retry_onboarding_confirmations'](retry_event)
        self.ns['queue_group_message'].assert_awaited_once()
        self.assertIsNone(self.rec['pending_recruiter_dm'])

    async def test_retry_onboarding_confirmations_skips_candidates_without_pending_dm(self):
        # 还没收到过招聘私聊补充信息的候选人（没有pending_recruiter_dm）
        # 不应该被"重试入职确认"误触发。
        self.ns['client'].get_me = AsyncMock(return_value=NS(id=99))
        retry_event = NS(chat_id=99, raw_text='重试入职确认', is_private=True, sender_id=99)
        await self.ns['retry_onboarding_confirmations'](retry_event)
        self.ns['queue_group_message'].assert_not_awaited()

    async def test_ssc_favorites_paste_with_section_markers_generates_confirmation(self):
        # SSC不等招聘私聊，直接把候选人信息转发/粘贴到自己收藏夹里，带
        # "3️⃣招聘信息"/"4️⃣入职信息"编号小标题，效果应该跟招聘私聊我一样。
        self.ns['client'].get_me = AsyncMock(return_value=NS(id=99))
        event = NS(chat_id=99, sender_id=99, is_private=True, raw_text=self.text,
                   message=NS(id=200))
        await self.ns['on_ssc_favorites_candidate_info'](event)
        call = self.ns['queue_group_message'].call_args
        self.assertIn('效能中心【入职信息确认】', call.args[1])
        self.assertIn('简历来源：齐夏', call.args[1])
        self.assertEqual(call.kwargs['expected_stage'], 'waiting_ssc_onboarding')

    async def test_ssc_favorites_ignores_own_generated_draft(self):
        # 防止机器人自己发到收藏夹的【入职信息确认】草稿被当成新的候选人
        # 信息再处理一遍——即使碰巧也带了编号小标题，只要出现方括号标题
        # 就一律不当作新输入。
        self.ns['client'].get_me = AsyncMock(return_value=NS(id=99))
        text = self.text + '\n效能中心【入职信息确认】'
        event = NS(chat_id=99, sender_id=99, is_private=True, raw_text=text,
                   message=NS(id=201))
        await self.ns['on_ssc_favorites_candidate_info'](event)
        self.ns['queue_group_message'].assert_not_awaited()

    async def test_ssc_favorites_ignores_text_without_section_markers(self):
        # 没有"3️⃣"/"4️⃣"编号小标题的普通收藏夹消息（比如审批码、其它闲聊）
        # 不应该被误当成候选人信息，哪怕碰巧提到了候选人姓名。
        self.ns['client'].get_me = AsyncMock(return_value=NS(id=99))
        event = NS(chat_id=99, sender_id=99, is_private=True, raw_text='小C的事情稍后处理',
                   message=NS(id=202))
        await self.ns['on_ssc_favorites_candidate_info'](event)
        self.ns['queue_group_message'].assert_not_awaited()

    async def test_ssc_favorites_ignores_when_not_from_self(self):
        # 只认SSC自己发到自己收藏夹的消息；不是私聊自己（比如真的是招聘
        # 私聊过来）的不归这个入口管，走on_private_message。
        self.ns['client'].get_me = AsyncMock(return_value=NS(id=99))
        event = NS(chat_id=8, sender_id=8, is_private=True, raw_text=self.text,
                   message=NS(id=203))
        await self.ns['on_ssc_favorites_candidate_info'](event)
        self.ns['queue_group_message'].assert_not_awaited()

    async def test_ssc_favorites_ignores_candidate_not_waiting_for_dm(self):
        # 候选人还没进入waiting_recruiter_dm（比如终审还没通过）时，收藏夹
        # 里提前出现的候选人信息不应该被处理。
        self.rec['stage'] = 'waiting_final_review'
        self.ns['client'].get_me = AsyncMock(return_value=NS(id=99))
        event = NS(chat_id=99, sender_id=99, is_private=True, raw_text=self.text,
                   message=NS(id=204))
        await self.ns['on_ssc_favorites_candidate_info'](event)
        self.ns['queue_group_message'].assert_not_awaited()

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
