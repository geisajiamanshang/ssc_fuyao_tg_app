from unittest import TestCase

from anniversary import (
    AnniversaryDriveRepository,
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

    def test_compact_name_extracted_when_info_file_has_no_known_names(self):
        # 信息文件里完全没有可反查的花名（比如还没来得及生成/更新）时，
        # 也要能直接从触发消息的紧凑格式里取出花名，而不是直接判定未匹配。
        trigger = "简言（NX0362｜运营中心/技术效能部）入职日期：2026-09-15"
        self.assertEqual(names_from_anniversary_trigger(trigger, ""), ["简言"])

    def test_compact_name_recovers_full_pipeline_against_real_greeting_file(self):
        # 用真实周年祝贺语.txt 的格式：反查花名表没命中这个人时（比如信息文件
        # 还没来得及包含他），最终仍能从紧凑格式里取出花名，并且这个花名依然
        # 能在祝贺语正文里通过子串匹配找到对应内容（extract_anniversary_greeting
        # 自己也会退回子串匹配，不依赖 known 花名表）。
        info_text = """【陈昊｜1周年】
祝贺 陈昊 @chenhao985

入职满 1 周年，感谢有你！！！

————————————

【简言｜1周年】
祝贺 简言 @jianyan567

入职满 1 周年，感谢有你！！！
"""
        trigger = "简言（NX0362｜运营中心/技术效能部）入职日期：2026-09-15"
        # 故意传一份不包含“简言”的信息文件片段，模拟反查表没命中的情况。
        names = names_from_anniversary_trigger(trigger, "【陈昊｜1周年】\n祝贺 陈昊 @chenhao985")
        self.assertEqual(names, ["简言"])
        greeting = extract_anniversary_greeting(info_text, names[0])
        self.assertTrue(greeting.startswith("祝贺 简言 @jianyan567"))


class FakeMisdetectedEncodingResponse:
    """模拟 requests 把 text/plain 误判成 Latin-1：content是正确的UTF-8字节，
    但 .encoding/.text 会按错误编码解码，用来验证下载函数不会依赖它们。"""

    def __init__(self, text):
        self._utf8_bytes = text.encode("utf-8")
        self.encoding = "ISO-8859-1"

    @property
    def content(self):
        return self._utf8_bytes

    @property
    def text(self):
        return self._utf8_bytes.decode(self.encoding)

    def raise_for_status(self):
        return None


class DownloadTextEncodingTests(TestCase):
    def test_decodes_utf8_bytes_even_when_response_claims_latin1(self):
        real_text = "【简言｜1周年】\n祝贺 简言 @jianyan567\n\n入职满 1 周年，感谢有你！！！\n"
        response = FakeMisdetectedEncodingResponse(real_text)
        session = type("Session", (), {"get": lambda self, *a, **k: response})()
        drive_file = {"id": "f1", "mimeType": "text/plain"}
        decoded = AnniversaryDriveRepository._download_text(session, {}, drive_file)
        self.assertEqual(decoded, real_text)
        self.assertIn("简言", decoded)
        # 反面对照：直接读 .text（走 requests 自己猜的编码）会是乱码，
        # 证明修复确实绕开了 response.text，不是碰巧一样。
        self.assertNotIn("简言", response.text)
