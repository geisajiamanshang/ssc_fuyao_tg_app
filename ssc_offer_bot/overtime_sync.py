# -*- coding: utf-8 -*-
"""加班登记群消息同步到 Google Sheets。"""

import re
import unicodedata
from urllib.parse import quote

from daily_reports import _drive_session

SHEETS_API_URL = "https://sheets.googleapis.com/v4/spreadsheets"
SHEETS_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
)
_LABELS = {
    "工号": "employee_code",
    "部门": "department",
    "花名": "name",
    "加班日期": "date",
    "加班时长": "duration",
    "加班类型": "type",
    "加班原因": "reason",
}
_LINE_RE = re.compile(r"^\s*([^:：]+?)\s*[:：]\s*(.*?)\s*$")


def _normalize_label(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value or ""))


def _split_dates(value):
    """日期区间拆成起止日期；单日日期两列重复填写。"""
    value = (value or "").strip()
    parts = re.split(r"\s*(?:~|～|至|到)\s*", value, maxsplit=1)
    start = parts[0].strip()
    end = parts[1].strip() if len(parts) > 1 else start
    return start, end or start


def parse_overtime_records(text):
    """解析一条消息中的一位或多位加班登记人员。"""
    text = unicodedata.normalize("NFKC", text or "")
    if not all(label in text for label in ("加班日期", "加班时长", "加班类型")):
        return []

    records = []
    current = {}
    active_multiline_field = None

    def finish():
        if (current.get("name") and current.get("date")
                and current.get("duration") and current.get("type")):
            start_date, end_date = _split_dates(current["date"])
            records.append({
                "name": current["name"].strip(),
                "start_date": start_date,
                "end_date": end_date,
                "duration": current["duration"].strip(),
                "reason": "\n".join(current.get("reason_lines", [])).strip(),
            })

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = _LINE_RE.match(line)
        if not match:
            if active_multiline_field == "reason":
                current.setdefault("reason_lines", []).append(line)
            continue

        label = _normalize_label(match.group(1))
        value = match.group(2).strip()
        field = _LABELS.get(label)

        # 每个登记块以“工号”或重复出现的“花名”作为边界。兼容首个非加班
        # 区块（如年假）出现在同一条群消息里的情况。
        if label == "工号" and current.get("name"):
            finish()
            current = {}
        elif label == "花名" and current.get("name"):
            finish()
            current = {}

        if not field:
            active_multiline_field = None
            continue
        if field == "reason":
            current["reason_lines"] = [value] if value else []
            active_multiline_field = "reason"
        else:
            current[field] = value
            active_multiline_field = None

    finish()
    return records


class OvertimeSheetsRepository:
    def __init__(self, spreadsheet_id, sheet_gid):
        self.spreadsheet_id = spreadsheet_id
        self.sheet_gid = int(sheet_gid)

    def _sheet_title(self, session, auth_params):
        response = session.get(
            f"{SHEETS_API_URL}/{self.spreadsheet_id}",
            params={**auth_params, "fields": "sheets.properties(sheetId,title)"},
            timeout=30,
        )
        response.raise_for_status()
        for sheet in response.json().get("sheets", []):
            properties = sheet.get("properties", {})
            if properties.get("sheetId") == self.sheet_gid:
                return properties["title"]
        raise FileNotFoundError(
            f"加班登记表中没有gid={self.sheet_gid}的工作表"
        )

    def append_records(self, records):
        """将一条Telegram消息中的多名员工一次性追加到指定工作表。"""
        if not records:
            return 0
        session, auth_params = _drive_session(
            scopes=SHEETS_SCOPES, need_write=True
        )
        title = self._sheet_title(session, auth_params)
        quoted_title = "'" + title.replace("'", "''") + "'"
        values = []
        for record in records:
            row = [""] * 12
            row[4] = record["name"]          # E：花名
            row[6] = record["start_date"]    # G：加班开始日期
            row[7] = record["end_date"]      # H：加班结束日期
            row[8] = record["duration"]      # I：加班时长
            row[11] = record["reason"]       # L：加班原因
            values.append(row)

        append_range = quote(f"{quoted_title}!A:L", safe="")
        response = session.post(
            f"{SHEETS_API_URL}/{self.spreadsheet_id}/values/{append_range}:append",
            params={
                **auth_params,
                "valueInputOption": "USER_ENTERED",
                "insertDataOption": "INSERT_ROWS",
            },
            json={"majorDimension": "ROWS", "values": values},
            timeout=60,
        )
        response.raise_for_status()
        return len(values)
