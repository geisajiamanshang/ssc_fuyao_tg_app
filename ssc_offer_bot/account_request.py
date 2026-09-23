# -*- coding: utf-8 -*-
"""SSC主管私聊里出现账号申请类关键词后，识别申请类目、从转发/直接文本里
提取花名，并按查到的入职信息拼出【员工帐号申请】草稿文本。

纯文本逻辑单独放这个模块，不涉及Drive/Telegram调用，方便独立测试；
按花名反查入职信息复用 onboarding_training.OnboardingTrainingDriveRepository
（同一个"入职助手/输出"文件夹，只是查找键从TG用户名换成花名）。
"""

import re
from datetime import datetime

from parsers import get_field


# "外事号"/"外事TG号"/"外事邮箱"/"推特号"/"申请邮箱"/"注册TG"/"注册新TG"/
# "工作帐号"/"工作账号"/"工作TG号"/"工作邮箱" 及其相近说法都算命中。
ACCOUNT_REQUEST_PATTERN = re.compile(
    r"外事\s*(?:号|TG\s*号|邮箱)|推特号|申请\s*邮箱|注册\s*(?:新\s*)?TG|"
    r"工作\s*(?:帐号|账号|TG\s*号|邮箱)",
    re.I,
)
_FORWARD_NAME_SPLIT_RE = re.compile(r"[-－—]")
_DIRECT_NAME_RE = re.compile(r"(?:为|给|帮)\s*(?P<name>[一-鿿]{1,6}?)(?:这边|那边)?\s*申请")

ACCOUNT_REQUEST_DEMAND_TEXT = {
    "外事": "申请外事号/外事TG号/外事邮箱 1个",
    "工作": "申请工作帐号/TG号/工作邮箱 1个",
}


def matches_account_request_keyword(text):
    return bool(ACCOUNT_REQUEST_PATTERN.search(text or ""))


def account_request_category(text):
    """关键词含"外事"归外事类目，其余（推特号/申请邮箱/注册TG等）默认归工作类目。"""
    return "外事" if "外事" in (text or "") else "工作"


def name_from_forward_sender_name(sender_display_name):
    """转发消息原发送者昵称约定为"花名-角色-国家"（如"里昂-HRGS-CN"），取第一段。"""
    if not sender_display_name:
        return ""
    return _FORWARD_NAME_SPLIT_RE.split(sender_display_name.strip(), maxsplit=1)[0].strip()


def name_from_direct_text(text):
    """非转发、SSC主管直接打字时，从"为/给/帮XX申请"里提取花名。"""
    match = _DIRECT_NAME_RE.search(text or "")
    return match.group("name").strip() if match else ""


def _org_unit_from_department(fields):
    department = get_field(fields, "部门-小组")
    if not department:
        return ""
    return department.split("-", 1)[0].strip()


def build_account_request_text(category, fields, today=None):
    """按查到的入职信息字段拼【员工帐号申请】草稿；缺失字段填"待补充"，
    让SSC在收藏夹里能一眼看出哪些还没补全，而不是发出一份看似完整实际
    有假数据的申请。"""
    today = today or datetime.now().strftime("%Y-%m-%d")
    org_unit = get_field(fields, "编制组织") or _org_unit_from_department(fields) or "待补充"
    service_unit = get_field(fields, "服务单位", "北斗矩阵") or "恒睿"
    code = get_field(fields, "编号") or "待补充"
    name = get_field(fields, "花名") or "待补充"
    resume_name = get_field(fields, "简历名") or name
    contact_tg = get_field(fields, "联系TG", "TG", "Telegram")
    if contact_tg and not contact_tg.startswith("@"):
        contact_tg = "@" + contact_tg.lstrip("@")
    contact_tg = contact_tg or "待补充"
    demand = ACCOUNT_REQUEST_DEMAND_TEXT[category]

    return (
        "【员工帐号申请】\n\n"
        f"申请日期：{today}\n"
        f"编制组织：{org_unit}\n"
        f"服务单位：{service_unit}\n"
        f"编号：{code}\n"
        f"花名：{name}\n"
        f"简历名：{resume_name}\n"
        f"需求：{demand}\n"
        "申请原因：工作需要\n"
        f"联系TG：{contact_tg}"
    )
