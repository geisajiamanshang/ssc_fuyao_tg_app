import unittest
from datetime import date

from account_application import (
    account_application_reason,
    build_account_application_text,
    is_tech_department,
    merge_rosters,
    needs_account_application,
    parse_roster_date,
    parse_roster_rows,
)


def roster_sheet_rows(*data_rows):
    """拼出跟真实"花名册"结构一致的行列表：前3行是标题/分组表头/字段表头
    （内容对parse_roster_rows不重要，只占位），从第4行开始才是数据。"""
    title_row = ["在职花名册"]
    group_header_row = ["基础身份"]
    field_header_row = ["序号", "员工编码（新）", "花名*", "姓名/简历名（选填）",
                         "在职状态*", "生效日期（入/调）"]
    return [title_row, group_header_row, field_header_row, *data_rows]


def data_row(*, employee_code="", name="", resume_name="", effective_date="",
             org_unit="", service_unit="", department="", work_tg="", personal_contact=""):
    """按列字母位置(B/C/D/F/L/N/O/AD/AE)拼一行，其余列留空字符串。"""
    cells = ["" for _ in range(31)]  # A(0)..AE(30)
    cells[1] = employee_code   # B
    cells[2] = name            # C
    cells[3] = resume_name     # D
    cells[5] = effective_date  # F
    cells[11] = org_unit       # L
    cells[13] = service_unit   # N
    cells[14] = department     # O
    cells[29] = work_tg        # AD
    cells[30] = personal_contact  # AE
    return cells


class ParseRosterRowsTests(unittest.TestCase):
    def test_extracts_named_columns_by_letter(self):
        rows = roster_sheet_rows(
            data_row(employee_code="YY6357", name="范谦和", resume_name="范德",
                     effective_date="2026-09-17", org_unit="运营中心",
                     service_unit="恒睿", department="运营1部",
                     work_tg="@fanqianhe1108", personal_contact="@fanqianhe123"),
        )
        candidates = parse_roster_rows(rows)
        self.assertEqual(len(candidates), 1)
        row = candidates[0]
        self.assertEqual(row["employee_code"], "YY6357")
        self.assertEqual(row["name"], "范谦和")
        self.assertEqual(row["resume_name"], "范德")
        self.assertEqual(row["effective_date_raw"], "2026-09-17")
        self.assertEqual(row["org_unit"], "运营中心")
        self.assertEqual(row["service_unit"], "恒睿")
        self.assertEqual(row["department"], "运营1部")
        self.assertEqual(row["work_tg"], "@fanqianhe1108")
        self.assertEqual(row["personal_contact"], "@fanqianhe123")

    def test_skips_rows_with_empty_name(self):
        rows = roster_sheet_rows(data_row(name="", effective_date="2026-09-01"))
        candidates = parse_roster_rows(rows)
        self.assertEqual(candidates, [])

    def test_handles_short_rows_missing_trailing_columns(self):
        # Sheets API对行尾全空的单元格会直接省略，不会补齐到AE列。
        rows = roster_sheet_rows(["1", "YY0001", "阿林"])
        candidates = parse_roster_rows(rows)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["name"], "阿林")
        self.assertEqual(candidates[0]["work_tg"], "")
        self.assertEqual(candidates[0]["personal_contact"], "")


class ParseRosterDateTests(unittest.TestCase):
    def test_parses_common_formats(self):
        self.assertEqual(parse_roster_date("2026-09-01"), date(2026, 9, 1))
        self.assertEqual(parse_roster_date("2026/9/1"), date(2026, 9, 1))
        self.assertEqual(parse_roster_date("2026.9.1"), date(2026, 9, 1))
        self.assertEqual(parse_roster_date("2026年9月1日"), date(2026, 9, 1))

    def test_unparseable_or_empty_returns_none(self):
        self.assertIsNone(parse_roster_date(""))
        self.assertIsNone(parse_roster_date("不是日期"))


class MergeRostersTests(unittest.TestCase):
    def test_union_of_both_sheets(self):
        primary = [{"name": "张三"}]
        secondary = [{"name": "李四"}]
        merged, conflicts = merge_rosters(primary, secondary)
        self.assertEqual({row["name"] for row in merged}, {"张三", "李四"})
        self.assertEqual(conflicts, [])

    def test_duplicate_name_prefers_primary_and_is_reported(self):
        primary = [{"name": "张三", "department": "来自花名册"}]
        secondary = [{"name": "张三", "department": "来自花名册（机器人）"}]
        merged, conflicts = merge_rosters(primary, secondary)
        self.assertEqual(conflicts, ["张三"])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["department"], "来自花名册")


class NeedsAccountApplicationTests(unittest.TestCase):
    """needs_account_application 现在只看工作TG(AD)/私人联系方式(AE)，不再
    看生效日期——是否在自动化处理范围内(生效日期>=cutover_date)完全交给
    account_application_reason() 判断，按SSC反馈：日期达标就该立刻处理，
    不再额外要求生效满多少天。
    """

    def test_true_when_work_tg_still_placeholder(self):
        # 真实例子：阿林还没申请，工作TG(AD)和私人联系方式(AE)相同。
        row = {"work_tg": "@alin65175", "personal_contact": "@alin65175"}
        self.assertTrue(needs_account_application(row))

    def test_false_when_work_tg_already_different_from_personal_contact(self):
        # 真实例子：范谦和已经申请过，工作TG和私人联系方式不同。
        row = {"work_tg": "@fanqianhe1108", "personal_contact": "@fanqianhe123"}
        self.assertFalse(needs_account_application(row))

    def test_true_when_work_tg_blank(self):
        # AD列完全空白：不管AE列有没有填，都算还没申请。
        row = {"work_tg": "", "personal_contact": ""}
        self.assertTrue(needs_account_application(row))
        row["personal_contact"] = "@x"
        self.assertTrue(needs_account_application(row))

    def test_true_when_work_tg_is_placeholder_text(self):
        # AD列填"同上"这类占位文字，等价于跟AE列相同。
        row = {"work_tg": "同上", "personal_contact": "@x"}
        self.assertTrue(needs_account_application(row))

    def test_false_when_work_tg_filled_but_personal_contact_missing(self):
        # AD列填了具体内容，但AE列是空的，没法比对是否只是占位，不处理。
        row = {"work_tg": "@fanqianhe1108", "personal_contact": ""}
        self.assertFalse(needs_account_application(row))


class IsTechDepartmentTests(unittest.TestCase):
    TECH = ("研发部", "效能部")

    def test_matches_tech_keywords(self):
        self.assertTrue(is_tech_department({"department": "技术中心-研发部"}, tech_departments=self.TECH))
        self.assertTrue(is_tech_department({"department": "效能部"}, tech_departments=self.TECH))

    def test_other_departments_do_not_match(self):
        self.assertFalse(is_tech_department({"department": "运营1部"}, tech_departments=self.TECH))


class AccountApplicationReasonTests(unittest.TestCase):
    TECH = ("研发部", "效能部")
    CUTOVER = date(2026, 10, 1)

    def test_tech_department_before_cutover_is_skipped(self):
        # 生效日期早于cutover的历史存量，哪怕是研发部/效能部也不处理——
        # 这是根据线上真实测试反馈修正的：之前研发部/效能部会绕过cutover
        # 直接生成，导致本该等到10-1之后才处理的人提前生成了草稿。
        row = {"department": "效能部", "effective_date": date(2026, 9, 30)}
        reason = account_application_reason(
            row, tech_departments=self.TECH, cutover_date=self.CUTOVER
        )
        self.assertIsNone(reason)

    def test_tech_department_on_or_after_cutover_qualifies(self):
        # 生效日期达标就立刻处理，不再额外要求生效满多少天——哪怕就是
        # cutover当天，也应该生成。
        row = {"department": "效能部", "effective_date": date(2026, 10, 1)}
        reason = account_application_reason(
            row, tech_departments=self.TECH, cutover_date=self.CUTOVER
        )
        self.assertEqual(reason, "新人入职工作需要")

    def test_other_department_before_cutover_is_skipped(self):
        row = {"department": "运营1部", "effective_date": date(2026, 9, 30)}
        reason = account_application_reason(
            row, tech_departments=self.TECH, cutover_date=self.CUTOVER
        )
        self.assertIsNone(reason)

    def test_other_department_on_or_after_cutover_qualifies(self):
        row = {"department": "运营1部", "effective_date": date(2026, 10, 1)}
        reason = account_application_reason(
            row, tech_departments=self.TECH, cutover_date=self.CUTOVER
        )
        self.assertEqual(reason, "新人入职满7天")

    def test_date_unparseable_is_skipped(self):
        row = {"department": "效能部", "effective_date": None}
        reason = account_application_reason(
            row, tech_departments=self.TECH, cutover_date=self.CUTOVER
        )
        self.assertIsNone(reason)


class BuildAccountApplicationTextTests(unittest.TestCase):
    def test_tech_format_matches_real_example_structure(self):
        row = {
            "name": "廖伊波", "resume_name": "廖伊波", "org_unit": "效能中心",
            "service_unit": "恒睿", "employee_code": "NX4325",
            "personal_contact": "@heather80130",
        }
        text = build_account_application_text(
            row, "新人入职工作需要", is_tech=True, today="2026-09-03"
        )
        self.assertTrue(text.startswith("【员工账号申请】"))
        self.assertIn("申请日期：2026-09-03", text)
        self.assertIn("编制组织：效能中心", text)
        self.assertIn("服务单位：恒睿", text)
        self.assertIn("编号：NX4325", text)
        self.assertIn("花名：廖伊波", text)
        self.assertIn("简历名：廖伊波", text)
        self.assertIn("需求：TG×1", text)
        self.assertIn("申请原因：新人入职工作需要", text)
        self.assertIn("联系TG：@heather80130", text)
        self.assertNotIn("申请数量", text)

    def test_other_format_matches_real_example_structure(self):
        row = {
            "name": "江亦白", "org_unit": "运营中心", "service_unit": "恒睿",
            "department": "运营1部", "employee_code": "YY6342",
            "personal_contact": "yibai7798",
        }
        text = build_account_application_text(
            row, "新人入职满7天", is_tech=False, today="2026-09-02"
        )
        self.assertTrue(text.startswith("【员工工作帐号申请】"))
        self.assertIn("编制组织：运营中心", text)
        self.assertIn("服务公司：恒睿", text)
        self.assertIn("部门：运营1部", text)
        self.assertIn("花名：江亦白", text)
        self.assertIn("员工编号：YY6342", text)
        self.assertIn("需求：TG×1", text)
        self.assertIn("申请原因：新人入职满7天", text)
        self.assertIn("申请数量：1个", text)
        self.assertIn("联系TG：@yibai7798", text)  # 自动补上@前缀
        self.assertIn("申请日期：2026-09-02", text)
        self.assertNotIn("简历名", text)


if __name__ == "__main__":
    unittest.main()
