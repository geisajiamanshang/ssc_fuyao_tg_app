# -*- coding: utf-8 -*-
"""联合管理群出现【入职信息确认】后，把其中的"候选人编码"写进花名册（机器人）
表的D列：按"候选人姓名"在C列找到该员工已有的行，只填这一格，不新增行、不
覆盖已有的不同编码。"""

import re
import unicodedata
from urllib.parse import quote

from daily_reports import _drive_session

SHEETS_API_URL = "https://sheets.googleapis.com/v4/spreadsheets"
SHEETS_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
)
NATIVE_SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
_WS_RE = re.compile(r"\s+")


def normalize_name(value):
    return _WS_RE.sub("", unicodedata.normalize("NFKC", value or "")).casefold()


def normalize_code(value):
    return _WS_RE.sub("", unicodedata.normalize("NFKC", value or "")).upper()


def plan_code_write(rows, name, code, name_col_index, code_col_index):
    """rows为整张表按行的二维列表（第1行是表头）。返回 (status, row_number)：
    status ∈ written_new / already_set / name_not_found / ambiguous / conflict。
    row_number是1开始的表格行号；仅 written_new 需要真正写入。"""
    target = normalize_name(name)
    matches = []
    for index, row in enumerate(rows[1:], start=2):
        cell_name = row[name_col_index] if len(row) > name_col_index else ""
        if target and normalize_name(cell_name) == target:
            existing = row[code_col_index] if len(row) > code_col_index else ""
            matches.append((index, (existing or "").strip()))
    if not matches:
        return "name_not_found", None
    wanted = normalize_code(code)
    if any(normalize_code(existing) == wanted for _row, existing in matches):
        row_number = next(r for r, e in matches if normalize_code(e) == wanted)
        return "already_set", row_number
    empty = [r for r, existing in matches if not existing]
    if len(matches) == 1:
        return ("written_new", empty[0]) if empty else ("conflict", matches[0][0])
    if len(empty) == 1:
        return "written_new", empty[0]
    return "ambiguous", None


def column_index(letter):
    index = 0
    for char in letter.upper():
        index = index * 26 + (ord(char) - 64)
    return index - 1


class RosterCodeRepository:
    def __init__(self, spreadsheet_id, sheet_gid, name_column="C", code_column="D"):
        self.spreadsheet_id = spreadsheet_id
        self.sheet_gid = int(sheet_gid)
        self.name_column = name_column
        self.code_column = code_column

    def _sheet_title(self, session, auth_params):
        response = session.get(
            f"{SHEETS_API_URL}/{self.spreadsheet_id}",
            params={**auth_params, "fields": "sheets.properties(sheetId,title)"},
            timeout=30,
        )
        if response.status_code == 400 and "not supported for this document" in response.text:
            raise ValueError("花名册（机器人）不是Google表格（可能是上传的xlsx），请先转换成Google表格")
        response.raise_for_status()
        for sheet in response.json().get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("sheetId") == self.sheet_gid:
                return props["title"]
        raise FileNotFoundError(f"花名册（机器人）里没有gid={self.sheet_gid}的工作表")

    def write_code(self, name, code):
        """返回 (status, row_number)，status见 plan_code_write。"""
        session, auth_params = _drive_session(scopes=SHEETS_SCOPES, need_write=True)
        title = self._sheet_title(session, auth_params)
        quoted = "'" + title.replace("'", "''") + "'"
        response = session.get(
            f"{SHEETS_API_URL}/{self.spreadsheet_id}/values/{quote(quoted + '!A:AZ', safe='')}",
            params={**auth_params, "majorDimension": "ROWS"}, timeout=60,
        )
        response.raise_for_status()
        rows = response.json().get("values", [])
        status, row_number = plan_code_write(
            rows, name, code,
            column_index(self.name_column), column_index(self.code_column),
        )
        if status != "written_new":
            return status, row_number
        cell = f"{quoted}!{self.code_column}{row_number}"
        update = session.put(
            f"{SHEETS_API_URL}/{self.spreadsheet_id}/values/{quote(cell, safe='')}",
            params={**auth_params, "valueInputOption": "RAW"},
            json={"values": [[code.strip()]]}, timeout=30,
        )
        update.raise_for_status()
        return status, row_number
