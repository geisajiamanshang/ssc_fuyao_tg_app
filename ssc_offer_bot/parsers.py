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

# 字段名允许中文/英文/数字/下划线/斜杠，长度限制避免误把正文长句当成字段名
_FIELD_PATTERN = re.compile(r"^\s*([\u4e00-\u9fa5A-Za-z0-9_/]{1,20}?)[:：]\s*(.+?)\s*$")


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
    """
    去掉场景一原始消息的固定开头和结尾，只保留中间正文部分。
    开头："【Offer】+附件简历：" (或 "【Offer】附件简历：" 等接近写法)
    结尾："@某用户名 麻烦跟进offer审批"
    """
    if not text:
        return ""
    t = text.strip()
    t = re.sub(r"^【\s*Offer\s*】\s*\+?\s*附件简历[:：]\s*", "", t)
    t = re.sub(r"@\S+\s*麻烦跟进offer审批\s*$", "", t.strip())
    return t.strip()
