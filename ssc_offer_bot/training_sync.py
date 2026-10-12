# -*- coding: utf-8 -*-
"""场景十三：SSC在自己的收藏夹发带"培训"关键词的消息，触发：按花名册
（机器人）AR列日期筛出"明天"要培训的人（AR列本身存的就是这个人要参加
培训那一天的日期，不是入职日期；筛出来以后，"入职时间"就按这个AR列
日期原样填，不再单独取别的入职日期列），按编制组织(M列)分组生成
【次日培训信息同步】草稿发到收藏夹，经审批码14（测试14）放行到共享
服务中心-远程培训沟通群。

跟roster_code.py读写候选人编码用的是同一张"花名册（机器人）"表格——
表头只占1行（第1行），数据从第2行开始，跟account_application.py那两张
"花名册"/"花名册（机器人）"（表头占3行，从第4行开始是数据，列位置也
不一样）不是同一张表，列位置不能照搬account_application.py的
ROSTER_FIELD_COLUMNS。列位置（电子表格列字母，SSC本人核对过）：
简历名=E，编制组织=M，部门=P，岗位=U，培训日期=AR。"服务单位"这张表
没有单独列，固定写"恒睿"，复用daily_sync.py当日人事信息数据同步已有
的DAILY_SYNC_COMPANY_LABEL；分组顺序复用DAILY_SYNC_CENTER_ORDER。

纯逻辑（列解析/按日期筛选/分组拼文案）单独放在这里，不涉及Telegram
调用，方便独立测试；Google Sheets读取复用daily_reports._drive_session，
只读不写，所以只申请drive.readonly + spreadsheets.readonly两个权限
范围。
"""

from datetime import datetime
from urllib.parse import quote

TRAINING_SYNC_HEADER = "【次日培训信息同步】"

TRAINING_FIELD_COLUMNS = {
    "name": "E",                 # 简历名
    "org_unit": "M",             # 编制组织
    "department": "P",           # 部门
    "position": "U",             # 岗位
    "training_date_raw": "AR",   # 培训日期（= 输出里的"入职时间"，原样展示）
}

# 花名册（机器人）培训日期列可能被Sheets渲染成这几种常见格式，都尝试一遍；
# 都不匹配就跳过这一行，不让整批因为一行格式异常而崩掉。
_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日")

# 表头只占1行，数据从第2行（0-based下标1）开始——跟roster_code.py里
# plan_code_write()对这张表的假设（rows[1:]是数据）一致。
ROSTER_DATA_START_INDEX = 1


def _col_index(letter):
    """把电子表格列字母（E、M、AR……）转换成从0开始的下标。"""
    index = 0
    for ch in letter.strip().upper():
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return index - 1


def _cell(row, index):
    if index >= len(row):
        return ""
    value = row[index]
    return value.strip() if isinstance(value, str) else ("" if value is None else str(value))


def parse_training_date(raw):
    """尝试按常见格式解析花名册AR列培训日期单元格文本，失败返回None。"""
    raw = (raw or "").strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def parse_training_roster_rows(rows, *, columns=TRAINING_FIELD_COLUMNS,
                                data_start_index=ROSTER_DATA_START_INDEX):
    """把Sheets API返回的行列表（每行是单元格值的list）解析成人员字典
    列表：跳过表头行，简历名(E列)为空的行也跳过。列位置用电子表格列字母
    指定，不依赖表头文字。
    """
    col_indexes = {field: _col_index(letter) for field, letter in columns.items()}
    people = []
    for row in rows[data_start_index:]:
        name = _cell(row, col_indexes["name"])
        if not name:
            continue
        person = {field: _cell(row, idx) for field, idx in col_indexes.items()}
        people.append(person)
    return people


def select_people_for_date(people, target_date):
    """按AR列(training_date_raw)解析出的日期筛出恰好等于target_date的人；
    解析失败（格式不认识/空白）的行静默跳过，不报错整批失败。"""
    selected = []
    for person in people:
        if parse_training_date(person.get("training_date_raw")) == target_date:
            selected.append(person)
    return selected


def build_training_sync_report(people, center_order, company_label, date_str):
    """people是select_people_for_date()已经筛出的、这次报告里要出现的人。
    按编制组织(org_unit)分组：组的先后顺序先按center_order排列（当天没人
    匹配到的编制组织不出现——跟daily_sync.py那边"永远列出全部中心"的习惯
    不一样），center_order里没有的编制组织按花名册里第一次出现的顺序追加
    在最后。date_str是筛选用的那个目标日期（所有人共用同一个"明天"），
    直接当"入职时间"填，不再单独取每个人自己AR列的原始文本（避免因为
    单元格格式不一致导致同一份报告里日期写法不统一）。
    """
    grouped = {}
    first_seen_order = []
    for person in people:
        center = person.get("org_unit") or "待补充"
        if center not in grouped:
            grouped[center] = []
            first_seen_order.append(center)
        grouped[center].append(person)

    ordered_centers = [c for c in center_order if c in grouped]
    ordered_centers += [c for c in first_seen_order if c not in center_order]

    blocks = []
    for center in ordered_centers:
        members = grouped[center]
        lines = [f"{center}-{company_label} {len(members)}人"]
        for index, person in enumerate(members):
            if index > 0:
                lines.append("")  # 同一组内，人与人之间空一行；表头和第一个人之间不空行。
            lines.append(
                f"入职时间：{date_str}\n"
                f"岗位：{person.get('position') or '待补充'}\n"
                f"部门：{person.get('department') or '待补充'}\n"
                f"简历名：{person.get('name') or '待补充'}"
            )
        blocks.append("\n".join(lines))
    return TRAINING_SYNC_HEADER + "\n\n" + "\n\n".join(blocks)


SHEETS_API_URL = "https://sheets.googleapis.com/v4/spreadsheets"
SHEETS_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
)


class TrainingSyncRosterRepository:
    """花名册（机器人）的只读访问：按配置好的spreadsheet_id+gid精确定位
    分页（哪怕分页被改名也能找到），用Sheets API v4读取A:AZ整列范围
    （AR列在第44列，落在这个范围内）。"""

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
            props = sheet.get("properties", {})
            if props.get("sheetId") == self.sheet_gid:
                return props["title"]
        raise FileNotFoundError(f"花名册（机器人）里没有gid={self.sheet_gid}的工作表")

    def load_rows(self):
        """返回整张表按行的二维列表（Sheets API原样返回，行尾空单元格
        会被省略），交给parse_training_roster_rows()解析。"""
        from daily_reports import _drive_session

        session, auth_params = _drive_session(scopes=SHEETS_SCOPES)
        title = self._sheet_title(session, auth_params)
        quoted = "'" + title.replace("'", "''") + "'"
        response = session.get(
            f"{SHEETS_API_URL}/{self.spreadsheet_id}/values/{quote(quoted + '!A:AZ', safe='')}",
            params={**auth_params, "majorDimension": "ROWS"}, timeout=60,
        )
        response.raise_for_status()
        return response.json().get("values", [])
