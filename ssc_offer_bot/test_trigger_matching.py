from unittest import TestCase

from regularization import trigger_keyword_matches


class TriggerMatchingTests(TestCase):
    def test_accepts_spaces_and_dash_variants(self):
        self.assertTrue(trigger_keyword_matches(
            "转正提醒 — 恒睿 — 转正倒数4天",
            "转正提醒-恒睿-转正倒数4天",
        ))

    def test_rejects_unrelated_text(self):
        self.assertFalse(trigger_keyword_matches(
            "普通测试消息",
            "转正提醒-恒睿-转正倒数4天",
        ))
