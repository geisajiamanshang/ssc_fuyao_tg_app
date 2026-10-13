# -*- coding: utf-8 -*-
"""场景十四：SSC收藏夹出现"入职协议"关键词后，到Drive入职协议文件夹下找当月
文件夹（例：2026年-10月），取里面当日入职的所有入职协议（文件名约定
"花名_入职协议_日期"），从协议内容里读出这个人的私人TG，把协议的Drive链接
私发给他，附带"这是你的入职协议，签字哦"。

协议文件是Word(.docx)或Google文档，真实排版没有样例，所以读TG时刻意宽松：
- 先找"私人TG"类字段，没有再退回"工作TG"字段；
- 都没有时，协议全文里只出现一个@用户名就用它（出现多个不猜，交给人工）；
- 找不到的人不硬发，原样告诉SSC是谁缺什么。
纯逻辑单独放在这里，不涉及Telegram调用，方便独立测试。
"""

import io
import re
import unicodedata
import zipfile
from xml.etree import ElementTree as ET

from daily_reports import DRIVE_FILES_URL, _drive_session
from onboarding_training import OnboardingTrainingDriveRepository

AGREEMENT_LINK_MESSAGE = "这是你的入职协议，签字哦"

_USERNAME_RE = re.compile(r"@?([A-Za-z][A-Za-z0-9_]{4,31})")
# 前面是字母/数字/点说明是邮箱（a@gmail.com），不是TG用户名。
_AT_USERNAME_RE = re.compile(r"(?<![A-Za-z0-9_.])@([A-Za-z][A-Za-z0-9_]{4,31})")
_KEY_VALUE_LINE_RE = re.compile(r"^\s*([^:：\n]{1,16}?)\s*[:：]\s*(.+?)\s*$")
_PLACEHOLDERS = ("同上", "无", "暂无", "待补充", "没有", "-", "/")
_WORK_TG_KEYS = ("工作tg", "工作telegram")
_PERSONAL_TG_KEYS = ("私人tg", "私人telegram", "私人联系方式", "个人tg", "候选人联系方式", "联系方式", "tg", "telegram")
_GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
_FOLDER_MIME = "application/vnd.google-apps.folder"


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
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
    "字段：值"，超链接的真实地址追加在显示文字后面。"""
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        document = ET.fromstring(zf.read("word/document.xml"))
        rels = {}
        if "word/_rels/document.xml.rels" in zf.namelist():
            for rel in ET.fromstring(zf.read("word/_rels/document.xml.rels")):
                rels[rel.get("Id")] = rel.get("Target", "")

    def para_text(p):
        out = []

        def walk(node):
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


def _normalize_tg(value):
    value = (value or "").strip()
    if not value or any(value == p for p in _PLACEHOLDERS):
        return ""
    match = _AT_USERNAME_RE.search(value) or _USERNAME_RE.search(value)
    return "@" + match.group(1) if match else ""


def extract_private_tg(text):
    """返回 (用户名, 来源)：先私人TG字段，再工作TG字段，再协议全文里唯一的@用户名；
    都没有返回 ("", "")。字段名按去空格、不分大小写比较（"私人 tg:"也行）。"""
    normalized = unicodedata.normalize("NFKC", text or "")
    work = personal = ""
    for line in normalized.splitlines():
        match = _KEY_VALUE_LINE_RE.match(line)
        if not match:
            continue
        key = "".join(match.group(1).split()).lower()
        if key in _PERSONAL_TG_KEYS and not personal:
            personal = _normalize_tg(match.group(2))
        elif key in _WORK_TG_KEYS and not work:
            work = _normalize_tg(match.group(2))
    if personal:
        return personal, "私人TG"
    if work:
        return work, "工作TG"
    handles = {h.casefold(): h for h in _AT_USERNAME_RE.findall(normalized)}
    if len(handles) == 1:
        return "@" + next(iter(handles.values())), "协议内TG"
    return "", ""


def _date_tokens(date_str):
    year, month, day = (int(x) for x in date_str.split("-"))
    return {
        f"{year}{month:02d}{day:02d}", f"{year}-{month:02d}-{day:02d}", f"{year}-{month}-{day}",
        f"{year}.{month:02d}.{day:02d}", f"{year}.{month}.{day}", f"{year}/{month:02d}/{day:02d}",
        f"{year}年{month}月{day}日",
    }


def _month_tokens(date_str):
    year, month = (int(x) for x in date_str.split("-")[:2])
    return {
        f"{year}年-{month}月", f"{year}年-{month:02d}月", f"{year}年{month}月", f"{year}年{month:02d}月",
        f"{year}-{month:02d}", f"{year}-{month}", f"{year}.{month:02d}", f"{year}{month:02d}",
    }


def matches_month_folder(folder_name, date_str):
    """当月文件夹：2026年-10月（也兼容 2026年10月、2026-10、202610 这类写法）。"""
    compact = _compact(folder_name)
    return any(token in compact for token in _month_tokens(date_str))


def matches_agreement_file_name(file_name, date_str):
    """当日入职协议：文件名含"入职协议"和当日日期（花名_入职协议_20261013.docx）。"""
    compact = _compact(file_name)
    return "入职协议" in compact and any(token in compact for token in _date_tokens(date_str))


def person_name_from_file_name(file_name):
    """从"花名_入职协议_日期.docx"取花名（第一个下划线之前）。"""
    stem = _compact(file_name).rsplit(".", 1)[0] if "." in _compact(file_name) else _compact(file_name)
    head = stem.split("_")[0]
    return head if head and "入职协议" not in head else ""


def drive_file_link(drive_file):
    if drive_file.get("webViewLink"):
        return drive_file["webViewLink"]
    if drive_file.get("mimeType") == _GOOGLE_DOC_MIME:
        return f"https://docs.google.com/document/d/{drive_file['id']}/edit"
    return f"https://drive.google.com/file/d/{drive_file['id']}/view"


def build_agreement_message(link):
    return f"{AGREEMENT_LINK_MESSAGE}\n{link}"


def build_leader_approval_message(links):
    """发给领导审批的汇总消息：第一行"x人入职协议，请萌萌姐审批"，下面每个协议一个链接，
    链接之间空一行。"""
    return f"{len(links)}人入职协议，请萌萌姐审批\n" + "\n\n".join(links)


def collect_folder_files(session, auth_params, folder_id):
    """文件夹顶层的文件，加上最近修改的5个子文件夹里的文件。"""
    list_children = OnboardingTrainingDriveRepository._list_children
    top_level = list_children(session, auth_params, folder_id)
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
    return items


class OnboardingAgreementRepository:
    """入职协议根文件夹 -> 当月文件夹 -> 当日入职协议（下载成文本，供读私人TG）。"""

    def __init__(self, root_folder_id):
        self.root_folder_id = root_folder_id

    @staticmethod
    def _download_text(session, auth_params, drive_file):
        if drive_file.get("mimeType") == _GOOGLE_DOC_MIME:
            # 导出成docx再解析，和上传的.docx走同一条解析路径。
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
        return raw.decode(encoding).replace("\r\n", "\n").replace("\r", "\n")

    def find_today_agreements(self, date_str):
        """返回 (协议列表, 诊断信息)。协议 = dict(name花名, file_name, link, text, error)，
        同一个花名有多个文件（.docx和Google文档并存）时取最近修改的。
        诊断信息 = dict(root_folders根目录下看到的文件夹名, month_folders命中的月份
        文件夹名, files月份文件夹里看到的文件名)，找不到协议时用来告诉SSC机器人
        到底看到了什么（全是空通常说明文件夹没分享给机器人的Google服务账号）。"""
        session, auth_params = _drive_session()
        top = OnboardingTrainingDriveRepository._list_children(session, auth_params, self.root_folder_id)
        folders = [i for i in top if i.get("mimeType") == _FOLDER_MIME]
        month_folders = [f for f in folders if matches_month_folder(f.get("name", ""), date_str)]
        if month_folders:
            items, seen_ids = [], set()
            for folder in month_folders:
                for item in collect_folder_files(session, auth_params, folder["id"]):
                    if item.get("id") not in seen_ids:
                        seen_ids.add(item.get("id"))
                        items.append(item)
        else:
            items = [i for i in top if i.get("mimeType") != _FOLDER_MIME]
        diagnostics = {
            "root_folders": [f.get("name", "") for f in folders],
            "month_folders": [f.get("name", "") for f in month_folders],
            "files": [i.get("name", "") for i in items],
        }
        latest = {}
        for item in items:
            if not matches_agreement_file_name(item.get("name", ""), date_str):
                continue
            name = person_name_from_file_name(item.get("name", "")) or _compact(item.get("name", ""))
            if name not in latest or item.get("modifiedTime", "") > latest[name].get("modifiedTime", ""):
                latest[name] = item
        agreements = []
        for name, item in sorted(latest.items()):
            entry = {"name": name, "file_name": item.get("name", ""), "link": drive_file_link(item),
                     "text": "", "error": ""}
            try:
                entry["text"] = self._download_text(session, auth_params, item)
            except Exception as exc:  # 单个文件读不出来只影响这个人，其他人照常处理
                entry["error"] = str(exc)[:100]
            agreements.append(entry)
        return agreements, diagnostics
