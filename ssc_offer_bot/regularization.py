# -*- coding: utf-8 -*-
"""转正提醒的 Drive 查找、花名匹配与四类消息提取。"""

import re

from daily_reports import DRIVE_FILES_URL, _drive_session


SECTION_NAMES = ("转正申请", "转正信息同步", "转正通知", "预转正提醒")
SEPARATOR = "————"
_SECTION_RE = re.compile(
    r"(?m)^[ \t]*【(?P<title>[^【】\r\n]*?(?P<kind>"
    + "|".join(map(re.escape, SECTION_NAMES)) + r"))】[ \t]*$"
)
_BLOCK_RE = re.compile(r"(?m)^\s*(?:—{2,}|-{3,})\s*$")
_NAME_RE = re.compile(r"花名\s*[:：]\s*([^\s,，;；]+)")
_REMINDER_FOOTER_RE = re.compile(r"(?s)\n*如需延期，.*\Z")
_TRIGGER_SEPARATOR_RE = re.compile(r"[\s\-‐‑‒–—―－]+")
_ORG_SECTION_RE_TEMPLATE = r"【\s*{organization}\s*】(?P<body>.*?)(?=\n\s*【|\Z)"
_COUNTDOWN_BLOCK_RE_TEMPLATE = (
    r"转正倒数\s*{days}\s*天\s*[:：](?P<body>.*?)"
    r"(?=\n\s*(?:转正倒数\s*\d+\s*天|今日转正)\s*[:：]|\Z)"
)


def trigger_keyword_matches(text, keyword):
    """兼容旧版连续关键词，以及新版“标题 + 公司分区 + 倒数天数”消息。"""
    compact_text = _TRIGGER_SEPARATOR_RE.sub("", text or "").casefold()
    compact_keyword = _TRIGGER_SEPARATOR_RE.sub("", keyword or "").casefold()
    if compact_keyword and compact_keyword in compact_text:
        return True
    return bool(extract_trigger_scope(text, organization="恒睿", countdown_days=4))


def extract_trigger_scope(text, organization="恒睿", countdown_days=4):
    """返回指定公司分区内对应倒数天数的人员块；未命中返回空串。"""
    normalized = text or ""
    if "转正提醒" not in normalized:
        return ""
    org_pattern = _ORG_SECTION_RE_TEMPLATE.format(
        organization=re.escape(organization)
    )
    org_match = re.search(org_pattern, normalized, flags=re.S)
    if not org_match:
        return ""
    countdown_pattern = _COUNTDOWN_BLOCK_RE_TEMPLATE.format(days=countdown_days)
    countdown_match = re.search(countdown_pattern, org_match.group("body"), flags=re.S)
    if not countdown_match:
        return ""
    body = countdown_match.group("body").strip()
    return body if body else ""


def regularization_trigger_scope(text, keyword):
    """供处理器提取花名：新版只返回恒睿倒数4天块，旧版保留原消息。"""
    scoped = extract_trigger_scope(text, organization="恒睿", countdown_days=4)
    if scoped:
        return scoped
    compact_text = _TRIGGER_SEPARATOR_RE.sub("", text or "").casefold()
    compact_keyword = _TRIGGER_SEPARATOR_RE.sub("", keyword or "").casefold()
    return text if compact_keyword and compact_keyword in compact_text else ""


def _escape_query(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def split_sections(text):
    matches = list(_SECTION_RE.finditer(text or ""))
    sections = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        kind = match.group("kind")
        body = text[match.end():end].strip()
        # 部门/公司前缀标题属于单个人员消息，保留原文并累积同类人员。
        if match.group("title") != kind:
            body = match.group(0).strip() + "\n" + body
        if kind in sections:
            sections[kind] += "\n\n" + SEPARATOR + "\n\n" + body
        else:
            sections[kind] = body
    return sections


def split_blocks(section_text):
    return [block.strip() for block in _BLOCK_RE.split(section_text or "") if block.strip()]


def names_from_trigger(trigger_text, reminder_section):
    """优先读取触发消息的花名字段，格式不规则时用当月花名表反查。"""
    known = list(dict.fromkeys(_NAME_RE.findall(reminder_section or "")))
    explicit = list(dict.fromkeys(_NAME_RE.findall(trigger_text or "")))
    result = [name for name in explicit if name in known]
    compact_trigger = "".join((trigger_text or "").split()).casefold()
    for name in known:
        if name.casefold() in compact_trigger and name not in result:
            result.append(name)
    return result


def _block_has_name(section_name, block, name):
    if re.search(rf"花名\s*[:：]\s*{re.escape(name)}(?=\s|$)", block):
        return True
    return section_name == "转正通知" and name in block


def extract_section_for_names(section_name, section_text, names):
    footer = ""
    if section_name == "预转正提醒":
        footer_match = _REMINDER_FOOTER_RE.search(section_text or "")
        if footer_match:
            footer = footer_match.group(0).strip()
            section_text = (section_text or "")[:footer_match.start()]

    blocks = split_blocks(section_text)
    selected = []
    for name in names:
        matches = [block for block in blocks if _block_has_name(section_name, block, name)]
        if matches:
            # 汇总文件中可能保留旧版本；靠后的区块视为最新版本。
            latest = matches[-1]
            if latest not in selected:
                selected.append(latest)
    if not selected:
        return ""

    body = f"\n\n{SEPARATOR}\n\n".join(selected)
    if footer:
        body += f"\n\n{footer}"
    # 预转正提醒直接发到领导群，不加分区标签；其余参考资料发到收藏夹，保留标签便于辨认。
    if section_name == "预转正提醒":
        return body.strip()
    return (f"【{section_name}】\n\n" + body).strip()


def build_regularization_messages(monthly_text, trigger_text):
    sections = split_sections(monthly_text)
    reminder_section = sections.get("预转正提醒", "")
    names = names_from_trigger(trigger_text, reminder_section)
    messages = {
        name: extract_section_for_names(name, sections.get(name, ""), names)
        for name in SECTION_NAMES
    }
    return names, messages


class RegularizationDriveRepository:
    def __init__(self, output_folder_id):
        self.output_folder_id = output_folder_id

    @staticmethod
    def _list_children(session, auth_params, folder_id):
        params = {
            **auth_params,
            "q": f"'{_escape_query(folder_id)}' in parents and trashed = false",
            "fields": "files(id,name,mimeType,modifiedTime,size)",
            "orderBy": "modifiedTime desc",
            "pageSize": 100,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        response = session.get(DRIVE_FILES_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get("files", [])

    @staticmethod
    def _download_text(session, auth_params, drive_file):
        url = f"{DRIVE_FILES_URL}/{drive_file['id']}"
        response = session.get(
            url, params={**auth_params, "alt": "media"}, timeout=120
        )
        response.raise_for_status()
        # text/plain may default to Latin-1 in requests even for UTF-8 files.
        # Decode bytes explicitly and fail clearly instead of matching mojibake.
        raw = response.content
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            raise ValueError(
                "转正信息文件编码无法识别，请将 TXT 保存为 UTF-8 后重试"
            ) from exc
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def load_month(self, day):
        session, auth_params = _drive_session()
        children = self._list_children(
            session, auth_params, self.output_folder_id
        )
        folder_mime = "application/vnd.google-apps.folder"
        month_tokens = (f"{day.year}{day.month:02d}", f"{day.month}月转正")
        folders = [
            item for item in children
            if item.get("mimeType") == folder_mime
            and "转正" in item.get("name", "")
            and any(token in item.get("name", "") for token in month_tokens)
        ]
        if not folders:
            raise FileNotFoundError(f"未找到 {day.year}年{day.month}月转正文件夹")

        files = self._list_children(session, auth_params, folders[0]["id"])
        candidates = [
            item for item in files
            if item.get("mimeType") != folder_mime
            and item.get("name", "").lower().endswith(".txt")
            and "转正信息" in item.get("name", "")
        ]
        if not candidates:
            raise FileNotFoundError("当月转正文件夹中未找到转正信息 TXT")
        return self._download_text(session, auth_params, candidates[0]), candidates[0]
