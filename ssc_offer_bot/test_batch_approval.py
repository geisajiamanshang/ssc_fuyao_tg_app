from types import SimpleNamespace as NS
from unittest import TestCase
from batch_approval import is_batch_approval, missing_approvals, recover_approvals
from parsers import is_approval


class BatchTests(TestCase):
    def test_trigger(self):
        for text in ['以上 OK', '以上👌', '以上ok']:
            self.assertTrue(is_batch_approval(text))
        for text in ['OK', '以上不OK', '以上OK但需要修改']:
            self.assertFalse(is_batch_approval(text))

    def test_non_tech_needs_only_first(self):
        self.assertEqual(missing_approvals(dict(org_unit='效能中心', first_approved_msg_id=10), ['技术中心']), [])
        self.assertEqual(missing_approvals(dict(org_unit='运营中心'), ['技术中心']), ['first'])

    def test_tech_requires_ordered_approvals(self):
        rec = dict(org_unit='技术中心', first_approved_msg_id=10)
        self.assertEqual(missing_approvals(rec, ['技术中心']), ['second'])
        rec['second_approved_msg_id'] = 9
        self.assertEqual(missing_approvals(rec, ['技术中心']), ['second'])
        rec['second_approved_msg_id'] = 12
        self.assertEqual(missing_approvals(rec, ['技术中心']), [])

    def test_history_requires_correct_leaders_and_second_prompt(self):
        rec = dict(offer_confirm_msg_id=1, second_review_msg_id=5)
        def msg(i, sender, reply):
            return NS(id=i, sender_id=sender, reply_to_msg_id=reply, raw_text='1')
        messages = [msg(2, 9, 1), msg(3, 8, 1), msg(4, 8, 1), msg(6, 8, 1)]
        result = recover_approvals(rec, messages, {8:'leader', 9:'outsider'}, 'leader', 'leader', is_approval)
        self.assertEqual(result['first_approved_msg_id'], 3)
        self.assertEqual(result['second_approved_msg_id'], 6)

    def test_unrelated_or_unthreaded_approval_is_not_evidence(self):
        messages = [NS(id=2, sender_id=8, reply_to_msg_id=None, raw_text='ok')]
        result = recover_approvals(dict(offer_confirm_msg_id=1), messages, {8:'leader'}, 'leader', 'second', is_approval)
        self.assertNotIn('first_approved_msg_id', result)
