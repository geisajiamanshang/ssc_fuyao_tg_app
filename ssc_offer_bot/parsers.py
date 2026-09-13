# -*- coding: utf-8 -*-
"""
文本解析工具。

约定：消息里的结构化信息都是"字段名：值"，每个字段单独占一行，例如：

    候选人姓名：叶蓝栩
    编制组织：运营中心
    职位：运营专员
    转正薪资：16K

parse_kv_fields() 会把这样的文本解析成一个 dict，供后续拼接新消息使用。
"""

import re


def is_offer_message(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).casefold()
    return (("【offer】" in compact and "附件简历" in compact)
            or "【offer信息确认】" in compact
            or "候选人编码" in compact or "候选人姓名" in compact)


def offer_header_org(text: str) -> str:
    match = re.match(r"^\s*([^\n【]+?)\s*【\s*offer\s*信息确认\s*】", text, re.I)
    return match.group(1).strip() if match else ""


def is_approval(text: str) -> bool:
    value = text.strip().casefold().strip("。.!！ ")
    return value in {"好的", "好", "ok", "okay", "同意", "通过", "批准", "审批通过", "同意通过", "可以", "没问题", "收到，同意", "收到,同意"}

# 字段名允许中文/英文/数字/下划线/斜杠，长度限制避免误把正文长句当成字段名
_FIELD_PATTERN = re.compile(r"^\s*(?:[0-9０-９]+\s*[.．、)）]\s*)?([\u4e00-\u9fa5A-Za-z0-9_/]{1,20}?)[:：]\s*(.+?)\s*$")


def parse_kv_fields(text: str) -> dict:
    """按行解析 "字段名：值" 格式的文本，返回 dict。"""
    fields = {}
    if not text:
        return fields
    for line in text.splitlines():
        m = _FIELD_PATTERN.match(line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key and val:
                fields[key] = val
    return fields


def get_field(fields: dict, *keys, default: str = "") -> str:
    """
    按多个可能的字段名依次查找，返回第一个命中的值。
    例如同一个意思有的地方写"职位"，有的地方写"应聘岗位"，
    用 get_field(fields, "职位", "应聘岗位") 都能取到。
    """
    for k in keys:
        v = fields.get(k)
        if v:
            return v
    return default


def strip_header_footer(text: str) -> str:
    """删除原始或重复的Offer标题，以及末尾的审批请求。"""
    t = (text or "").strip()
    header = r"^(?:【\s*offer\s*】\s*\+?\s*附件简历\s*[:：]?|[^\n【]*【\s*offer\s*信息确认\s*】)\s*"
    while True:
        cleaned = re.sub(header, "", t, count=1, flags=re.I)
        if cleaned == t:
            break
        t = cleaned.strip()
    footer = r"(?:^|\n)[ \t]*(?:@ffuuyao\b[^\n]*|@[A-Za-z0-9_]+[^\n]*?(?:请\s*(?:领导\s*)?审批|麻烦\s*跟进\s*offer\s*审批)[^\n]*)\s*$"
    while True:
        cleaned = re.sub(footer, "", t, count=1, flags=re.I)
        if cleaned == t:
            break
        t = cleaned.strip()
    return t
