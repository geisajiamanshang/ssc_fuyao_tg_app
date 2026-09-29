# -*- coding: utf-8 -*-
"""帐号申请自动化：SSC收藏夹出现"帐号申请"后，扫描Drive花名册文件夹下
"花名册"和"花名册（机器人）"两张表，找出已生效满一定天数但仍未申请工作
帐号的人，按部门套用不同理由，套用"帐号申请助手"文件夹下的「帐号申请
模版」分别生成【员工帐号申请】草稿。

纯逻辑（CSV解析/合并/筛选/理由判断/文案拼装）单独放在这里，不涉及
Telegram调用，方便独立测试；Drive读取复用 daily_reports 的会话/下载
机制（服务账号或API key，只需要 drive.readonly 权限），用CSV导出而不是
Sheets API v4读取花名册两张表，避免额外申请 spreadsheets.readonly 权限。
"""

import csv
import io
from datetime import datetime

from daily_reports import DRIVE_FILES_URL, _drive_session

NATIVE_SHEET_MIME_TYPE = "application/vnd.google-apps.spreadsheet"

# 花名册生效日期列可能被Sheets渲染成这几种常见格式，都尝试一遍；都不匹配
# 就返回None，由调用方把这一行标记为跳过，而不是让整个批次因为一行格式
# 异常而崩掉。
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")


def _col_index(letter):
    """把电子表格列字母（A、F、AD……）转换成从0开始的下标。"""
    index = 0
    for ch in letter.strip().upper():
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


def parse_roster_date(raw):
    """尝试按常见格式解析花名册生效日期单元格文本，失败返回None。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_roster_csv(csv_text, *, name_col, date_col, dept_col, status_cols):
    """把花名册CSV正文解析成候选人字典列表：跳过表头行(第一行)和姓名为空
    的行。列位置用电子表格列字母指定(如"C" "F" "O" "AD")而不依赖表头文字，
    因为"花名册"和"花名册（机器人）"两张表的表头未必完全一致。
    """
    name_idx = _col_index(name_col)
    date_idx = _col_index(date_col)
    dept_idx = _col_index(dept_col)
    status_idx = [_col_index(c) for c in status_cols]
    max_idx = max([name_idx, date_idx, dept_idx, *status_idx])

    rows = list(csv.reader(io.StringIO(csv_text or "")))
    candidates = []
    for row in rows[1:]:
        if len(row) <= max_idx:
            continue
        name = row[name_idx].strip()
        if not name:
            continue
        candidates.append({
            "name": name,
            "effective_date_raw": row[date_idx].strip(),
            "department": row[dept_idx].strip(),
            "status_values": [row[i].strip() for i in status_idx],
        })
    return candidates


def merge_rosters(primary_rows, secondary_rows):
    """按姓名合并"花名册"(primary，优先)和"花名册（机器人）"(secondary)两张
    表，同名时以primary为准。返回 (合并后的候选人列表, 两张表都出现过的
    姓名列表)，冲突名单由调用方通知到SSC收藏夹。
    """
    primary_by_name = {row["name"]: row for row in primary_rows}
    secondary_by_name = {row["name"]: row for row in secondary_rows}
    conflicts = sorted(set(primary_by_name) & set(secondary_by_name))
    merged = dict(secondary_by_name)
    merged.update(primary_by_name)
    return list(merged.values()), conflicts


def needs_account_application(candidate, today, *, min_days=6):
    """生效日期与今日相差>=min_days天，且两个状态列(AD/AE)的值不同，说明
    还没申请工作帐号。生效日期解析失败或状态列不全的行一律跳过。
    """
    effective = candidate.get("effective_date")
    if effective is None:
        return False
    if (today - effective).days < min_days:
        return False
    values = candidate.get("status_values") or []
    if len(values) < 2:
        return False
    return values[0] != values[1]


def account_application_reason(candidate, today, *, tech_departments, cutover_date):
    """研发部/效能部固定"新人入职工作需要"；其他部门理由是"新人入职满7
    天"，只对生效日期>=cutover_date起的人生效，返回None表示这个人本次不
    处理（其他部门、生效日期早于cutover_date的历史存量不在本次自动化范围
    内）。
    """
    department = candidate.get("department") or ""
    if any(keyword in department for keyword in tech_departments):
        return "新人入职工作需要"
    effective = candidate.get("effective_date")
    if effective is None or effective < cutover_date:
        return None
    return "新人入职满7天"


def build_account_application_text(candidate, reason, template_text, today=None):
    """把"帐号申请模版"文档原文（原样保留，不猜测占位符写法）和这个人的
    具体字段拼在一起；模版读取失败/为空时退化为固定表头，不影响草稿生成。
    """
    today = today or datetime.now().date().isoformat()
    header = (template_text or "").strip()
    body = (
        f"候选人姓名：{candidate.get('name') or '待补充'}\n"
        f"部门：{candidate.get('department') or '待补充'}\n"
        f"生效日期：{candidate.get('effective_date_raw') or '待补充'}\n"
        f"申请日期：{today}\n"
        f"申请理由：{reason}"
    )
    if header:
        return header + "\n\n" + body
    return "【员工帐号申请】\n\n" + body


class AccountApplicationDriveRepository:
    """花名册两张表(CSV导出)+帐号申请助手文件夹("步骤""帐号申请模版")的
    Drive读取，复用 daily_reports 的Drive会话/下载机制。
    """

    def __init__(self, roster_folder_id, assistant_folder_id):
        self.roster_folder_id = roster_folder_id
        self.assistant_folder_id = assistant_folder_id

    @staticmethod
    def _escape_query(value):
        return (value or "").replace("\\", "\\\\").replace("'", "\\'")

    @classmethod
    def _list_children(cls, session, auth_params, folder_id):
        params = {
            **auth_params,
            "q": f"'{cls._escape_query(folder_id)}' in parents and trashed = false",
            "fields": "files(id,name,mimeType,modifiedTime)",
            "orderBy": "modifiedTime desc",
            "pageSize": 100,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        response = session.get(DRIVE_FILES_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get("files", [])

    @staticmethod
    def _download_csv(session, auth_params, drive_file):
        """花名册需要是Google表格(mimeType为原生表格)才能用export导出CSV；
        如果是上传的xlsx等文件，明确报错而不是让Drive API返回的403看起来
        像别的问题。
        """
        mime_type = drive_file.get("mimeType", "")
        if mime_type != NATIVE_SHEET_MIME_TYPE:
            raise ValueError(
                f"「{drive_file.get('name')}」不是Google表格"
                f"(mimeType={mime_type or '未知'})，暂不支持读取，"
                "请转换成Google表格格式后重试"
            )
        url = f"{DRIVE_FILES_URL}/{drive_file['id']}/export"
        response = session.get(
            url, params={**auth_params, "mimeType": "text/csv"}, timeout=60
        )
        response.raise_for_status()
        return response.content.decode("utf-8-sig")

    @staticmethod
    def _download_text(session, auth_params, drive_file):
        """"步骤"/"帐号申请模版"多半是Google文档，也兼容万一是普通TXT。"""
        mime_type = drive_file.get("mimeType", "")
        if mime_type.startswith("application/vnd.google-apps"):
            url = f"{DRIVE_FILES_URL}/{drive_file['id']}/export"
            params = {**auth_params, "mimeType": "text/plain"}
        else:
            url = f"{DRIVE_FILES_URL}/{drive_file['id']}"
            params = {**auth_params, "alt": "media"}
        response = session.get(url, params=params, timeout=60)
        response.raise_for_status()
        raw = response.content
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        return raw.decode(encoding)

    def load_rosters(self):
        """返回 ("花名册"CSV正文, "花名册（机器人）"CSV正文)；任一张表在
        文件夹里找不到时抛FileNotFoundError，由调用方汇报给SSC。
        """
        session, auth_params = _drive_session()
        children = self._list_children(session, auth_params, self.roster_folder_id)
        primary_file = next(
            (item for item in children if item.get("name", "").strip() == "花名册"), None
        )
        secondary_file = next(
            (item for item in children
             if "花名册" in item.get("name", "") and "机器人" in item.get("name", "")),
            None,
        )
        if not primary_file:
            raise FileNotFoundError("未在花名册文件夹中找到名为「花名册」的表")
        if not secondary_file:
            raise FileNotFoundError("未在花名册文件夹中找到名为「花名册（机器人）」的表")
        primary_csv = self._download_csv(session, auth_params, primary_file)
        secondary_csv = self._download_csv(session, auth_params, secondary_file)
        return primary_csv, secondary_csv

    def load_template(self):
        """帐号申请助手文件夹下查找文件名包含"帐号申请模版"的文档全文。"""
        session, auth_params = _drive_session()
        children = self._list_children(session, auth_params, self.assistant_folder_id)
        drive_file = next(
            (item for item in children if "帐号申请模版" in item.get("name", "")), None
        )
        if not drive_file:
            raise FileNotFoundError("未在帐号申请助手文件夹中找到「帐号申请模版」")
        return self._download_text(session, auth_params, drive_file)
