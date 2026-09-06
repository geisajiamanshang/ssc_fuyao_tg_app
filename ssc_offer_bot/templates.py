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
    footer = f"@{config.LEADER_FIRST} 请领导审批，谢谢"
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


def build_onboarding_confirm_message(org_unit: str, fields: dict, leader_usernames: list) -> str:
    """
    场景三：招聘私聊补充完信息后，回复联合管理工作群里的【offer信息确认】，
    发布完整的【入职信息确认】。

    fields 是合并后的字段字典（场景一解析出的字段 + 招聘私聊补充的字段）。
    """
    leaders_line = "  ".join(f"@{u}" for u in leader_usernames)

    return (
        f"{org_unit}【入职信息确认】\n"
        f"候选人编码：{fields.get('候选人编码', '')}\n"
        f"候选人姓名：{fields.get('候选人姓名', '')}\n"
        f"性别：{fields.get('性别', '')}\n"
        f"1️⃣编制信息：\n"
        f"入职编制组织：{fields.get('入职编制组织', org_unit)}\n"
        f"入职服务单位：{fields.get('入职服务单位', '')}\n"
        f"人员性质：{fields.get('人员性质', '')}\n"
        f"入职部门：{fields.get('入职部门', '')}\n"
        f"直属上级：{fields.get('直属上级', '')}      岗位类型：{fields.get('岗位类型', '')}\n"
        f"职位：{fields.get('职位', '')}\n"
        f"建议职级：{fields.get('建议职级', '')}     管理序列：{fields.get('管理序列', '')}\n"
        f"办公方式：{fields.get('办公方式', '')}地区：{fields.get('地区', '')}\n"
        f"2️⃣薪资信息\n"
        f"薪资货币：{fields.get('薪资货币', 'RMB')}\n"
        f"转正薪资：{fields.get('转正薪资', '')}\n"
        f"试用期：{fields.get('试用期', '2个月')}\n"
        f"试用薪资：{fields.get('试用薪资', '')}\n"
        f"3️⃣招聘信息\n"
        f"招聘渠道：{fields.get('招聘渠道', '')}\n"
        f"简历来源：{fields.get('简历来源', '')}\n"
        f"招聘专员：{fields.get('招聘专员', '')}\n"
        f"招聘组长：{fields.get('招聘组长', '')}\n"
        f"招聘主管：{fields.get('招聘主管', '')}\n"
        f"招聘专员联系方式：{fields.get('招聘专员联系方式', '')}\n"
        f"4️⃣入职信息：\n"
        f"  1. 入职日期：{fields.get('入职日期', '')}\n"
        f"  2. 候选人联系方式：{fields.get('候选人联系方式', '')}\n"
        f"#面试评价：{fields.get('面试评价', '')}\n"
        f"主要面试官：{fields.get('主要面试官', '')}\n"
        f"{leaders_line}  请知悉"
    )
