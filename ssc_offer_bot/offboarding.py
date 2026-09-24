# -*- coding: utf-8 -*-
"""恒睿公司-联合管理群出现"劝退申请"/"离职申请"关键词后，从Drive云端 离职助手/
输出 文件夹按员工姓名查找该员工的《XX_离职信息同步.txt》，并把文件内容按
【段落名】拆成四类，分别经各自审批码放行到不同目的地：

  81 -> 离职确认信息转发到联合管理群
  82 -> 薪水结算信息私发给员工本人的工作TG
  83 -> 离职信息同步一次性转发到 人事数据同步-SSC3组 和 北斗离职人员-同步商务中心群
  84 -> 员工帐号回收信息发送到 工作帐号需求群-SSC3组

文件里出现的其它分区（不属于以上四类）作为参考资料，原样分条发到收藏夹，
不设审批码，与新人培训入职信息的处理方式一致。
"""

import re
from datetime import datetime

from daily_reports import DRIVE_FILES_URL, _drive_session
from parsers import parse_kv_fields, get_field


OFFBOARDING_TRIGGER_KEYWORDS = ("劝退申请", "离职申请")

_NAME_FIELD_RE = re.compile(r"(?:花名|姓名|候选人姓名)\s*[:：]\s*([^\s,，;；]+)")
_NAME_AFTER_KEYWORD_RE = re.compile(r"(?:劝退申请|离职申请)\s*[:：]\s*([^\s，,。;；\n]{1,10})")
_NAME_BEFORE_KEYWORD_RE = re.compile(
    r"(?:对|针对)?\s*([^\s，,。:：；;【】@]{1,10}?)\s*(?:的|提出|发起)?\s*(?:劝退|离职)申请"
)

# 分区角色判定关键词；SECTION_ROLE_ORDER 的顺序很重要——"离职信息同步"这个
# 分区名本身含"息"字，但不应被更宽泛的规则误判，所以更具体的角色先判定。
SECTION_ROLE_HINTS = {
    "account_reclaim": ("账号回收", "帐号回收", "回收"),
    "salary": ("薪资", "薪水", "结算"),
    "sync": ("同步",),
    "forward": ("确认",),
}
SECTION_ROLE_ORDER = ("account_reclaim", "salary", "sync", "forward")

_WS_RE = re.compile(r"[\s_\-—]+")


def _normalized(value):
    return _WS_RE.sub("", value or "").casefold()


def _escape_query(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def matches_offboarding_keyword(text):
    return any(keyword in (text or "") for keyword in OFFBOARDING_TRIGGER_KEYWORDS)


def extract_offboarding_name(text):
    """从劝退/离职申请消息里提取员工姓名：优先"花名/姓名"字段，
    其次"离职申请：XX"，最后"对XX的离职申请"这类紧邻关键词的写法。"""
    text = text or ""
    match = _NAME_FIELD_RE.search(text)
    if match:
        return match.group(1).strip()
    match = _NAME_AFTER_KEYWORD_RE.search(text)
    if match:
        return match.group(1).strip()
    match = _NAME_BEFORE_KEYWORD_RE.search(text)
    if match:
        return match.group(1).strip()
    return ""


def classify_offboarding_sections(sections):
    """把【段落名】分区按角色归类为 forward/salary/sync/account_reclaim，
    一个分区只归入一个角色，先到先得。未命中任何角色的分区原样作为参考
    资料随 reference 列表返回，保持在文件中出现的顺序。"""
    by_role = {}
    reference = []
    for name, body in sections:
        if not body:
            continue
        role = None
        for candidate_role in SECTION_ROLE_ORDER:
            if candidate_role in by_role:
                continue
            if any(hint in name for hint in SECTION_ROLE_HINTS[candidate_role]):
                role = candidate_role
                break
        if role:
            by_role[role] = (name, body)
        else:
            reference.append((name, body))
    return by_role, reference


def extract_offboarding_contact_tg(text):
    """从离职信息同步文件全文里找员工本人的工作TG，用于代发薪水结算信息。"""
    fields = parse_kv_fields(text or "")
    value = get_field(fields, "工作TG", "联系TG", "候选人联系方式", "TG", "Telegram")
    value = (value or "").strip()
    if not value:
        return ""
    return value if value.startswith("@") else "@" + value.lstrip("@")


def build_account_reclaim_text(name, fields, today=None):
    """离职信息文件里没有单独的"账号回收"分区时，退而用已知字段拼一份最小
    的【员工帐号回收】通知，缺失字段填"待补充"，不假装信息完整。"""
    today = today or datetime.now().strftime("%Y-%m-%d")
    org_unit = get_field(fields, "编制组织") or "待补充"
    code = get_field(fields, "编号") or "待补充"
    display_name = get_field(fields, "花名") or (name or "").strip() or "待补充"
    return (
        "【员工帐号回收】\n\n"
        f"申请日期：{today}\n"
        f"编制组织：{org_unit}\n"
        f"编号：{code}\n"
        f"花名：{display_name}\n"
        "需求：回收该员工的工作帐号/TG号/工作邮箱\n"
        "申请原因：员工离职"
    )


class OffboardingDriveRepository:
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
        response = session.get(
            f"{DRIVE_FILES_URL}/{drive_file['id']}",
            params={**auth_params, "alt": "media"}, timeout=120,
        )
        response.raise_for_status()
        raw = response.content
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            raise ValueError(
                "离职信息文件编码无法识别，请将 TXT 保存为 UTF-8 后重试"
            ) from exc
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def _candidate_files(self, session, auth_params, limit=30):
        """输出文件夹下既可能直接放TXT，也可能按日期/月份子文件夹存放；
        两种结构都收集，按修改时间倒序，最近修改的文件优先匹配。"""
        folder_mime = "application/vnd.google-apps.folder"
        top_level = self._list_children(session, auth_params, self.output_folder_id)
        candidates = [
            item for item in top_level
            if item.get("mimeType") != folder_mime
            and item.get("name", "").lower().endswith(".txt")
        ]
        subfolders = sorted(
            (item for item in top_level if item.get("mimeType") == folder_mime),
            key=lambda item: item.get("modifiedTime", ""), reverse=True,
        )
        for subfolder in subfolders[:5]:
            children = self._list_children(session, auth_params, subfolder["id"])
            candidates.extend(
                item for item in children
                if item.get("mimeType") != folder_mime
                and item.get("name", "").lower().endswith(".txt")
            )
        candidates.sort(key=lambda item: item.get("modifiedTime", ""), reverse=True)
        return candidates[:limit]

    def find_by_name(self, name):
        """按"员工名字_离职信息同步.txt"命名约定查找该员工的离职信息全文。"""
        target = (name or "").strip()
        if not target:
            raise ValueError("员工姓名为空，无法查找")
        session, auth_params = _drive_session()
        normalized_target = _normalized(target)
        for drive_file in self._candidate_files(session, auth_params):
            file_name = drive_file.get("name", "")
            if (normalized_target and normalized_target in _normalized(file_name)
                    and "离职信息同步" in file_name):
                return self._download_text(session, auth_params, drive_file), drive_file
        raise FileNotFoundError(f"离职助手/输出文件夹中未找到{target}的离职信息同步文件")


class OffboardingApprovalFormRepository:
    """检查 离职流程 Drive 文件夹（drive.google.com/drive/u/1/folders/...）下
    当月离职明细 子文件夹中，是否已经有该员工的《XX_员工离职审批表》。这一步
    与 OffboardingDriveRepository 查的不是同一个文件夹，找不到不算异常——
    审批表可能还没上传，交由SSC人工核实，不阻塞其余三项信息的处理。"""

    def __init__(self, process_folder_id):
        self.process_folder_id = process_folder_id

    @staticmethod
    def _list_children(session, auth_params, folder_id):
        params = {
            **auth_params,
            "q": f"'{_escape_query(folder_id)}' in parents and trashed = false",
            "fields": "files(id,name,mimeType,modifiedTime)",
            "orderBy": "modifiedTime desc",
            "pageSize": 100,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        response = session.get(DRIVE_FILES_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get("files", [])

    def find_approval_form_link(self, name):
        """返回该员工《离职审批表》的云端查看链接；当月离职明细文件夹不存在，
        或里面没有匹配到该员工的文件时返回 None。"""
        target = (name or "").strip()
        if not target or not self.process_folder_id:
            return None
        folder_mime = "application/vnd.google-apps.folder"
        session, auth_params = _drive_session()
        top_level = self._list_children(session, auth_params, self.process_folder_id)
        month_folder = next(
            (item for item in top_level
             if item.get("mimeType") == folder_mime and "当月离职明细" in item.get("name", "")),
            None,
        )
        if not month_folder:
            return None
        normalized_target = _normalized(target)
        for item in self._list_children(session, auth_params, month_folder["id"]):
            file_name = item.get("name", "")
            if (item.get("mimeType") != folder_mime
                    and normalized_target in _normalized(file_name)
                    and "离职审批表" in file_name):
                return f"https://drive.google.com/file/d/{item['id']}/view"
        return None
