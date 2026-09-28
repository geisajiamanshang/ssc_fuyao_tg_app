# -*- coding: utf-8 -*-
"""
当日人事信息数据同步：把"人事数据同步-SSC3组"里当天本账号发出的
【入职信息同步】【转正信息同步】【离职信息同步】【人员异动信息同步】
消息，按所属中心归类、计数，拼成两份汇总消息（详细版 / 无详情版）。

【入职信息同步】【转正信息同步】不带"编制组织"字段，只带"部门-小组"，
要靠 DAILY_SYNC_CENTER_DEPARTMENT_KEYWORDS 倒推所属中心；
【离职信息同步】【人员异动信息同步】已经直接带"编制组织"字段，不查表。
"""

from parsers import parse_kv_fields, get_field

_SYNC_HEADERS = {
    "入职": "【入职信息同步】",
    "转正": "【转正信息同步】",
    "离职": "【离职信息同步】",
    "异动": "【人员异动信息同步】",
}
# 汇总消息里详情块的出现顺序，对应"今日入职/转正/离职/异动人数"的顺序。
_DETAIL_ORDER = ["入职", "转正", "离职", "异动"]
_SEPARATOR = "\n——————————\n"


def new_center_bucket():
    """一个中心当天的统计桶：4类同步消息原文 + 3类异动子计数。"""
    return {"入职": [], "转正": [], "离职": [], "异动": [],
            "改花名": 0, "改小组": 0, "改公司": 0}


def classify_sync_message(text):
    """按消息里的【XX信息同步】标题判断类型；不是同步消息返回 None。"""
    compact = "".join((text or "").split())
    for kind, header in _SYNC_HEADERS.items():
        if header in compact:
            return kind
    return None


def resolve_center(kind, fields, department_keywords, center_order):
    """离职/异动消息直接读"编制组织"字段；入职/转正消息靠部门关键词倒推。"""
    if kind in ("离职", "异动"):
        center = (get_field(fields, "编制组织") or "").strip()
        return center if center in department_keywords else None
    department = get_field(fields, "部门-小组", "部门")
    compact_department = "".join(department.split())
    if not compact_department:
        return None
    for center in center_order:
        for keyword in department_keywords.get(center, []):
            if keyword in compact_department:
                return center
    return None


def classify_transfer_subtype(value):
    """"异动类型"字段按关键字归到改花名/改小组/改公司三类之一，不认识的返回 None。"""
    value = value or ""
    if "花名" in value:
        return "改花名"
    if "组" in value:
        return "改小组"
    if "公司" in value:
        return "改公司"
    return None


def classify_and_bucket(text, buckets, department_keywords, center_order):
    """解析一条同步消息，归入对应中心的桶；返回 (kind, center) 或 (kind, None)（未识别中心）。"""
    kind = classify_sync_message(text)
    if not kind:
        return None, None
    fields = parse_kv_fields(text)
    center = resolve_center(kind, fields, department_keywords, center_order)
    if not center or center not in buckets:
        return kind, None
    bucket = buckets[center]
    bucket[kind].append(text.strip())
    if kind == "异动":
        subtype = classify_transfer_subtype(get_field(fields, "异动类型"))
        if subtype:
            bucket[subtype] += 1
    return kind, center


def build_daily_sync_report(buckets, center_order, company_label, date_str, include_detail):
    """拼出"当日人事信息数据同步"消息；include_detail=False 时去掉4类详情块。"""
    blocks = []
    for center in center_order:
        bucket = buckets.get(center) or new_center_bucket()
        lines = [
            f"{center}-{company_label}",
            f"日期：{date_str}",
            f"今日入职人数：{len(bucket['入职'])}",
            f"今日转正人数：{len(bucket['转正'])}",
            f"今日离职人数：{len(bucket['离职'])}",
            f"今日异动人数：{len(bucket['异动'])}",
            f"改花名人数：{bucket['改花名']}",
            f"改小组人数：{bucket['改小组']}",
            f"改公司人数：{bucket['改公司']}",
            "花名册是否完成更新：是",
        ]
        block = "\n".join(lines)
        if include_detail:
            detail_parts = [text for kind in _DETAIL_ORDER for text in bucket[kind] if text]
            if detail_parts:
                block += "\n\n" + "\n\n".join(detail_parts)
        blocks.append(block)
    return _SEPARATOR.join(blocks)
