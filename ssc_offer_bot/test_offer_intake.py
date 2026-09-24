import ast
import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace as NS
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock

from parsers import (mentions_ssc, is_offer_message, parse_kv_fields,
                     get_field, offer_header_org, strip_header_footer,
                     fix_swapped_onboarding_date_contact)


class StripHeaderFooterTests(TestCase):
    def test_strips_bare_offer_plus_resume_line(self):
        # BP转发时常见把"技术中心【offer信息确认】"和"Offer+附件简历："分成
        # 两行，后者以前没有【】括号包裹，不会被旧正则识别，会原样残留在
        # 转发到联合管理群的消息里。
        text = "技术中心【offer信息确认】\nOffer+附件简历：\n候选人编码：WTQA00027\n候选人姓名：muli"
        self.assertEqual(strip_header_footer(text), "候选人编码：WTQA00027\n候选人姓名：muli")

    def test_strips_bracketed_offer_plus_resume_line(self):
        text = "【Offer】+附件简历：\n候选人编码：A1\n候选人姓名：小仙"
        self.assertEqual(strip_header_footer(text), "候选人编码：A1\n候选人姓名：小仙")

    def test_strips_offer_application_bracket_header(self):
        text = "【Offer申请】\n候选人编码：A1\n候选人姓名：小仙"
        self.assertEqual(strip_header_footer(text), "候选人编码：A1\n候选人姓名：小仙")

    def test_strips_offer_application_bracket_header_with_space(self):
        text = "【Offer 申请】\n候选人编码：A1\n候选人姓名：小仙"
        self.assertEqual(strip_header_footer(text), "候选人编码：A1\n候选人姓名：小仙")

    def test_body_without_any_header_is_unchanged(self):
        text = "候选人编码：A1\n候选人姓名：小仙"
        self.assertEqual(strip_header_footer(text), text)

    def test_strips_bp_footer_without_shenpi_suffix(self):
        # BP原文常见"@oiyr90557 麻烦跟进offer"，没有"审批"两个字，旧正则要求
        # 必须以"审批"结尾，匹配不上，会跟机器人新加的"请领导审批，谢谢"重复出现。
        text = "候选人编码：A1\n候选人姓名：小仙\n\n@oiyr90557 麻烦跟进offer"
        self.assertEqual(strip_header_footer(text), "候选人编码：A1\n候选人姓名：小仙")

    def test_still_strips_bp_footer_with_shenpi_suffix(self):
        text = "候选人编码：A1\n候选人姓名：小仙\n\n@oiyr90557 麻烦跟进offer审批"
        self.assertEqual(strip_header_footer(text), "候选人编码：A1\n候选人姓名：小仙")


class SwappedDateContactTests(TestCase):
    def test_swaps_when_date_and_contact_are_reversed(self):
        fields = {"入职日期": "@dashit88", "候选人联系方式": "2026.10.08"}
        fixed = fix_swapped_onboarding_date_contact(fields)
        self.assertEqual(fixed["入职日期"], "2026.10.08")
        self.assertEqual(fixed["候选人联系方式"], "@dashit88")

    def test_leaves_correct_order_unchanged(self):
        fields = {"入职日期": "2026.10.08", "候选人联系方式": "@dashit88"}
        self.assertEqual(fix_swapped_onboarding_date_contact(fields), fields)

    def test_leaves_ambiguous_values_unchanged(self):
        # 手机号不算"日期样式"也不算"@开头"，格式拿不准时不瞎改。
        fields = {"入职日期": "9/16", "候选人联系方式": "13800001111"}
        self.assertEqual(fix_swapped_onboarding_date_contact(fields), fields)

    def test_missing_fields_are_left_alone(self):
        self.assertEqual(fix_swapped_onboarding_date_contact({}), {})
        self.assertEqual(fix_swapped_onboarding_date_contact({"入职日期": "2026.10.08"}),
                          {"入职日期": "2026.10.08"})


class MentionTests(TestCase):
    def test_missing_flag_still_accepts_exact_username(self):
        for text in ['@ffuuyao 请审批', '@FFUUYAO', '请@ffuuyao审批']:
            self.assertTrue(mentions_ssc(NS(raw_text=text)))
        for text in ['@ffuuyao_other', '@other', '小A 小B 小C']:
            self.assertFalse(mentions_ssc(NS(raw_text=text)))

    def test_legacy_oiyr90557_tag_still_accepted(self):
        # 旧版 Offer 模板仍在用 @oiyr90557（早期把 API 应用短名称误当成机器人
        # 用户名留下的标签），未同步更新的 BP 模板不应导致 Offer 被静默丢弃。
        for text in ['@oiyr90557 麻烦跟进offer', '@OIYR90557', '请@oiyr90557审批']:
            self.assertTrue(mentions_ssc(NS(raw_text=text)))
        for text in ['@oiyr90557_other', '@oiyr905570']:
            self.assertFalse(mentions_ssc(NS(raw_text=text)))

    def test_id_mention_and_flag(self):
        self.assertFalse(mentions_ssc(NS(mentioned=True)))
        self.assertTrue(mentions_ssc(NS(entities=[NS(user_id=8853414240)])))
        self.assertFalse(mentions_ssc(NS(entities=[NS(user_id=8)])))


class MemoryStore:
    def __init__(self):
        self.data = {}

    def find_by_field(self, field, value):
        return next(((key, rec) for key, rec in self.data.items()
                     if rec.get(field) == value), (None, None))

    def set(self, key, value):
        self.data[key] = value

    def update(self, key, **values):
        self.data[key].update(values)


class IntakeTests(IsolatedAsyncioTestCase):
    async def test_three_concurrent_offers_create_three_saved_drafts(self):
        # 执行真实处理函数和入队函数，隔离Telegram连接及磁盘副作用。
        source = ast.parse(Path(__file__).with_name('main.py').read_text())
        functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                     and n.name in {'queue_group_message', 'on_hrbp_offer'}]
        for node in functions:
            node.decorator_list = []
        saved = []

        async def send_message(destination, text, **kwargs):
            saved.append((destination, text))
            return NS(id=100 + len(saved))

        me = NS(id=9, username='ffuuyao')
        state, outbox = MemoryStore(), MemoryStore()
        env = dict(globals(), client=NS(get_me=AsyncMock(return_value=me),
                                       send_message=send_message),
                   state=state, outbox=outbox, ssc_send_lock=asyncio.Lock(),
                   get_ssc_reviewer=AsyncMock(return_value=me),
                   log=logging.getLogger('test'),
                   build_offer_confirm_message=lambda org, body: org + '\n' + body,
                   config=NS(GROUP_LEADERSHIP=-1, ALLOWED_DESTINATION_IDS={-1},
                             OFFER_APPROVAL_CODE='测试1', ENVIRONMENT='test',
                             EXCLUDED_CHAT_IDS=frozenset()))
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
        events = [NS(message=NS(id=i, mentioned=False, media=None,
                               raw_text=f'【Offer】+附件简历\n候选人姓名：小{name}\n入职编制组织：技术中心\n@ffuuyao 请审批'),
                     chat_id=-2, sender_id=8, get_sender=AsyncMock(return_value=NS(username='bp')))
                  for i, name in enumerate('ABC', 1)]
        await asyncio.gather(*(env['on_hrbp_offer'](event) for event in events))
        self.assertEqual(len(saved), 3)
        self.assertEqual({dest for dest, _ in saved}, {9})
        self.assertEqual({r['candidate'] for r in outbox.data.values()}, {'小A', '小B', '小C'})
        self.assertTrue(all(r['status'] == 'pending' for r in outbox.data.values()))

        await asyncio.gather(*(env['on_hrbp_offer'](event) for event in events))
        self.assertEqual(len(saved), 3)

    async def test_legacy_template_with_oiyr90557_tag_still_reaches_ssc(self):
        # 复现生产事故：BP 用了仍标注旧版 @oiyr90557 的【Offer 申请】模板，
        # 消息在修复前会被 mentions_ssc 静默拒绝，Offer 永远进不到下一步。
        source = ast.parse(Path(__file__).with_name('main.py').read_text())
        functions = [n for n in source.body if isinstance(n, ast.AsyncFunctionDef)
                     and n.name in {'queue_group_message', 'on_hrbp_offer'}]
        for node in functions:
            node.decorator_list = []
        saved = []

        async def send_message(destination, text, **kwargs):
            saved.append((destination, text))
            return NS(id=200 + len(saved))

        me = NS(id=9, username='ffuuyao')
        state, outbox = MemoryStore(), MemoryStore()
        env = dict(globals(), client=NS(get_me=AsyncMock(return_value=me),
                                       send_message=send_message),
                   state=state, outbox=outbox, ssc_send_lock=asyncio.Lock(),
                   get_ssc_reviewer=AsyncMock(return_value=me),
                   log=logging.getLogger('test'),
                   build_offer_confirm_message=lambda org, body: org + '\n' + body,
                   config=NS(GROUP_LEADERSHIP=-1, ALLOWED_DESTINATION_IDS={-1},
                             OFFER_APPROVAL_CODE='测试1', ENVIRONMENT='test',
                             EXCLUDED_CHAT_IDS=frozenset()))
        exec(compile(ast.Module(body=functions, type_ignores=[]), 'main.py', 'exec'), env)
        raw_text = (
            '【Offer 申请】\n'
            '候选人编码：LYSNZ000060\n'
            '候选人姓名：Nancy\n'
            '性别：女\n'
            '入职编制组织：运营中心\n'
            '职位：运营专员\n'
            '转正薪资：15K\n'
            '试用薪资：12K\n'
            '@oiyr90557 麻烦跟进offer'
        )
        event = NS(message=NS(id=1, mentioned=False, media=None, raw_text=raw_text),
                   chat_id=-2, sender_id=8, get_sender=AsyncMock(return_value=NS(username='bp')))
        await env['on_hrbp_offer'](event)
        self.assertEqual(len(saved), 1)
        self.assertEqual({r['candidate'] for r in outbox.data.values()}, {'Nancy'})
