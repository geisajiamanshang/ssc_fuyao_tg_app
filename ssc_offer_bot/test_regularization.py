from datetime import date
from unittest import TestCase
from unittest.mock import Mock, patch

from regularization import (
    RegularizationDriveRepository,
    month_name_matches,
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


FOLDER = "application/vnd.google-apps.folder"
OCT = date(2026, 10, 14)


class MonthFolderMatchingTests(TestCase):
    def test_month_name_variants_for_october(self):
        for name in ("20261001_10月转正", "2026年10月转正", "2026年-10月", "2026年-10月转正", "2026-10",
                     "202610", "2026.10月转正", "10月转正", "2026年10月5人转正", "2026年 10 月"):
            self.assertTrue(month_name_matches(name, OCT), name)

    def test_other_months_do_not_match(self):
        for name in ("20260901_9月转正", "2026年9月转正", "2026年-11月", "2025年10月", "110月",
                     "2026中秋国庆5人转正", "转正模版", "20250901_10月转正"):
            self.assertFalse(month_name_matches(name, OCT), name)
        self.assertFalse(month_name_matches("2026年10月转正", date(2026, 1, 5)))   # 1月 != 10月
        self.assertTrue(month_name_matches("2026年1月转正", date(2026, 1, 5)))


def _session(*payloads):
    session = Mock()
    session.get.side_effect = list(payloads)
    return session


class MonthFolderResolutionTests(TestCase):
    def _load(self, session, day=OCT):
        with patch("regularization._drive_session", return_value=(session, {})):
            return RegularizationDriveRepository("output").load_month(day)

    def test_folder_without_zhuanzheng_in_name_is_found(self):
        # 用户新的月份文件夹命名习惯："2026年-10月"，名字里没有"转正"。
        session = _session(
            FakeResponse({"files": [{"id": "oct", "name": "2026年-10月", "mimeType": FOLDER}]}),
            FakeResponse({"files": [{"id": "txt", "name": "2026年10月多人转正信息_20261014.txt", "mimeType": "text/plain"}]}),
            FakeResponse(text=SAMPLE),
        )
        text, item = self._load(session)
        self.assertEqual((text, item["id"]), (SAMPLE, "txt"))

    def test_prefers_folder_with_zhuanzheng_over_plain_month_folder(self):
        session = _session(
            FakeResponse({"files": [
                {"id": "plain", "name": "2026年10月", "mimeType": FOLDER},
                {"id": "reg", "name": "2026年10月5人转正", "mimeType": FOLDER}]}),
            FakeResponse({"files": [{"id": "txt", "name": "转正信息_20261014.txt", "mimeType": "text/plain"}]}),
            FakeResponse(text=SAMPLE),
        )
        self._load(session)
        self.assertEqual(session.get.call_args_list[1].args[0].rsplit("/", 1)[-1], "files")
        self.assertIn("'reg' in parents", session.get.call_args_list[1].kwargs["params"]["q"])

    def test_fallback_to_zhuanzheng_folder_whose_info_file_names_the_month(self):
        session = _session(
            FakeResponse({"files": [{"id": "holiday", "name": "2026中秋国庆5人转正", "mimeType": FOLDER}]}),
            FakeResponse({"files": [{"id": "txt", "name": "2026年10月多人转正信息_20261001.txt", "mimeType": "text/plain"}]}),
            FakeResponse({"files": [{"id": "txt", "name": "2026年10月多人转正信息_20261001.txt", "mimeType": "text/plain"}]}),
            FakeResponse(text=SAMPLE),
        )
        text, item = self._load(session)
        self.assertEqual(item["id"], "txt")

    def test_not_found_error_lists_what_the_bot_saw(self):
        session = _session(FakeResponse({"files": [
            {"id": "sep", "name": "20260901_9月转正", "mimeType": FOLDER},
            {"id": "x", "name": "2026中秋国庆5人转正", "mimeType": FOLDER}]}),
            FakeResponse({"files": []}), FakeResponse({"files": []}), FakeResponse({"files": []}))
        with self.assertRaises(FileNotFoundError) as ctx:
            self._load(session)
        message = str(ctx.exception)
        self.assertIn("未找到 2026年10月转正文件夹", message)
        self.assertIn("20260901_9月转正", message)
        self.assertIn("看到2个文件夹", message)
        self.assertLess(len(message), 300)

    def test_nothing_visible_hints_at_sharing(self):
        with self.assertRaises(FileNotFoundError) as ctx:
            self._load(_session(FakeResponse({"files": []})))
        self.assertIn("没有分享给机器人的Google服务账号", str(ctx.exception))

    def test_docx_info_file_is_used_when_no_txt(self):
        import io as _io
        import zipfile as _zip

        w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
        body = (f'<w:document xmlns:w="{w}"><w:body>'
                + "".join(f"<w:p><w:r><w:t>{line}</w:t></w:r></w:p>" for line in SAMPLE.splitlines())
                + "</w:body></w:document>")
        buf = _io.BytesIO()
        with _zip.ZipFile(buf, "w") as zf:
            zf.writestr("word/document.xml", body)
        class BytesResponse(FakeResponse):
            content = buf.getvalue()

        response = BytesResponse(text="")
        session = _session(
            FakeResponse({"files": [{"id": "oct", "name": "2026年-10月转正", "mimeType": FOLDER}]}),
            FakeResponse({"files": [{"id": "doc", "name": "2026年10月多人转正信息_20261014.docx", "mimeType": "application/x"}]}),
            response,
        )
        text, item = self._load(session)
        self.assertEqual(item["id"], "doc")
        self.assertIn("【转正信息同步】", text)
        self.assertEqual(split_sections(text)["转正信息同步"].strip().splitlines()[0], "————")
