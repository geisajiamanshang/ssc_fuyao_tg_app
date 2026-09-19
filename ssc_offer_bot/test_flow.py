import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import unicodedata
from parsers import is_approval

source = Path(__file__).with_name('main.py').read_text()
tree = ast.parse(source)
selected = {'approval_roles', 'role_username', 'approval_role', 'batch_approval',
            'apply_approval_evidence', 'advance_offer', 'process_leadership_reply',
            'notify_missing', 'todays_offer_records', 'recover_approval_evidence', 'approval_target',
            'matches_recruit_candidate', 'get_leader_tags'}
config = NS(LEADER_FIRST='first_user', LEADER_SECOND_TECH='second_user',
            LEADER_FINAL='final_user', DAILY_REPORT_TIMEZONE='Asia/Shanghai',
            GROUP_LEADERSHIP=-123)
ns = dict(config=config, unicodedata=unicodedata, is_approval=is_approval,
          ZoneInfo=ZoneInfo)
exec(compile(ast.Module(body=[n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in selected], type_ignores=[]), '<flow>', 'exec'), ns)
real_target=ns['approval_target']
real_today=ns['todays_offer_records']
real_recover=ns['recover_approval_evidence']
from parsers import parse_kv_fields, get_field, offer_header_org
ns.update(parse_kv_fields=parse_kv_fields,get_field=get_field,offer_header_org=offer_header_org)

class Store:
    def __init__(self, data): self.data=data
    def get(self,k): return self.data.get(k)
    def update(self,k,**v): self.data[k].update(v)
    def all(self): return self.data
    def find_by_field(self,key,value):
        return next(((n,r) for n,r in self.data.items() if r.get(key)==value),(None,None))

class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        ns['approval_target']=real_target
        ns['queue_group_message']=AsyncMock()
        ns['handle_final_approved']=AsyncMock()
        ns['get_ssc_reviewer']=AsyncMock(return_value=NS(id=99))
        ns['client']=NS(send_message=AsyncMock())
        ns['log']=NS(warning=lambda *a: None, exception=lambda *a: None)

    def test_role_paths(self):
        self.assertEqual(ns['approval_roles']('技术中心'), ['first','second','final'])
        self.assertEqual(ns['approval_roles']('效能中心'), ['first','final'])

    def test_resume_requires_code_and_exact_identity(self):
        match = ns['matches_recruit_candidate']
        self.assertFalse(match('候选人姓名：小仙', '小仙'))
        self.assertTrue(match('候选人编码：A1\n简历名：小仙', '小仙'))
        self.assertFalse(match('候选人编码：B2\n简历名：小仙', '小仙', 'A1'))

    def test_recruiter_candidate_disambiguation(self):
        from state_store import StateStore
        store = StateStore.__new__(StateStore)
        store.data = {n: dict(stage='waiting_recruiter_dm', recruiter_id=8,
                            raw_fields={'候选人编码': c}) for n,c in [('林舟','A1'),('小仙','B2')]}
        self.assertEqual(store.find_pending_for_recruiter('', '招聘信息\n候选人编码：B2', 8)[0], '小仙')
        self.assertEqual(store.find_pending_for_recruiter('', '招聘信息', 8), (None,None))
        self.assertEqual(store.find_pending_for_recruiter('', '候选人编码：B2', 9), (None,None))
        self.assertEqual(store.find_pending_for_recruiter('', '候选人编码：C3', 8), (None,None))

    def test_template_fields_and_evaluation(self):
        from templates import build_onboarding_confirm_message, build_recruit_reply_message
        original='运营中心【offer信息确认】\n候选人姓名：小仙\n入职部门：运营1部\n#面试评价：\n原始评价\n主要面试官：结城'
        result=build_onboarding_confirm_message('运营中心', {'入职部门':'运营2部','入职日期':'2026-09-20'}, ['leader'], original)
        self.assertIn('入职部门：运营2部',result)
        self.assertIn('#面试评价：\n原始评价\n主要面试官：结城',result)
        self.assertIn('入职日期：2026-09-20',result)
        self.assertIn('试用期：3个月',build_recruit_reply_message('小仙','运营','16K','12K','hr','bp','3个月'))

    def test_effect_leaders_and_combined_department(self):
        config.DEPARTMENT_LEADER_TAGS=[
            {'org_unit':'效能中心','dept_keywords':[''],'leaders':['DaBai10010','chuqianyiding','wean4790']},
            {'org_unit':'技术中心','dept_keywords':['前端组'],'leaders':['wdz999']}]
        self.assertEqual(ns['get_leader_tags']('效能中心',''),['DaBai10010','chuqianyiding','Nicky_lam','wean4790'])
        self.assertEqual(ns['get_leader_tags']('技术中心-前端组',''),['wdz999'])

    async def test_unthreaded_single_approval_is_not_guessed(self):
        ns['client'].get_me=AsyncMock(return_value=NS(id=99))
        self.assertEqual(await ns['approval_target'](NS(message=NS(reply_to_msg_id=None))), (None,None))

    def test_approval_phrases(self):
        for text in ['以上OK','以上👌','以上 👌🏻']:
            self.assertTrue(ns['batch_approval'](text))
        for text in ['以上不OK','以上OK但需要修改','好的']:
            self.assertFalse(ns['batch_approval'](text))

    def test_missing_and_order(self):
        rec={'org_unit':'技术中心'}
        missing,changed=ns['apply_approval_evidence'](rec,'final',30,3)
        self.assertEqual(missing,['first','second']);self.assertFalse(changed)
        ns['apply_approval_evidence'](rec,'first',10,1)
        self.assertEqual(ns['apply_approval_evidence'](rec,'final',30,3)[0],['second'])
        ns['apply_approval_evidence'](rec,'second',20,2)
        self.assertTrue(ns['apply_approval_evidence'](rec,'final',30,3)[1])
        self.assertFalse(ns['apply_approval_evidence'](rec,'final',30,3)[1])
        self.assertEqual(ns['apply_approval_evidence']({'org_unit':'运营中心','approvals':{'first':{'message_id':50}}},'final',40,3)[0],['first'])

    async def test_a_b_continue_c_warn(self):
        data={name:{'org_unit':'运营中心','stage':'waiting_final_review',
                    'offer_confirm_msg_id':i,'approvals':({'first':{'message_id':10,'sender_id':1}} if name!='C' else {})}
              for name,i in [('A',1),('B',2),('C',3)]}
        ns['state']=Store(data)
        ns['todays_offer_records']=AsyncMock(return_value=list(data.items()))
        ns['recover_approval_evidence']=AsyncMock()
        event=NS(message=NS(id=50,raw_text='好的'),sender_id=3,
                 get_sender=AsyncMock(return_value=NS(username='final_user')))
        for name, rec in data.items():
            ns['approval_target']=AsyncMock(return_value=(name, rec))
            await ns['process_leadership_reply'](event)
        self.assertEqual([c.args[0] for c in ns['handle_final_approved'].call_args_list],['A','B'])
        notice=ns['client'].send_message.call_args.args[1]
        self.assertIn('C-卡在一级',notice)
        self.assertNotIn('final',data['C']['approvals'])
        self.assertEqual(ns['queue_group_message'].await_count,0)

    async def test_first_review_queues_correct_prompt(self):
        for org,expected in [('技术中心','二级审批'),('效能中心','终审')]:
            rec={'org_unit':org,'stage':'sent_to_leadership','offer_confirm_msg_id':12,
                 'approvals':{'first':{'message_id':20,'sender_id':1}}}
            ns['state']=Store({'A':rec})
            await ns['advance_offer']('A',rec)
            call=ns['queue_group_message'].call_args
            self.assertIn(expected,call.args[1]);self.assertEqual(call.kwargs['reply_to'],12)

    def test_unknown_sender(self):
        self.assertIsNone(ns['approval_role'](NS(username='unrelated')))
        self.assertEqual(ns['approval_role'](NS(username='FIRST_USER')),'first')

    async def test_today_before_only(self):
        data={n:{'offer_confirm_msg_id':i,'org_unit':'运营中心'} for n,i in [('today',10),('yesterday',11),('future',60)]}
        ns['state']=Store(data)
        def source(i):
            return NS(id=i,sender_id=99,raw_text='运营中心【offer信息确认】',
                      date=datetime(2026,9,19 if i==10 else 18,1,tzinfo=timezone.utc))
        ns['client'].get_messages=AsyncMock(side_effect=lambda *a,**kw:source(kw['ids']))
        ns['client'].get_me=AsyncMock(return_value=NS(id=99))
        result=await real_today(NS(message=NS(id=50,date=datetime(2026,9,19,2,tzinfo=timezone.utc))))
        self.assertEqual([n for n,r in result],['today'])

    async def test_recover_indirect_reply(self):
        rec={'offer_confirm_msg_id':10,'org_unit':'技术中心'}
        ns['state']=Store({'A':rec})
        original=NS(id=10,sender_id=99,raw_text='技术中心【offer信息确认】',reply_to_msg_id=None)
        first=NS(id=20,sender_id=1,raw_text='好的',reply_to_msg_id=10,
                 get_reply_message=AsyncMock(return_value=original),
                 get_sender=AsyncMock(return_value=NS(username='first_user')))
        second=NS(id=30,sender_id=2,raw_text='👌',reply_to_msg_id=20,
                  get_reply_message=AsyncMock(return_value=first),
                  get_sender=AsyncMock(return_value=NS(username='second_user')))
        async def history(*a,**kw):
            for m in [first,second]: yield m
        ns['client'].iter_messages=history
        ns['client'].get_me=AsyncMock(return_value=NS(id=99))
        await real_recover(NS(message=NS(id=40)), [('A',rec)])
        self.assertEqual(set(rec['approvals']),{'first','second'})
        ns['client'].send_message.assert_not_awaited()

if __name__=='__main__': unittest.main()
