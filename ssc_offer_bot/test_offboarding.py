import unittest

from offboarding import (
    build_account_reclaim_text,
    classify_offboarding_sections,
    extract_offboarding_contact_tg,
    extract_offboarding_name,
    matches_offboarding_keyword,
)


class KeywordMatchingTests(unittest.TestCase):
    def test_matches_both_keywords(self):
        self.assertTrue(matches_offboarding_keyword("张三 劝退申请"))
        self.assertTrue(matches_offboarding_keyword("李四的离职申请"))

    def test_unrelated_text_does_not_match(self):
        self.assertFalse(matches_offboarding_keyword("今天天气不错"))
        self.assertFalse(matches_offboarding_keyword("离职"))


class NameExtractionTests(unittest.TestCase):
    def test_explicit_name_field_takes_priority(self):
        self.assertEqual(extract_offboarding_name("花名：张三\n劝退申请"), "张三")
        self.assertEqual(extract_offboarding_name("姓名：李四\n离职申请，请核实"), "李四")

    def test_name_after_colon_following_keyword(self):
        self.assertEqual(extract_offboarding_name("劝退申请：王五"), "王五")
        self.assertEqual(extract_offboarding_name("离职申请：赵六，原因：绩效不达标"), "赵六")

    def test_name_immediately_before_keyword(self):
        self.assertEqual(extract_offboarding_name("对张三提出离职申请"), "张三")
        self.assertEqual(extract_offboarding_name("李四的离职申请"), "李四")

    def test_returns_empty_when_no_name_found(self):
        self.assertEqual(extract_offboarding_name("劝退申请"), "")
        self.assertEqual(extract_offboarding_name(""), "")


class SectionClassificationTests(unittest.TestCase):
    def test_classifies_four_known_roles(self):
        sections = [
            ("离职信息确认", "候选人姓名：张三\n编制组织：运营中心"),
            ("薪资结算信息", "应结工资：8000"),
            ("离职信息同步", "编号：HJXL001\n花名：张三"),
            ("账号回收", "回收TG账号：@zhangsan"),
        ]
        by_role, reference = classify_offboarding_sections(sections)
        self.assertEqual(by_role["forward"], ("离职信息确认", "候选人姓名：张三\n编制组织：运营中心"))
        self.assertEqual(by_role["salary"], ("薪资结算信息", "应结工资：8000"))
        self.assertEqual(by_role["sync"], ("离职信息同步", "编号：HJXL001\n花名：张三"))
        self.assertEqual(by_role["account_reclaim"], ("账号回收", "回收TG账号：@zhangsan"))
        self.assertEqual(reference, [])

    def test_unmatched_sections_become_reference_material(self):
        sections = [
            ("离职信息确认", "候选人姓名：张三"),
            ("面试评价", "工作表现一般"),
        ]
        by_role, reference = classify_offboarding_sections(sections)
        self.assertNotIn("salary", by_role)
        self.assertNotIn("sync", by_role)
        self.assertNotIn("account_reclaim", by_role)
        self.assertEqual(reference, [("面试评价", "工作表现一般")])

    def test_sync_section_is_not_misclassified_by_generic_hints(self):
        # "离职信息同步"本身含"息"字，不应被更宽泛的规则抢先命中。
        sections = [("离职信息同步", "编号：HJXL001")]
        by_role, reference = classify_offboarding_sections(sections)
        self.assertEqual(by_role.get("sync"), ("离职信息同步", "编号：HJXL001"))
        self.assertEqual(reference, [])

    def test_empty_body_sections_are_skipped(self):
        sections = [("离职信息确认", ""), ("薪资结算信息", "应结工资：8000")]
        by_role, reference = classify_offboarding_sections(sections)
        self.assertNotIn("forward", by_role)
        self.assertEqual(by_role["salary"], ("薪资结算信息", "应结工资：8000"))


class ContactExtractionTests(unittest.TestCase):
    def test_extracts_from_work_tg_field(self):
        text = "花名：张三\n工作TG：zhangsan_work"
        self.assertEqual(extract_offboarding_contact_tg(text), "@zhangsan_work")

    def test_falls_back_to_contact_field_with_at_prefix_kept(self):
        text = "候选人联系方式：@zhangsan88"
        self.assertEqual(extract_offboarding_contact_tg(text), "@zhangsan88")

    def test_returns_empty_when_no_contact_field(self):
        self.assertEqual(extract_offboarding_contact_tg("花名：张三"), "")


class BuildAccountReclaimTextTests(unittest.TestCase):
    def test_uses_known_fields(self):
        fields = {"编制组织": "运营中心", "编号": "HJXL00076", "花名": "方清屿"}
        text = build_account_reclaim_text("方清屿", fields, today="2026-09-24")
        expected = (
            "【员工帐号回收】\n\n"
            "申请日期：2026-09-24\n"
            "编制组织：运营中心\n"
            "编号：HJXL00076\n"
            "花名：方清屿\n"
            "需求：回收该员工的工作帐号/TG号/工作邮箱\n"
            "申请原因：员工离职"
        )
        self.assertEqual(text, expected)

    def test_missing_fields_fall_back_to_placeholder_or_name(self):
        text = build_account_reclaim_text("张三", {}, today="2026-09-24")
        self.assertIn("编制组织：待补充", text)
        self.assertIn("编号：待补充", text)
        self.assertIn("花名：张三", text)


if __name__ == '__main__':
    unittest.main()
