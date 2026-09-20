from unittest import TestCase
from approval_queue import select_pending


class ApprovalQueueTests(TestCase):
    def setUp(self):
        self.items = [dict(draft_id=i, candidate=str(i), status='pending',
                           review_chat_id=99, approval_code=code,
                           expected_stage='review')
                      for i, code in [(10, '测试1'), (20, '测试1'),
                                      (30, '测试2'), (40, '测试3')]]
        self.states = {str(i): {'stage': 'review'} for i in [10, 20, 30, 40]}

    def select(self, code='测试1', event=100, reply=None):
        return select_pending(self.items, self.states, 99, code, event, reply)

    def test_drain_latest_pending_one_per_event_and_ignore_replay(self):
        first = self.select()
        self.assertEqual(first['draft_id'], 20)
        first.update(status='sent', approval_msg_id=100)
        self.assertIsNone(self.select())
        second = self.select(event=101)
        self.assertEqual(second['draft_id'], 10)
        second.update(status='sent', approval_msg_id=101)
        self.assertIsNone(self.select(event=102))

    def test_reply_targets_exact_draft_without_fallback(self):
        self.assertEqual(self.select(reply=10)['draft_id'], 10)
        for reply in [30, 999]:
            self.assertIsNone(self.select(reply=reply))
        self.items[0]['status'] = 'sent'
        self.assertIsNone(self.select(reply=10))

    def test_codes_are_isolated(self):
        self.assertEqual(self.select('测试2')['draft_id'], 30)
        self.assertEqual(self.select('测试3')['draft_id'], 40)
        self.assertIsNone(self.select('1'))

    def test_stale_and_uncertain_items_do_not_block_older_pending(self):
        self.states['20']['stage'] = 'done'
        self.assertEqual(self.select()['draft_id'], 10)
        self.states['20']['stage'] = 'review'
        self.items[1]['status'] = 'sending'
        self.assertEqual(self.select()['draft_id'], 10)

    def test_chat_and_message_boundary(self):
        self.assertIsNone(self.select(event=10))
        self.items[1]['review_chat_id'] = 123
        self.assertEqual(self.select()['draft_id'], 10)
