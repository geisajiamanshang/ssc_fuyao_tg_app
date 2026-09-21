from unittest import TestCase

from anniversary import (
    anniversary_destination,
    extract_anniversary_greeting,
    names_from_anniversary_trigger,
    parse_anniversary_fields,
)


INFO = """【入职周年祝贺】
花名：小承
祝贺小承入职一周年！
————
【入职周年祝贺】
花名：江羽
祝贺江羽入职两周年！
"""

ACTUAL_INFO = """【金钟国｜1周年】
祝贺 金钟国 @jzg404

入职满 1 周年，感谢有你！！！

————————————

【王大壮｜7周年】
祝贺 王大壮 @wdz999

入职满 7 周年，感谢有你！！！
"""

RULES = [
    {"keywords": ["ACFAN特战队", "ACFAN"], "chat_id": -1001},
    {"keywords": ["运营一部", "运营1部"], "chat_id": -1002},
    {"keywords": ["技术部", "效能部"], "chat_id": -1003},
]


class AnniversaryParserTests(TestCase):
    def test_extracts_name_and_greeting(self):
        trigger = "入职周年提醒 恒睿\n花名：江羽\n编制组织：恒睿公司\n部门：运营一部"
        self.assertEqual(names_from_anniversary_trigger(trigger, INFO), ["江羽"])
        self.assertIn("祝贺江羽", extract_anniversary_greeting(INFO, "江羽"))

    def test_uses_latest_matching_greeting(self):
        text = INFO + "\n————\n花名：小承\n祝贺小承入职周年，最新版。"
        self.assertIn("最新版", extract_anniversary_greeting(text, "小承"))

    def test_supports_current_heading_format_without_name_field(self):
        trigger = "入职周年提醒 恒睿 金钟国\n编制组织：恒睿公司\n部门：运营一部"
        self.assertEqual(
            names_from_anniversary_trigger(trigger, ACTUAL_INFO), ["金钟国"]
        )
        greeting = extract_anniversary_greeting(ACTUAL_INFO, "金钟国")
        self.assertIn("@jzg404", greeting)
        self.assertTrue(greeting.startswith("祝贺 金钟国"))
        self.assertNotIn("【金钟国｜1周年】", greeting)

    def test_matches_department_group(self):
        trigger = "编制组织：恒睿公司\n部门：技术/效能部"
        destination, fields = anniversary_destination(trigger, RULES)
        self.assertEqual(destination, -1003)
        self.assertEqual(fields["org_unit"], "恒睿公司")

    def test_does_not_guess_without_department(self):
        destination, fields = anniversary_destination("入职周年提醒-恒睿", RULES)
        self.assertIsNone(destination)
        self.assertEqual(parse_anniversary_fields("部门：ACFAN特战队")["department"], "ACFAN特战队")

    def test_falls_back_to_compact_grouped_message_format(self):
        # 云昭机器人的真实分组提醒消息没有独立的“编制组织：/部门：”字段行，
        # 而是把编号和编制组织/部门写在花名后的括号里，用｜分隔。
        trigger = (
            "📋 入职周年提醒 · 2026-09-15\n\n"
            "【恒睿】\n"
            "入职1周年：\n"
            "简言（NX0362｜运营中心/技术效能部）入职日期：2026-09-15\n"
        )
        fields = parse_anniversary_fields(trigger)
        self.assertEqual(fields["org_unit"], "运营中心")
        self.assertEqual(fields["department"], "技术效能部")
        destination, _ = anniversary_destination(trigger, RULES)
        self.assertEqual(destination, -1003)

    def test_compact_format_without_org_prefix_still_routes(self):
        trigger = "简言（NX0362｜ACFAN特战队）入职日期：2026-09-15"
        destination, fields = anniversary_destination(trigger, RULES)
        self.assertEqual(destination, -1001)

    def test_field_lines_take_priority_over_compact_format(self):
        # 独立字段行存在时优先使用，不去解析括号里的内容。
        trigger = "编制组织：恒睿公司\n部门：运营一部\n简言（NX0362｜ACFAN特战队）"
        fields = parse_anniversary_fields(trigger)
        self.assertEqual(fields["org_unit"], "恒睿公司")
        self.assertEqual(fields["department"], "运营一部")
