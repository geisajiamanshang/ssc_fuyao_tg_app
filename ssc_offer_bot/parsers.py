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
import unicodedata


def mentions_ssc(message):
    """两套环境均识别指定SSC，不依赖当前账号的 mentioned 标记。

    @oiyr90557 是早期误用的旧标签（当时把 my.telegram.org 的 API 应用短名称
    误当成了机器人的 Telegram 用户名），机器人账号真正的用户名是 @ffuuyao。
    部分 BP 的 Offer 消息模板至今仍沿用旧标签，未同步更新会导致消息被
    on_hrbp_offer 静默忽略、流程卡在第一步。这里同时接受新旧两个标签，
    保证旧模板的 Offer 消息也能被正常处理；同时应推动模板尽快改回 @ffuuyao。
    """
    if any(getattr(entity, "user_id", None) == 8853414240
           for entity in (getattr(message, "entities", None) or [])):
        return True
    return bool(re.search(
        r"(?<![A-Za-z0-9_@])@(?:ffuuyao|oiyr90557)(?![A-Za-z0-9_])",
        getattr(message, "raw_text", "") or "", re.I,
    ))


def is_offer_message(text: str) -> bool:
    compact = re.sub(r"\s+", "", text).casefold()
    return (("【offer】" in compact and "附件简历" in compact)
            or "【offer信息确认】" in compact
            or "候选人编码" in compact or "候选人姓名" in compact)


def offer_header_org(text: str) -> str:
    match = re.match(r"^\s*([^\n【]+?)\s*【\s*offer\s*信息确认\s*】", text, re.I)
    return match.group(1).strip() if match else ""


def is_approval(text: str) -> bool:
    """识别明确同意，包括批量确认、表情和数字；否定/待定不推进。"""
    value = unicodedata.normalize("NFKC", text or "").casefold()
    value = re.sub(r"@[a-z0-9_]+", "", value)
    value = re.sub(r"[\s\ufe0f\U0001f3fb-\U0001f3ff]+", "", value)
    value = value.strip("。.!！,，;；:：、'\"‘’“”")
    # 不能把“不同意”“不ok”“同意，但需要修改”当作审批通过。
    if re.search(r"不(?!错)|未|否|拒绝|暂|待|稍后|等|考虑|修改|调整|但是|但|不过|\?|？", value):
        return False
    token = r"(?:好的|好|ok(?:ay)?|👌|1|同意通过|同意|审批通过|审核通过|通过|批准|可以|没问题|无异议|赞同|认可|确认通过)"
    prefix = r"(?:(?:以上|上述|全部|所有|都|均|收到|已阅|我|这边|这几个|这几位|这些|候选人|信息)[,，:：、]*)*"
    suffix = r"(?:[,，。!！、]*(?:了|的|啦|可以继续|请继续|继续下一步|请推进|可以推进|谢谢))*"
    return bool(re.fullmatch(prefix + token + r"(?:[,，。!！、]*" + token + r")*" + suffix, value))

# 字段名允许中文/英文/数字/下划线/斜杠/短横线（如"部门-小组"），长度限制避免误把正文长句当成字段名
_FIELD_PATTERN = re.compile(r"^\s*(?:[0-9０-９]+\s*[.．、)）]\s*)?([\u4e00-\u9fa5A-Za-z0-9_/-]{1,20}?)\s*[:：]\s*(.+?)\s*$")


def parse_kv_fields(text: str) -> dict:
    """按行解析 "字段名：值" 格式的文本，返回 dict。"""
    fields = {}
    if not text:
        return fields
    for line in text.splitlines():
        line = ''.join(c for c in unicodedata.normalize('NFKC', line)
                       if unicodedata.category(c) != 'Cf')
        m = _FIELD_PATTERN.match(line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key and val:
                fields[key] = val
    # 面试评价可能以#开头并跨多行，保留正文直至面试官或末尾通知。
    evaluation = re.search(
        r"(?:^|\n)\s*#?\s*面试评价\s*[:：][ \t]*(.*?)(?=\n[ \t]*(?:主要面试官\s*[:：]|@[A-Za-z0-9_]+)|\Z)",
        text, re.S,
    )
    if evaluation and evaluation.group(1).strip():
        fields["面试评价"] = evaluation.group(1).strip()
    return fields


_DATE_LIKE_RE = re.compile(
    r"^\d{4}\s*[.\-/年]\s*\d{1,2}\s*[.\-/月]\s*\d{1,2}\s*日?$"   # 2026.10.08 / 2026-10-08 / 2026年10月08日
    r"|^\d{1,2}\s*[./]\s*\d{1,2}$"                                     # 9/16 / 10.08
)
_CONTACT_LIKE_RE = re.compile(
    r"^@[A-Za-z0-9_]{3,}$"     # @dashit88
    r"|^1\d{10}$"              # 手机号
)


def fix_swapped_onboarding_date_contact(fields: dict) -> dict:
    """招聘私聊补充"入职信息"时，偶尔会把"入职日期"和"候选人联系方式"两行的
    值填反（比如"入职日期：@dashit88" + "候选人联系方式：2026.10.08"）。
    只有一边明显是TG号/手机号、另一边明显是日期格式时才纠正，模糊或非常规
    格式一律不动，避免误伤正常但格式少见的填写。"""
    date_val = (fields.get("入职日期") or "").strip()
    contact_val = (fields.get("候选人联系方式") or "").strip()
    if (date_val and contact_val
            and _CONTACT_LIKE_RE.match(date_val) and not _DATE_LIKE_RE.match(date_val)
            and _DATE_LIKE_RE.match(contact_val) and not _CONTACT_LIKE_RE.match(contact_val)):
        fields = dict(fields)
        fields["入职日期"], fields["候选人联系方式"] = contact_val, date_val
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
    header = (
        r"^(?:"
        r"(?:【\s*offer\s*】|offer)\s*\+?\s*附件简历\s*[:：]?"      # Offer+附件简历： / 【Offer】+附件简历：
        r"|【\s*offer\s*申请\s*】\s*[:：]?"                          # 【Offer申请】
        r"|[^\n【]*【\s*offer\s*信息确认\s*】"                       # xx中心【offer信息确认】
        r")\s*"
    )
    while True:
        cleaned = re.sub(header, "", t, count=1, flags=re.I)
        if cleaned == t:
            break
        t = cleaned.strip()
    footer = r"(?:^|\n)[ \t]*(?:@ffuuyao\b[^\n]*|@[A-Za-z0-9_]+[^\n]*?(?:请\s*(?:领导\s*)?审批|麻烦\s*跟进\s*offer(?:\s*审批)?)[^\n]*)\s*$"
    while True:
        cleaned = re.sub(footer, "", t, count=1, flags=re.I)
        if cleaned == t:
            break
        t = cleaned.strip()
    return t
