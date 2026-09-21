# -*- coding: utf-8 -*-
"""入职周年提醒的 Drive 文件查找、内容提取与目标群匹配。"""

import io
import re

from daily_reports import DRIVE_FILES_URL, _drive_session


FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
_NAME_RE = re.compile(r"花名\s*[:：]\s*([^\s,，;；]+)")
_HEADING_NAME_RE = re.compile(r"【\s*([^【】｜|]+?)\s*[｜|]\s*\d+\s*周年\s*】")
_ANNIVERSARY_HEADING_RE = re.compile(
    r"^\s*【\s*[^【】｜|]+?\s*[｜|]\s*\d+\s*周年\s*】\s*"
)
_BLOCK_RE = re.compile(r"(?m)^\s*(?:—{2,}|-{3,})\s*$")
_FIELD_RE = re.compile(r"(?m)^\s*([^\n:：]{1,20})\s*[:：]\s*([^\n]+?)\s*$")
# 云昭机器人的分组提醒消息把编号和编制组织/部门写在花名后的括号里，
# 例如“简言（NX0362｜运营中心/技术效能部）”，不是独立的“编制组织：/部门：”字段行。
_COMPACT_ENTRY_RE = re.compile(r"[（(][^）(]*?[｜|]([^）)]+)[）)]")


def _normalized(value):
    return re.sub(r"[\s/_\-—]+", "", value or "").casefold()


def _escape_query(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def names_from_anniversary_trigger(trigger_text, info_text):
    """优先使用提醒里的“花名”，再用入职信息文件中的已知花名反查。"""
    known = list(dict.fromkeys(
        _NAME_RE.findall(info_text or "") + _HEADING_NAME_RE.findall(info_text or "")
    ))
    explicit = list(dict.fromkeys(_NAME_RE.findall(trigger_text or "")))
    result = explicit[:]
    compact = _normalized(trigger_text)
    for name in known:
        if _normalized(name) in compact and name not in result:
            result.append(name)
    return result


def extract_anniversary_greeting(info_text, name):
    """取指定花名靠后的周年祝贺区块，汇总文件有旧版时使用最新版。"""
    text = (info_text or "").strip()
    blocks = [block.strip() for block in _BLOCK_RE.split(text) if block.strip()]
    explicit = [
        block for block in blocks
        if re.search(rf"花名\s*[:：]\s*{re.escape(name)}(?=\s|$)", block)
    ]
    matches = explicit or [block for block in blocks if name in block]
    if not matches:
        return ""
    greeting = matches[-1].strip()
    if "周年" not in greeting and "祝贺" not in greeting:
        return ""
    # 汇总文件的分段标题只用于查找，不随海报发出；正文作为图片说明，
    # 从“祝贺 花名 @账号”开始，与海报组成一条 Telegram 消息。
    return _ANNIVERSARY_HEADING_RE.sub("", greeting, count=1).strip()


def parse_anniversary_fields(trigger_text):
    fields = {key.strip(): value.strip() for key, value in _FIELD_RE.findall(trigger_text or "")}
    org_unit = fields.get("编制组织", "") or fields.get("入职编制组织", "")
    department = fields.get("部门", "") or fields.get("入职部门", "")
    if not org_unit and not department:
        # 独立字段行不存在时，退回解析紧凑格式括号里的“编制组织/部门”。
        match = _COMPACT_ENTRY_RE.search(trigger_text or "")
        if match:
            org_unit, _, department = match.group(1).strip().partition("/")
            org_unit, department = org_unit.strip(), department.strip()
    return {"org_unit": org_unit, "department": department}


def anniversary_destination(trigger_text, group_rules):
    """按提醒中的编制组织和部门匹配唯一目标群。"""
    fields = parse_anniversary_fields(trigger_text)
    haystack = _normalized(fields["org_unit"] + fields["department"])
    if not haystack:
        return None, fields
    for rule in group_rules:
        if any(_normalized(keyword) in haystack for keyword in rule["keywords"]):
            return int(rule["chat_id"]), fields
    return None, fields


class AnniversaryDriveRepository:
    def __init__(self, root_folder_id, path_parts):
        self.root_folder_id = root_folder_id
        self.path_parts = tuple(path_parts)

    @staticmethod
    def _list_children(session, auth_params, folder_id):
        params = {
            **auth_params,
            "q": f"'{_escape_query(folder_id)}' in parents and trashed = false",
            "fields": "files(id,name,mimeType,modifiedTime,size)",
            "orderBy": "modifiedTime desc",
            "pageSize": 1000,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        response = session.get(DRIVE_FILES_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get("files", [])

    def _resolve_folder(self, session, auth_params):
        folder_id = self.root_folder_id
        for part in self.path_parts:
            children = self._list_children(session, auth_params, folder_id)
            matches = [
                item for item in children
                if item.get("mimeType") == FOLDER_MIME
                and _normalized(item.get("name", "")) == _normalized(part)
            ]
            if not matches:
                raise FileNotFoundError("Drive中未找到文件夹：" + "/".join(self.path_parts))
            folder_id = matches[0]["id"]
        return folder_id

    @staticmethod
    def _download_text(session, auth_params, drive_file):
        if drive_file.get("mimeType") == GOOGLE_DOC_MIME:
            url = f"{DRIVE_FILES_URL}/{drive_file['id']}/export"
            params = {**auth_params, "mimeType": "text/plain"}
        else:
            url = f"{DRIVE_FILES_URL}/{drive_file['id']}"
            params = {**auth_params, "alt": "media"}
        response = session.get(url, params=params, timeout=120)
        response.raise_for_status()
        response.encoding = response.encoding or "utf-8"
        return response.text

    @staticmethod
    def _download_bytes(session, auth_params, drive_file):
        response = session.get(
            f"{DRIVE_FILES_URL}/{drive_file['id']}",
            params={**auth_params, "alt": "media"},
            timeout=120,
        )
        response.raise_for_status()
        result = io.BytesIO(response.content)
        result.name = drive_file.get("name") or "anniversary-poster.jpg"
        return result

    def load(self, trigger_text):
        session, auth_params = _drive_session()
        folder_id = self._resolve_folder(session, auth_params)
        items = self._list_children(session, auth_params, folder_id)

        # 兼容“当月入职周年海报”下再按月份建立一层文件夹的结构。
        child_folders = [item for item in items if item.get("mimeType") == FOLDER_MIME]
        if child_folders:
            nested = self._list_children(session, auth_params, child_folders[0]["id"])
            if nested:
                items = nested + items

        info_files = [
            item for item in items
            if item.get("mimeType") != FOLDER_MIME
            and any(
                keyword in item.get("name", "")
                for keyword in ("入职信息", "周年祝贺")
            )
        ]
        if not info_files:
            raise FileNotFoundError("当月入职周年海报文件夹中未找到入职信息/周年祝贺文件")
        info_file = info_files[0]
        info_text = self._download_text(session, auth_params, info_file)
        names = names_from_anniversary_trigger(trigger_text, info_text)
        if not names:
            raise LookupError("入职信息文件中未匹配到提醒消息里的花名")

        results = []
        for name in names:
            greeting = extract_anniversary_greeting(info_text, name)
            if not greeting:
                raise LookupError(f"入职信息文件中未找到{name}的周年祝贺")
            posters = [
                item for item in items
                if item.get("mimeType") != FOLDER_MIME
                and name in item.get("name", "")
                and (
                    item.get("mimeType", "").startswith("image/")
                    or item.get("name", "").lower().endswith((".jpg", ".jpeg", ".png", ".webp"))
                )
            ]
            if not posters:
                raise FileNotFoundError(f"未找到{name}的周年海报")
            poster = posters[0]
            results.append({
                "name": name,
                "greeting": greeting,
                "poster": self._download_bytes(session, auth_params, poster),
                "poster_file_id": poster["id"],
            })
        return results, info_file
