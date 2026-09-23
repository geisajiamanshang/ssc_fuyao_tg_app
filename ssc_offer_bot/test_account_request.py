import unittest

from account_request import (
    account_request_category,
    build_account_request_text,
    matches_account_request_keyword,
    name_from_direct_text,
    name_from_forward_sender_name,
)


class KeywordMatchingTests(unittest.TestCase):
    def test_matches_all_listed_keywords_and_variants(self):
        for text in ("哥 我这边要申请一个外事号", "老师，这边需要申请一个外事号",
                     "帮我搞个推特号呗", "麻烦申请邮箱一个", "帮忙注册新tg",
                     "注册TG", "给结城申请一个外事号么", "工作账号申请一下",
                     "需要一个工作邮箱", "工作TG号申请下"):
            self.assertTrue(matches_account_request_keyword(text), text)

    def test_unrelated_text_does_not_match(self):
        for text in ("今天天气不错", "帮我看看这份简历", "外事" ):
            self.assertFalse(matches_account_request_keyword(text), text)


class CategoryTests(unittest.TestCase):
    def test_foreign_keyword_maps_to_foreign_category(self):
        self.assertEqual(account_request_category("哥 我这边要申请一个外事号"), "外事")
        self.assertEqual(account_request_category("外事号么"), "外事")

    def test_other_keywords_default_to_work_category(self):
        self.assertEqual(account_request_category("帮我搞个推特号呗"), "工作")
        self.assertEqual(account_request_category("麻烦申请邮箱一个"), "工作")
        self.assertEqual(account_request_category("帮忙注册新tg"), "工作")


class NameExtractionTests(unittest.TestCase):
    def test_forward_sender_name_takes_first_segment(self):
        self.assertEqual(name_from_forward_sender_name("里昂-HRGS-CN"), "里昂")
        self.assertEqual(name_from_forward_sender_name("三风-HRGS-CN"), "三风")
        self.assertEqual(name_from_forward_sender_name("王晓源-HRBD-VN"), "王晓源")

    def test_forward_sender_name_handles_missing_input(self):
        self.assertEqual(name_from_forward_sender_name(""), "")
        self.assertEqual(name_from_forward_sender_name(None), "")

    def test_direct_text_extracts_name_after_wei_gei_bang(self):
        self.assertEqual(name_from_direct_text("就为里昂申请一个外事TG号"), "里昂")
        self.assertEqual(name_from_direct_text("给结城申请一个外事号"), "结城")
        self.assertEqual(name_from_direct_text("帮阿林这边申请一个工作邮箱"), "阿林")

    def test_direct_text_returns_empty_when_no_name_pattern(self):
        self.assertEqual(name_from_direct_text("外事号么"), "")
        self.assertEqual(name_from_direct_text("是的"), "")


class BuildTemplateTests(unittest.TestCase):
    def test_foreign_template_matches_expected_format(self):
        fields = {
            "编制组织": "效能中心", "服务单位": "恒睿", "编号": "NX4325",
            "花名": "廖伊波", "简历名": "廖伊波", "联系TG": "@heather80130",
        }
        text = build_account_request_text("外事", fields, today="2026-09-03")
        expected = (
            "【员工帐号申请】\n\n"
            "申请日期：2026-09-03\n"
            "编制组织：效能中心\n"
            "服务单位：恒睿\n"
            "编号：NX4325\n"
            "花名：廖伊波\n"
            "简历名：廖伊波\n"
            "需求：申请外事号/外事TG号/外事邮箱 1个\n"
            "申请原因：工作需要\n"
            "联系TG：@heather80130"
        )
        self.assertEqual(text, expected)

    def test_work_template_uses_work_demand_text(self):
        fields = {
            "编制组织": "效能中心", "服务单位": "恒睿", "编号": "NX4325",
            "花名": "廖伊波", "简历名": "廖伊波", "联系TG": "@heather80130",
        }
        text = build_account_request_text("工作", fields, today="2026-09-03")
        self.assertIn("需求：申请工作帐号/TG号/工作邮箱 1个", text)

    def test_missing_fields_fall_back_to_placeholder(self):
        text = build_account_request_text("工作", {}, today="2026-09-03")
        self.assertIn("编号：待补充", text)
        self.assertIn("花名：待补充", text)
        self.assertIn("联系TG：待补充", text)

    def test_org_unit_falls_back_to_department_prefix(self):
        fields = {"部门-小组": "技术中心-研发部", "花名": "阿林"}
        text = build_account_request_text("工作", fields, today="2026-09-03")
        self.assertIn("编制组织：技术中心", text)

    def test_contact_tg_gets_at_prefix_when_missing(self):
        fields = {"联系TG": "heather80130"}
        text = build_account_request_text("工作", fields, today="2026-09-03")
        self.assertIn("联系TG：@heather80130", text)

    def test_service_unit_falls_back_to_beidou_field_then_default(self):
        text_with_field = build_account_request_text(
            "工作", {"北斗矩阵": "恒睿"}, today="2026-09-03"
        )
        self.assertIn("服务单位：恒睿", text_with_field)
        text_default = build_account_request_text("工作", {}, today="2026-09-03")
        self.assertIn("服务单位：恒睿", text_default)


if __name__ == '__main__':
    unittest.main()
