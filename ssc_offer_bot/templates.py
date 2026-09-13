# -*- coding: utf-8 -*-
"""
各阶段发送的消息文本，在这里统一拼接。
如果实际排版跟公司模板对不上，改这个文件里的字符串拼接即可，不用动其他逻辑代码。
"""


def build_offer_confirm_message(org_unit: str, body: str) -> str:
    """
    场景一：HRBP原始offer消息 -> 转发到联合管理工作群的"offer信息确认"消息。
    开头替换成 "<入职编制组织值>【offer信息确认】"，结尾替换成 "@一级领导 请领导审批，谢谢"。
    """
    import config

    header = f"{org_unit}【offer信息确认】"
    leader_first = config.LEADER_FIRST.strip().lstrip("@")
    footer = f"@{leader_first} 请领导审批，谢谢"
    return f"{header}\n{body}\n\n{footer}"


def build_recruit_reply_message(
    candidate_name: str,
    position: str,
    salary_confirm: str,
    salary_probation: str,
    recruiter_username: str,
    hrbp_username: str,
) -> str:
    """场景二：终审通过后，回复招聘群简历消息，通知招聘 + 抄送hrbp。"""
    return (
        f"简历名：{candidate_name}\n"
        f"职位： {position}\n"
        f"转正薪资：{salary_confirm}\n"
        f"试用期：2个月\n"
        f"试用薪资：{salary_probation}\n\n"
        f"@{recruiter_username}   Offer审批已通过，请跟进候选人确认招聘信息和入职信息，"
        f"为防止隐私泄漏，请招聘私聊我，谢谢\n"
        f"@{hrbp_username}    请知悉"
    )


def build_onboarding_confirm_message(
    org_unit: str, fields: dict, leader_usernames: list, offer_text: str
) -> str:
    """保留原Offer正文，只更换标题、添加招聘/入职信息及末尾通知。"""
    import re
    from parsers import strip_header_footer

    if not offer_text.strip():
        raise ValueError("缺少原Offer消息，不能重建或添加原文没有的字段")
    body = strip_header_footer(offer_text)
    supplement = (
        "3️⃣招聘信息\n"
        f"招聘渠道：{fields.get('招聘渠道', '')}\n"
        f"简历来源：{fields.get('简历来源', '')}\n"
        f"招聘通道：{fields.get('招聘通道', '')}\n"
        "4️⃣入职信息\n"
        f"入职日期：{fields.get('入职日期', '')}\n"
        f"候选人联系方式：{fields.get('候选人联系方式', '')}"
    )
    # 只插入补充区，面试评价、其他未知字段和原有空字段均原样保留。
    insertion = re.search(r"(?m)^[ \t]*#?[ \t]*(?:面试评价|主要面试官)[ \t]*[:：]", body)
    if insertion:
        body = body[:insertion.start()].rstrip() + "\n" + supplement + "\n\n" + body[insertion.start():]
    else:
        body = body.rstrip() + "\n" + supplement
    leaders_line = " ".join(f"@{u.strip().lstrip('@')}" for u in leader_usernames)
    return f"{org_unit}【入职信息确认】\n{body}\n\n{leaders_line} 请知悉"
