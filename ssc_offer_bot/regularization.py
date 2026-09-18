# -*- coding: utf-8 -*-
"""转正提醒的 Drive 查找、花名匹配与四类消息提取。"""

import re

from daily_reports import DRIVE_FILES_URL, _drive_session


SECTION_NAMES = ("转正申请", "转正信息同步", "转正通知", "预转正提醒")
SEPARATOR = "————"
_SECTION_RE = re.compile(
    r"【(" + "|".join(map(re.escape, SECTION_NAMES)) + r")】"
)
_BLOCK_RE = re.compile(r"(?m)^\s*(?:—{2,}|-{3,})\s*$")
_NAME_RE = re.compile(r"花名\s*[:：]\s*([^\s,，;；]+)")
_REMINDER_FOOTER_RE = re.compile(r"(?s)\n*如需延期，.*\Z")
_TRIGGER_SEPARATOR_RE = re.compile(r"[\s\-‐‑‒–—―－]+")


def trigger_keyword_matches(text, keyword):
    """容忍全角/半角横线、长横线及分隔空格。"""
    compact_text = _TRIGGER_SEPARATOR_RE.sub("", text or "").casefold()
    compact_keyword = _TRIGGER_SEPARATOR_RE.sub("", keyword or "").casefold()
    return bool(compact_keyword and compact_keyword in compact_text)


def _escape_query(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def split_sections(text):
    matches = list(_SECTION_RE.finditer(text or ""))
    sections = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections[match.group(1)] = text[match.end():end].strip()
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

    result = f"【{section_name}】\n\n" + f"\n\n{SEPARATOR}\n\n".join(selected)
    if footer:
        result += f"\n\n{SEPARATOR}\n\n{footer}"
    return result.strip()


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
        response.encoding = response.encoding or "utf-8"
        return response.text

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
