from unittest import TestCase

from regularization import regularization_trigger_scope, trigger_keyword_matches


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

    def test_matches_real_grouped_message_and_scopes_to_target_company(self):
        message = """📋 转正提醒 · 2026-09-18

【其他公司】
转正倒数4天：
其他甲（X001）转正日期：2026-09-22

【恒睿】
转正倒数4天：
测试甲（X002）转正日期：2026-09-22

转正倒数2天：
测试乙（X003）转正日期：2026-09-20

【其他公司二】
转正倒数4天：
其他乙（X004）转正日期：2026-09-22
"""
        self.assertTrue(trigger_keyword_matches(
            message, "转正提醒-恒睿-转正倒数4天"
        ))
        scope = regularization_trigger_scope(
            message, "转正提醒-恒睿-转正倒数4天"
        )
        self.assertIn("测试甲", scope)
        self.assertNotIn("测试乙", scope)
        self.assertNotIn("其他甲", scope)

    def test_grouped_message_without_four_day_target_does_not_match(self):
        message = """转正提醒 · 2026-09-18
【恒睿】
转正倒数3天：
测试甲（X002）转正日期：2026-09-21
"""
        self.assertFalse(trigger_keyword_matches(
            message, "转正提醒-恒睿-转正倒数4天"
        ))
