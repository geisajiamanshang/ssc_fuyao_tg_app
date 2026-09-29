import unittest
from datetime import date

from account_application import (
    account_application_reason,
    build_account_application_text,
    merge_rosters,
    needs_account_application,
    parse_roster_csv,
    parse_roster_date,
)


def roster_row(*, col_c="", col_f="", col_o="", col_ad="", col_ae=""):
    """按列字母拼一行27列(A..AE)宽的CSV行，方便测试用列字母定位而不是数数字下标。"""
    cells = ["" for _ in range(31)]  # A(0)..AE(30)
    cells[2] = col_c   # C 姓名
    cells[5] = col_f   # F 生效日期
    cells[14] = col_o  # O 部门
    cells[29] = col_ad  # AD
    cells[30] = col_ae  # AE
    return ",".join(cells)


def make_csv(*rows):
    header = ",".join(["header"] * 31)
    return "\n".join([header, *rows])


class ParseRosterCsvTests(unittest.TestCase):
    def test_extracts_named_columns_by_letter(self):
        csv_text = make_csv(
            roster_row(col_c="廖伊波", col_f="2026-09-01", col_o="效能中心-效能部",
                       col_ad="已申请", col_ae="未申请"),
        )
        rows = parse_roster_csv(csv_text, name_col="C", date_col="F", dept_col="O",
                                 status_cols=("AD", "AE"))
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["name"], "廖伊波")
        self.assertEqual(row["effective_date_raw"], "2026-09-01")
        self.assertEqual(row["department"], "效能中心-效能部")
        self.assertEqual(row["status_values"], ["已申请", "未申请"])

    def test_skips_rows_with_empty_name(self):
        csv_text = make_csv(roster_row(col_c="", col_f="2026-09-01"))
        rows = parse_roster_csv(csv_text, name_col="C", date_col="F", dept_col="O",
                                 status_cols=("AD", "AE"))
        self.assertEqual(rows, [])

    def test_skips_rows_shorter_than_needed_columns(self):
        rows = parse_roster_csv("表头\n廖伊波,x", name_col="C", date_col="F", dept_col="O",
                                 status_cols=("AD", "AE"))
        self.assertEqual(rows, [])


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
    def test_true_when_effective_long_enough_and_status_differs(self):
        row = {
            "effective_date": date(2026, 9, 1),
            "status_values": ["已申请", "未申请"],
        }
        self.assertTrue(needs_account_application(row, date(2026, 9, 10)))

    def test_false_when_not_enough_days_elapsed(self):
        row = {
            "effective_date": date(2026, 9, 8),
            "status_values": ["已申请", "未申请"],
        }
        self.assertFalse(needs_account_application(row, date(2026, 9, 10)))

    def test_false_when_status_values_equal(self):
        row = {
            "effective_date": date(2026, 9, 1),
            "status_values": ["已申请", "已申请"],
        }
        self.assertFalse(needs_account_application(row, date(2026, 9, 10)))

    def test_false_when_date_unparseable(self):
        row = {"effective_date": None, "status_values": ["已申请", "未申请"]}
        self.assertFalse(needs_account_application(row, date(2026, 9, 10)))


class AccountApplicationReasonTests(unittest.TestCase):
    TECH = ("研发部", "效能部")
    CUTOVER = date(2026, 10, 1)

    def test_tech_department_always_qualifies(self):
        row = {"department": "技术中心-研发部", "effective_date": date(2026, 1, 1)}
        reason = account_application_reason(
            row, date(2026, 9, 10), tech_departments=self.TECH, cutover_date=self.CUTOVER
        )
        self.assertEqual(reason, "新人入职工作需要")

    def test_other_department_before_cutover_is_skipped(self):
        row = {"department": "运营中心-运营1部", "effective_date": date(2026, 9, 1)}
        reason = account_application_reason(
            row, date(2026, 9, 10), tech_departments=self.TECH, cutover_date=self.CUTOVER
        )
        self.assertIsNone(reason)

    def test_other_department_on_or_after_cutover_qualifies(self):
        row = {"department": "运营中心-运营1部", "effective_date": date(2026, 10, 1)}
        reason = account_application_reason(
            row, date(2026, 10, 10), tech_departments=self.TECH, cutover_date=self.CUTOVER
        )
        self.assertEqual(reason, "新人入职满7天")


class BuildAccountApplicationTextTests(unittest.TestCase):
    def test_uses_template_header_when_present(self):
        row = {"name": "廖伊波", "department": "效能中心-效能部", "effective_date_raw": "2026-09-01"}
        text = build_account_application_text(row, "新人入职工作需要", "【帐号申请模版】填写说明", today="2026-09-10")
        self.assertTrue(text.startswith("【帐号申请模版】填写说明"))
        self.assertIn("候选人姓名：廖伊波", text)
        self.assertIn("申请理由：新人入职工作需要", text)
        self.assertIn("申请日期：2026-09-10", text)

    def test_falls_back_to_default_header_when_template_missing(self):
        row = {"name": "廖伊波", "department": "效能中心-效能部", "effective_date_raw": "2026-09-01"}
        text = build_account_application_text(row, "新人入职工作需要", "", today="2026-09-10")
        self.assertTrue(text.startswith("【员工帐号申请】"))


if __name__ == "__main__":
    unittest.main()
