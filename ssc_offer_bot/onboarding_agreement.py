# -*- coding: utf-8 -*-
"""场景十四：SSC收藏夹出现"入职协议"关键词后，到Drive入职助手/输出文件夹
里找当日入职信息文件（文件名形如 2026-10-13_入职信息xxx），把当日入职的
每个人的转正审批表链接，私发给这个人的工作TG（没有工作TG就用私人TG）。

入职信息文件的真实排版暂时没有样例可对照，所以这里的解析刻意写得宽松，
并且找不到链接/TG时不猜测、不硬发，而是原样告诉SSC是哪个人缺什么：
- 一份文件可能只有一个人，也可能把当日所有人放在一起；多人时优先按"第一个
  【段落名】标题重复出现"拆分，其次按"花名："行拆分；
- 转正审批表链接：含"转正审批"的那一行里的第一个http(s)链接，该行没有链
  接就看紧挨着的下一行；
- 工作TG取"工作TG"字段，空白/占位（同上、无、待补充）则退回私人TG字段。
纯逻辑单独放在这里，不涉及Telegram调用，方便独立测试。
"""

import io
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

from daily_reports import DRIVE_FILES_URL, _drive_session
from onboarding_training import OnboardingTrainingDriveRepository, _SECTION_RE
from parsers import get_field, parse_kv_fields

AGREEMENT_LINK_MESSAGE = "这是你的转正审批表链接，请签字哦"

_URL_RE = re.compile(r"https?://[^\s<>\"'，。；）)】]+")
_USERNAME_RE = re.compile(r"@?([A-Za-z][A-Za-z0-9_]{4,31})")
_NAME_LINE_RE = re.compile(r"(?m)^[ \t]*花名\s*[:：]")
_PLACEHOLDERS = ("同上", "无", "暂无", "待补充", "没有", "-", "/")
_WORK_TG_KEYS = ("工作TG", "工作tg", "工作Telegram")
_PERSONAL_TG_KEYS = ("私人TG", "私人联系方式", "个人TG", "候选人联系方式", "联系方式", "TG", "Telegram")
_GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
_FOLDER_MIME = "application/vnd.google-apps.folder"


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_FIELD_URL_RE = re.compile(r'HYPERLINK\s+"([^"]+)"', re.I)


def strip_trigger_keyword(text, keyword):
    """收藏夹里机器人自己发的提示也会被触发监听器收到：提示里如果带了触发关键词
    （比如把文件名原样列出来，而文件名里恰好有这个词），就会自己触发自己。
    把关键词拆开一个点，保证发出去的提示一定不含完整关键词。"""
    if not keyword:
        return text
    return (text or "").replace(keyword, keyword[:2] + "·" + keyword[2:])


def docx_to_text(raw):
    """不依赖第三方库，从.docx里取出按段落排版的纯文本：表格里两列的行转成
    "字段：值"，超链接的真实地址（显示文字往往不是网址）追加在显示文字后面，
    保证后面的链接提取能拿到真正的URL。"""
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        document = ET.fromstring(zf.read("word/document.xml"))
        rels = {}
        if "word/_rels/document.xml.rels" in zf.namelist():
            for rel in ET.fromstring(zf.read("word/_rels/document.xml.rels")):
                rels[rel.get("Id")] = rel.get("Target", "")

    def para_text(p):
        out = []

        def walk(node, link=None):
            for child in node:
                tag = child.tag
                if tag == _W + "t":
                    out.append(child.text or "")
                elif tag == _W + "tab":
                    out.append("\t")
                elif tag == _W + "br":
                    out.append("\n")
                elif tag == _W + "instrText":
                    match = _FIELD_URL_RE.search(child.text or "")
                    if match:
                        out.append(" " + match.group(1) + " ")
                elif tag == _W + "hyperlink":
                    target = rels.get(child.get(_R + "id"), "")
                    walk(child)
                    if target.startswith("http"):
                        out.append(" " + target + " ")
                else:
                    walk(child)

        walk(p)
        return "".join(out).strip()

    lines = []

    def walk_block(node):
        for child in node:
            if child.tag == _W + "p":
                lines.append(para_text(child))
            elif child.tag == _W + "tbl":
                for row in child.iter(_W + "tr"):
                    cells = []
                    for cell in row.findall(_W + "tc"):
                        cells.append(" ".join(
                            t for t in (para_text(p) for p in cell.iter(_W + "p")) if t
                        ))
                    cells = [c for c in cells if c]
                    if len(cells) == 2:
                        lines.append(f"{cells[0]}：{cells[1]}")
                    else:
                        lines.extend(cells)
            else:
                walk_block(child)

    walk_block(document)
    return "\n".join(lines)


def _compact(value):
    return "".join(unicodedata.normalize("NFKC", value or "").split())


def split_person_records(text):
    """一份文件里可能有多个人：第一个【段落名】标题重复出现就按它拆；
    否则"花名："行出现多次就按这些行拆；都不是就当成一个人。"""
    text = text or ""
    headers = list(_SECTION_RE.finditer(text))
    if headers:
        first_name = headers[0].group("name")
        starts = [m.start() for m in headers if m.group("name") == first_name]
        if len(starts) > 1:
            starts.append(len(text))
            return [text[a:b].strip() for a, b in zip(starts, starts[1:]) if text[a:b].strip()]
    name_lines = [m.start() for m in _NAME_LINE_RE.finditer(text)]
    if len(name_lines) > 1:
        name_lines.append(len(text))
        return [text[a:b].strip() for a, b in zip(name_lines, name_lines[1:]) if text[a:b].strip()]
    return [text.strip()] if text.strip() else []


def extract_agreement_link(text):
    """含"转正审批"的那一行里的第一个链接；该行没有就看紧挨着的下一行。"""
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        if "转正审批" not in _compact(line):
            continue
        match = _URL_RE.search(line)
        if match:
            return match.group(0)
        if index + 1 < len(lines):
            match = _URL_RE.search(lines[index + 1])
            if match:
                return match.group(0)
    return ""


def _normalize_tg(value):
    value = (value or "").strip()
    if not value or any(value == p for p in _PLACEHOLDERS):
        return ""
    match = _USERNAME_RE.search(value)
    return "@" + match.group(1) if match else ""


def extract_contact_tg(text):
    """返回 (用户名, 来源)，来源是"工作TG"/"私人TG"，都没有返回 ("", "")。"""
    fields = parse_kv_fields(text or "")
    work = _normalize_tg(get_field(fields, *_WORK_TG_KEYS))
    if work:
        return work, "工作TG"
    personal = _normalize_tg(get_field(fields, *_PERSONAL_TG_KEYS))
    if personal:
        return personal, "私人TG"
    return "", ""


def build_agreement_recipients(file_texts):
    """把当日所有入职信息文件拆成一个个人，返回 [dict(name, link, tg, tg_source)]，
    同一个TG出现多次只留第一个（避免同一个人收到重复消息）。"""
    recipients = []
    seen = set()
    for text in file_texts:
        for record in split_person_records(text):
            fields = parse_kv_fields(record)
            name = (get_field(fields, "花名", "简历名", "候选人姓名") or "").strip() or "（未识别花名）"
            tg, source = extract_contact_tg(record)
            link = extract_agreement_link(record)
            key = tg.casefold() or f"noname:{name}:{link}"
            if tg and key in seen:
                continue
            seen.add(key)
            recipients.append({"name": name, "link": link, "tg": tg, "tg_source": source})
    return recipients


def matches_daily_file_name(name, date_str):
    """当日入职信息文件名：2026-10-13_入职信息_毛小婕_郑元宝.gdoc（日期开头），
    也兼容旧文件 ..._入职信息_20261008.txt 这种日期写在后面、不带横线的写法。"""
    compact = _compact(name)
    if "入职信息" not in compact:
        return False
    return compact.startswith(date_str) or date_str.replace("-", "") in compact


def build_agreement_message(link):
    return f"{AGREEMENT_LINK_MESSAGE}\n{link}"


class OnboardingAgreementDriveRepository:
    """按"YYYY-MM-DD_入职信息xxx"命名约定在入职助手/输出文件夹（顶层和最近的
    几个日期/月份子文件夹）里找当日入职信息文件，下载成文本。"""

    def __init__(self, output_folder_id):
        self.output_folder_id = output_folder_id

    @staticmethod
    def _download_text(session, auth_params, drive_file):
        mime = drive_file.get("mimeType")
        if mime == _GOOGLE_DOC_MIME:
            # 导出成docx再解析：text/plain导出会丢掉超链接的真实地址。
            response = session.get(
                f"{DRIVE_FILES_URL}/{drive_file['id']}/export",
                params={**auth_params, "mimeType": _DOCX_MIME}, timeout=120,
            )
        else:
            response = session.get(
                f"{DRIVE_FILES_URL}/{drive_file['id']}",
                params={**auth_params, "alt": "media"}, timeout=120,
            )
        response.raise_for_status()
        raw = response.content
        if raw[:2] == b"PK":
            return docx_to_text(raw)
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            raise ValueError("入职信息文件编码无法识别，请将文件保存为UTF-8文本或Word/Google文档后重试") from exc
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def find_daily_files(self, date_str):
        """返回 (当日入职信息文件的文本列表, 机器人在文件夹里实际看到的全部文件名)；
        后者用来在没找到时告诉SSC机器人到底看到了什么（看到0个通常说明文件夹
        没有分享给机器人的Google服务账号）。"""
        session, auth_params = _drive_session()
        list_children = OnboardingTrainingDriveRepository._list_children
        top_level = list_children(session, auth_params, self.output_folder_id)
        items = [i for i in top_level if i.get("mimeType") != _FOLDER_MIME]
        subfolders = sorted(
            (i for i in top_level if i.get("mimeType") == _FOLDER_MIME),
            key=lambda i: i.get("modifiedTime", ""), reverse=True,
        )
        for subfolder in subfolders[:5]:
            items.extend(
                i for i in list_children(session, auth_params, subfolder["id"])
                if i.get("mimeType") != _FOLDER_MIME
            )
        matched = [i for i in items if matches_daily_file_name(i.get("name", ""), date_str)]
        texts = [self._download_text(session, auth_params, i) for i in matched]
        return texts, [i.get("name", "") for i in items]
