from unittest import TestCase

from regularization import (
    department_for_name,
    extract_today_trigger_scope,
    greeting_for_name,
    match_department_group,
    names_from_trigger,
    split_sections,
    today_trigger_matches,
    today_trigger_scope,
)


GROUPED_MESSAGE = """📋 转正提醒 · 2026-09-21

【其他公司】
今日转正：
其他甲（X001）转正日期：2026-09-21

【恒睿】
转正倒数4天：
测试乙（X003）转正日期：2026-09-25

今日转正：
比尔（YY1940）转正日期：2026-09-21

【其他公司二】
今日转正：
其他乙（X004）转正日期：2026-09-21
"""

# 摘自 2026 年 9 月真实转正信息文件的三段，字段与真实数据一致。
MONTHLY_TEXT = """【转正信息同步】

————

北斗矩阵：恒睿
部门-小组：ACFAN特战队-品牌组
编号：YY1937
花名：三风
岗位：运营专员
入职日期：2026-07-11
转正日期：2026-09-11
直属上级/BP评估：同意按期转正
试用期职级：P2
转正职级：P2

————

北斗矩阵：恒睿
部门-小组：AIGC原创部-AIGC原创组
编号：YY1940
花名：比尔
岗位：运营专员
入职日期：2026-07-21
转正日期：2026-09-21
直属上级/BP评估：同意按期转正
试用期职级：P3
转正职级：P3

【转正通知】

————

🆗️祝贺 三风 @sanfeng279，表现优秀，通过试用期考核评估，于2026-09-11 起正式转正。
愿你在未来的工作中继续保持热忱，持续成长，共创更多价值！

恭喜转正，未来可期！👏👏👏

————

🆗️祝贺 比尔 @guzhi2099，表现优秀，通过试用期考核评估，于2026-09-21 起正式转正。
愿你在未来的工作中继续保持热忱，持续成长，共创更多价值！

恭喜转正，未来可期！👏👏👏
"""

GROUP_RULES = [
    {"name": "测试-ACFAN", "keywords": ["ACFAN特战队", "ACFAN", "AIGC原创部", "AIGC"], "chat_id": -5375721803},
    {"name": "测试-运营一部", "keywords": ["运营一部", "运营1部"], "chat_id": -5479404347},
]


class TodayTriggerScopeTests(TestCase):
    def test_matches_keyword_and_scopes_to_target_company(self):
        self.assertTrue(today_trigger_matches(GROUPED_MESSAGE, "转正提醒-恒睿-今日转正"))
        scope = today_trigger_scope(GROUPED_MESSAGE, "转正提醒-恒睿-今日转正")
        self.assertIn("比尔", scope)
        self.assertNotIn("测试乙", scope)
        self.assertNotIn("其他甲", scope)
        self.assertNotIn("其他乙", scope)

    def test_does_not_match_when_no_today_block(self):
        message = "【恒睿】\n转正倒数4天：\n测试乙（X003）转正日期：2026-09-25\n"
        self.assertFalse(today_trigger_matches(message, "转正提醒-恒睿-今日转正"))
        self.assertEqual(extract_today_trigger_scope(message), "")

    def test_names_from_trigger_reused_for_today_scope(self):
        scope = today_trigger_scope(GROUPED_MESSAGE, "转正提醒-恒睿-今日转正")
        sections = split_sections(MONTHLY_TEXT)
        names = names_from_trigger(scope, sections["转正信息同步"])
        self.assertEqual(names, ["比尔"])


class GreetingAndDepartmentTests(TestCase):
    def setUp(self):
        self.sections = split_sections(MONTHLY_TEXT)

    def test_greeting_for_name_matches_real_notice_format(self):
        greeting = greeting_for_name(self.sections["转正通知"], "比尔")
        self.assertTrue(greeting.startswith("祝贺 比尔 @guzhi2099"))
        self.assertNotIn("🆗️", greeting)
        self.assertIn("2026-09-21", greeting)
        self.assertNotIn("三风", greeting)

    def test_greeting_without_leading_symbol_is_unchanged(self):
        section = "祝贺 善知 @shanzhi_2222，表现优秀，通过试用期考核评估，于2026-09-06 起正式转正。\n恭喜转正，未来可期！👏👏👏"
        greeting = greeting_for_name(section, "善知")
        self.assertTrue(greeting.startswith("祝贺 善知 @shanzhi_2222"))

    def test_department_for_name_reads_real_sync_field(self):
        self.assertEqual(
            department_for_name(self.sections["转正信息同步"], "比尔"),
            "AIGC原创部-AIGC原创组",
        )
        self.assertEqual(
            department_for_name(self.sections["转正信息同步"], "三风"),
            "ACFAN特战队-品牌组",
        )

    def test_department_for_unknown_name_is_empty(self):
        self.assertEqual(department_for_name(self.sections["转正信息同步"], "不存在"), "")


class MatchDepartmentGroupTests(TestCase):
    def test_aigc_department_routes_to_acfan_group(self):
        self.assertEqual(
            match_department_group("AIGC原创部-AIGC原创组", GROUP_RULES),
            -5375721803,
        )

    def test_acfan_department_routes_to_acfan_group(self):
        self.assertEqual(
            match_department_group("ACFAN特战队-品牌组", GROUP_RULES),
            -5375721803,
        )

    def test_unmatched_department_returns_none(self):
        self.assertIsNone(match_department_group("技术中心-研发部", GROUP_RULES))

    def test_empty_department_returns_none(self):
        self.assertIsNone(match_department_group("", GROUP_RULES))
