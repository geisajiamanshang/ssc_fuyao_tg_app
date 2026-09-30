# -*- coding: utf-8 -*-
"""帐号申请自动化：SSC收藏夹出现"帐号申请"后，读取"花名册"和"花名册（机器
人）"两张在线Google表格，找出生效日期>=cutover_date（不论部门）且距今>=
min_days天（默认6天）、但工作TG(AD列)还没换成真正工作TG的人——具体表现为
AD列空白、填的是"同上"这类占位文字、或者跟私人联系方式(AE列)完全相同，
按部门套用不同理由和不同的消息格式，分别生成账号申请草稿。

纯逻辑（两表合并/筛选/理由判断/文案拼装）单独放在这里，不涉及Telegram
调用，方便独立测试；Drive/Sheets读取复用service_account凭证，只是比
daily_reports.py里其它功能用的drive.readonly多加了spreadsheets.readonly
这一个权限范围（读取指定gid对应的分页，需要Sheets API v4，Drive的CSV
导出接口不支持按gid选分页）。

两种消息格式照抄"帐号申请助手/模版.rtf"里对应部门类型的真实历史例子：
研发部/效能部用【员工账号申请】格式，其他部门用【员工工作帐号申请】格式，
"申请原因"按account_application_reason()的判断结果填入，不是照抄例子里的
原文。
"""

from datetime import datetime

# 花名册两张表的字段位置（电子表格列字母），两表结构完全一致：正文表头在
# 第3行（前两行是"在职花名册"标题行和分组表头），从第4行开始是数据。
ROSTER_HEADER_ROW_INDEX = 2  # 0-based：第3行
ROSTER_DATA_START_INDEX = 3  # 0-based：第4行开始是数据

ROSTER_FIELD_COLUMNS = {
    "employee_code": "B",   # 员工编码（新）
    "name": "C",             # 花名*
    "resume_name": "D",      # 姓名/简历名（选填）
    "effective_date_raw": "F",  # 生效日期（入/调）
    "org_unit": "L",         # 编制组织*（运营中心/技术中心/效能中心……）
    "service_unit": "N",     # 服务单位*（一般是"恒睿"）
    "department": "O",       # 部门*（研发部/效能部/运营1部……）
    "work_tg": "AD",         # 工作TG
    "personal_contact": "AE",  # 私人联系方式（选填）
}

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


def _cell(row, index):
    if index >= len(row):
        return ""
    value = row[index]
    return value.strip() if isinstance(value, str) else ("" if value is None else str(value))


def parse_roster_rows(rows, *, columns=ROSTER_FIELD_COLUMNS,
                       data_start_index=ROSTER_DATA_START_INDEX):
    """把Sheets API返回的行列表（每行是单元格值的list）解析成候选人字典
    列表：跳过标题/分组表头/字段表头这几行，姓名为空的行也跳过。列位置用
    电子表格列字母指定，不依赖表头文字，因为两张表的表头未必逐字一致。
    """
    col_indexes = {field: _col_index(letter) for field, letter in columns.items()}
    candidates = []
    for row in rows[data_start_index:]:
        name = _cell(row, col_indexes["name"])
        if not name:
            continue
        candidate = {field: _cell(row, idx) for field, idx in col_indexes.items()}
        candidates.append(candidate)
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


# 工作TG(AD列)填的是这些占位文字之一，跟留空一样表示"还没申请"——花名册
# 里有些人直接写"同上"表示跟私人联系方式(AE列)一样，而不是真的重复填一遍。
_PLACEHOLDER_WORK_TG_MARKERS = ("同上",)


def needs_account_application(candidate):
    """工作TG(AD)还没换成真正的工作TG——具体表现为以下任意一种：完全空白、
    填的是"同上"这类占位文字、或者跟私人联系方式(AE)完全相同（说明只是
    把AE抄了一遍占位）。工作TG已经填了具体的、跟AE不同的内容，才认为已经
    申请过，不处理。是否在本次自动化处理范围内（生效日期>=cutover_date
    且距今>=min_days天）由account_application_reason()单独判断，这里不
    判断生效日期。
    """
    work_tg = (candidate.get("work_tg") or "").strip()
    if not work_tg:
        return True
    if any(marker in work_tg for marker in _PLACEHOLDER_WORK_TG_MARKERS):
        return True
    personal_contact = (candidate.get("personal_contact") or "").strip()
    if not personal_contact:
        return False
    return work_tg == personal_contact


def is_tech_department(candidate, *, tech_departments):
    """O列（部门）包含"研发部"或"效能部"，对应"技术中心/效能中心模版"这一
    档；其余部门对应"运营中心模版"这一档。"""
    department = candidate.get("department") or ""
    return any(keyword in department for keyword in tech_departments)


def account_application_reason(candidate, today, *, tech_departments, cutover_date, min_days=6):
    """不论部门，必须同时满足两个日期条件才处理：F列生效日期>=cutover_date
    （早于这个日期的历史存量不在本次自动化范围内），且生效日期距今>=
    min_days天（刚生效没多久，HR/员工本人可能还没来得及配置工作TG，先不
    打扰）。都满足后，研发部/效能部理由固定"新人入职工作需要"，其他部门
    理由是"新人入职满7天"；不满足任一条件返回None，表示本次不处理这个人。
    """
    effective = candidate.get("effective_date")
    if effective is None or effective < cutover_date:
        return None
    if (today - effective).days < min_days:
        return None
    if is_tech_department(candidate, tech_departments=tech_departments):
        return "新人入职工作需要"
    return "新人入职满7天"


def _contact_tg(candidate):
    contact = (candidate.get("personal_contact") or "").strip()
    if not contact:
        return "待补充"
    return contact if contact.startswith("@") else "@" + contact.lstrip("@")


def build_account_application_text(candidate, reason, *, is_tech, today=None):
    """按"帐号申请助手/模版.rtf"里对应部门类型的真实格式拼草稿文本：
    研发部/效能部用【员工账号申请】格式（申请日期在最前面，多一个"简历名"
    字段）；其他部门用【员工工作帐号申请】格式（多一个"申请数量"字段，
    申请日期在最后）。"需求"统一填"TG×1"，因为这个自动化本身就是在补
    工作TG这一项；"申请原因"用account_application_reason()的判断结果，
    不是照抄模版例子里的原文。
    """
    today = today or datetime.now().date().isoformat()
    org_unit = candidate.get("org_unit") or "待补充"
    service_unit = candidate.get("service_unit") or "恒睿"
    department = candidate.get("department") or "待补充"
    name = candidate.get("name") or "待补充"
    resume_name = candidate.get("resume_name") or name
    employee_code = candidate.get("employee_code") or "待补充"
    contact_tg = _contact_tg(candidate)

    if is_tech:
        return (
            "【员工账号申请】\n\n"
            f"申请日期：{today}\n"
            f"编制组织：{org_unit}\n"
            f"服务单位：{service_unit}\n"
            f"编号：{employee_code}\n"
            f"花名：{name}\n"
            f"简历名：{resume_name}\n"
            "需求：TG×1\n"
            f"申请原因：{reason}\n"
            f"联系TG：{contact_tg}"
        )
    return (
        "【员工工作帐号申请】\n\n"
        f"编制组织：{org_unit}\n"
        f"服务公司：{service_unit}\n"
        f"部门：{department}\n"
        f"花名：{name}\n"
        f"员工编号：{employee_code}\n"
        "需求：TG×1\n"
        f"申请原因：{reason}\n"
        "申请数量：1个\n"
        f"联系TG：{contact_tg}\n"
        f"申请日期：{today}"
    )


SHEETS_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
)


class AccountApplicationSheetsRepository:
    """"花名册"/"花名册（机器人）"两张在线Google表格的读取：按配置好的
    spreadsheet_id+gid精确定位分页（哪怕分页被改名也能找到），用Sheets
    API v4读取整页数据。
    """

    def __init__(self, roster_spreadsheet_id, roster_gid,
                 roster_bot_spreadsheet_id, roster_bot_gid):
        self.roster_spreadsheet_id = roster_spreadsheet_id
        self.roster_gid = roster_gid
        self.roster_bot_spreadsheet_id = roster_bot_spreadsheet_id
        self.roster_bot_gid = roster_bot_gid

    @staticmethod
    def _session():
        import os

        credentials_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        if not credentials_path:
            raise RuntimeError(
                "未配置 GOOGLE_APPLICATION_CREDENTIALS：读取花名册在线表格"
                "需要服务账号凭证（Sheets API不支持仅用API key访问私有表格）"
            )
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2 import service_account

        credentials = service_account.Credentials.from_service_account_file(
            credentials_path, scopes=list(SHEETS_SCOPES)
        )
        return AuthorizedSession(credentials)

    @staticmethod
    def _resolve_sheet_title(session, spreadsheet_id, gid):
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
        response = session.get(url, params={"fields": "sheets.properties"}, timeout=30)
        response.raise_for_status()
        for sheet in response.json().get("sheets", []):
            props = sheet.get("properties", {})
            if props.get("sheetId") == gid:
                return props["title"]
        raise FileNotFoundError(
            f"表格{spreadsheet_id}里没有找到gid={gid}对应的分页，"
            "可能分页被删除或gid配置错了"
        )

    @classmethod
    def _fetch_rows(cls, session, spreadsheet_id, gid):
        sheet_title = cls._resolve_sheet_title(session, spreadsheet_id, gid)
        escaped_title = sheet_title.replace("'", "''")
        url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}"
            f"/values/'{escaped_title}'!A1:AZ5000"
        )
        response = session.get(url, timeout=60)
        response.raise_for_status()
        return response.json().get("values", [])

    def load_rosters(self):
        """返回 ("花名册"的行列表, "花名册（机器人）"的行列表)，每行是单元
        格值的list（Sheets API原样返回，行尾空单元格会被省略）。"""
        session = self._session()
        primary_rows = self._fetch_rows(session, self.roster_spreadsheet_id, self.roster_gid)
        secondary_rows = self._fetch_rows(
            session, self.roster_bot_spreadsheet_id, self.roster_bot_gid
        )
        return primary_rows, secondary_rows
