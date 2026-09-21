from datetime import date
from unittest import TestCase
from unittest.mock import Mock, patch

from regularization import (
    RegularizationDriveRepository,
    build_regularization_messages,
    names_from_trigger,
    split_sections,
)


SAMPLE = """【转正申请】
————
【效能中心-试用员工转正申请】
花名：清衡
编号：NX0393
旧版本
————
【效能中心-试用员工转正申请】
花名：清衡
编号：NX0393
新版本

【转正信息同步】
————
编号：NX0393
花名：清衡
岗位：前端工程师

【转正通知】
————
祝贺 清衡 @qingheng，表现优秀，通过试用期考核评估。

【预转正提醒】
————
【效能中心-恒睿公司-新人预转正提醒】
花名：清衡
编号：NX0393
以上员工试用期即将届满。
————
如需延期，请告知预计转正日期。
"""


class ParserTests(TestCase):
    def test_sections_and_name_matching(self):
        sections = split_sections(SAMPLE)
        self.assertEqual(names_from_trigger(
            "转正提醒-恒睿-转正倒数4天\n花名：清衡", sections["预转正提醒"]
        ), ["清衡"])

    def test_extracts_four_messages_and_latest_application(self):
        names, messages = build_regularization_messages(
            SAMPLE, "转正提醒-恒睿-转正倒数4天 清衡"
        )
        self.assertEqual(names, ["清衡"])
        self.assertNotIn("旧版本", messages["转正申请"])
        self.assertIn("新版本", messages["转正申请"])
        self.assertIn("如需延期", messages["预转正提醒"])
        self.assertTrue(all(messages.values()))

    def test_unknown_name_does_not_match(self):
        names, messages = build_regularization_messages(
            SAMPLE, "转正提醒-恒睿-转正倒数4天\n花名：不存在"
        )
        self.assertEqual(names, [])
        self.assertFalse(any(messages.values()))

    def test_multiple_names_are_kept_in_source_order(self):
        sample = SAMPLE.replace(
            "花名：清衡\n编号：NX0393\n以上员工试用期即将届满。",
            "花名：清衡\n编号：NX0393\n\n花名：金佳烽\n编号：NX0394\n以上员工试用期即将届满。",
        )
        names, messages = build_regularization_messages(
            sample, "转正提醒-恒睿-转正倒数4天 清衡、金佳烽"
        )
        self.assertEqual(names, ["清衡", "金佳烽"])
        self.assertIn("花名：金佳烽", messages["预转正提醒"])


class FakeResponse:
    def __init__(self, payload=None, text=""):
        self.payload = payload or {}
        self.text = text
        self.encoding = "utf-8"

    @property
    def content(self):
        return self.text.encode(self.encoding)

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class RepositoryTests(TestCase):
    def test_selects_current_month_folder_and_txt(self):
        session = Mock()
        session.get.side_effect = [
            FakeResponse({"files": [
                {"id": "sep", "name": "20260901_9月转正",
                 "mimeType": "application/vnd.google-apps.folder"},
            ]}),
            FakeResponse({"files": [
                {"id": "txt", "name": "2026年9月多人转正信息_20260901.txt",
                 "mimeType": "text/plain"},
            ]}),
            FakeResponse(text=SAMPLE),
        ]
        with patch("regularization._drive_session", return_value=(session, {})):
            text, item = RegularizationDriveRepository("output").load_month(
                date(2026, 9, 16)
            )
        self.assertEqual(text, SAMPLE)
        self.assertEqual(item["id"], "txt")

    def test_find_poster_matches_by_name_in_month_folder(self):
        session = Mock()
        session.get.side_effect = [
            FakeResponse({"files": [
                {"id": "sep", "name": "20260901_9月转正",
                 "mimeType": "application/vnd.google-apps.folder"},
            ]}),
            FakeResponse({"files": [
                {"id": "txt", "name": "2026年9月多人转正信息_20260901.txt",
                 "mimeType": "text/plain"},
                {"id": "poster-other", "name": "三风_转正海报_20260901.png",
                 "mimeType": "image/png"},
                {"id": "poster-bill", "name": "比尔_转正海报_20260901.png",
                 "mimeType": "image/png"},
            ]}),
            FakeResponse(text="PNGBYTES"),
        ]
        with patch("regularization._drive_session", return_value=(session, {})):
            poster = RegularizationDriveRepository("output").find_poster(
                date(2026, 9, 21), "比尔"
            )
        self.assertEqual(poster.read(), b"PNGBYTES")

    def test_find_poster_raises_when_no_match(self):
        session = Mock()
        session.get.side_effect = [
            FakeResponse({"files": [
                {"id": "sep", "name": "20260901_9月转正",
                 "mimeType": "application/vnd.google-apps.folder"},
            ]}),
            FakeResponse({"files": [
                {"id": "txt", "name": "2026年9月多人转正信息_20260901.txt",
                 "mimeType": "text/plain"},
            ]}),
        ]
        with patch("regularization._drive_session", return_value=(session, {})):
            with self.assertRaises(FileNotFoundError):
                RegularizationDriveRepository("output").find_poster(
                    date(2026, 9, 21), "比尔"
                )
