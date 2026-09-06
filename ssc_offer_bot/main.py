# -*- coding: utf-8 -*-
"""
SSC Offer 审批流转自动化 主程序。

流程总览：
  场景一：HRBP群 @我 的"【Offer】+附件简历"消息
          -> 改写格式 -> 转发到联合管理工作群，@一级领导

  场景二：联合管理工作群里
          一级领导回复"好的"
            -> 技术中心：@二级审批人；其他中心：直接 @终审人
          （技术中心）二级审批人任意回复
            -> @终审人
          终审人任意回复
            -> 去招聘群搜同名候选人的简历消息，回复它，@招聘 + @hrbp，
               并提示"请招聘私聊我"补充招聘/入职信息

  场景三：招聘私聊我，消息里包含"招聘信息"或"入职信息"关键词
          -> 合并已有信息 + 私聊补充信息，拼出完整【入职信息确认】
          -> 回复到联合管理工作群里对应的【offer信息确认】消息，@对应部门领导

运行前请务必先：
  1. pip install telethon
  2. 在 config.py 里填好 api_id / api_hash
  3. 运行 list_chats.py，把群组的数字ID填进 config.py（比用群名字符串更稳）
  4. 找一个测试群，把 GROUP_HRBP / GROUP_LEADERSHIP / GROUP_RECRUIT 先指向测试群，
     用几条模拟消息走一遍全流程，确认字段解析和消息格式都对了，再切回正式群。
"""

import asyncio
import logging

from telethon import TelegramClient, events

import config
from state_store import StateStore
from parsers import parse_kv_fields, get_field, strip_header_footer
from templates import (
    build_offer_confirm_message,
    build_recruit_reply_message,
    build_onboarding_confirm_message,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("ssc_offer_bot")

client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)
state = StateStore(config.DB_PATH)


def get_leader_tags(org_unit: str, dept_text: str) -> list:
    """按部门规则找到最终【入职信息确认】要@的领导名单。"""
    for rule in config.DEPARTMENT_LEADER_TAGS:
        if rule["org_unit"] in org_unit or org_unit in rule["org_unit"]:
            for kw in rule["dept_keywords"]:
                if kw in dept_text:
                    return rule["leaders"]
    log.warning(
        f"未匹配到部门领导配置 (org_unit={org_unit!r}, dept_text={dept_text!r})，"
        f"使用默认名单，请检查 config.py 里的 DEPARTMENT_LEADER_TAGS 是否需要补充"
    )
    return config.DEFAULT_LEADERS


# ==================== 场景一：HRBP群 -> 联合管理工作群 ====================
@client.on(events.NewMessage(chats=config.GROUP_HRBP))
async def on_hrbp_offer(event):
    msg = event.message
    if not msg.mentioned:
        return  # 只处理@了我的消息

    text = msg.raw_text or ""
    if "【Offer】" not in text or "附件简历" not in text:
        return

    fields = parse_kv_fields(text)
    candidate_name = get_field(fields, "候选人姓名")
    org_unit = get_field(fields, "编制组织", "入职编制组织")

    if not candidate_name:
        log.warning(f"[场景1] 未能从消息中解析出候选人姓名，已跳过。原文前100字：{text[:100]!r}")
        return
    if not org_unit:
        log.warning(f"[场景1] 候选人 {candidate_name} 未解析出编制组织，已跳过")
        return

    body = strip_header_footer(text)
    new_text = build_offer_confirm_message(org_unit, body)

    sent = await client.send_message(
        config.GROUP_LEADERSHIP,
        new_text,
        file=msg.media if msg.media else None,
    )

    sender = await event.get_sender()
    hrbp_username = sender.username or str(sender.id)

    state.set(candidate_name, {
        "candidate_name": candidate_name,
        "org_unit": org_unit,
        "hrbp_username": hrbp_username,
        "offer_confirm_msg_id": sent.id,
        "position": get_field(fields, "职位", "应聘岗位"),
        "salary_confirm": get_field(fields, "转正薪资"),
        "salary_probation": get_field(fields, "试用薪资"),
        "raw_fields": fields,
        "stage": "sent_to_leadership",
    })
    log.info(f"[场景1] 候选人「{candidate_name}」已转发到联合管理工作群，msg_id={sent.id}")


# ==================== 场景二：联合管理工作群里的审批链 ====================
@client.on(events.NewMessage(chats=config.GROUP_LEADERSHIP))
async def on_leadership_reply(event):
    msg = event.message
    reply_to_id = msg.reply_to_msg_id
    if not reply_to_id:
        return

    sender = await event.get_sender()
    sender_username = (sender.username or "").lower()
    text = (msg.raw_text or "").strip()

    # ---- 1) 一级领导回复"好的" ----
    name, rec = state.find_by_field("offer_confirm_msg_id", reply_to_id)
    if rec and rec.get("stage") == "sent_to_leadership":
        if sender_username != config.LEADER_FIRST.lower():
            return
        if "好的" not in text:
            return

        if any(kw in rec["org_unit"] for kw in config.TECH_CENTER_KEYWORDS):
            sent = await client.send_message(
                config.GROUP_LEADERSHIP,
                f"@{config.LEADER_SECOND_TECH} 初审已通过，请领导二级审批，谢谢",
                reply_to=rec["offer_confirm_msg_id"],
            )
            state.update(name, second_review_msg_id=sent.id, stage="waiting_second_review")
            log.info(f"[场景2] 「{name}」技术中心，已转二级审批，msg_id={sent.id}")
        else:
            sent = await client.send_message(
                config.GROUP_LEADERSHIP,
                f"@{config.LEADER_FINAL} 初审已通过，请领导终审，谢谢",
                reply_to=rec["offer_confirm_msg_id"],
            )
            state.update(name, final_review_msg_id=sent.id, stage="waiting_final_review")
            log.info(f"[场景2] 「{name}」非技术中心，已直接转终审，msg_id={sent.id}")
        return

    # ---- 2) 技术中心二级审批人的任意回复 ----
    name, rec = state.find_by_field("second_review_msg_id", reply_to_id)
    if rec and rec.get("stage") == "waiting_second_review":
        if sender_username != config.LEADER_SECOND_TECH.lower():
            return
        sent = await client.send_message(
            config.GROUP_LEADERSHIP,
            f"@{config.LEADER_FINAL} 初审已通过，请领导终审，谢谢",
            reply_to=rec["offer_confirm_msg_id"],
        )
        state.update(name, final_review_msg_id=sent.id, stage="waiting_final_review")
        log.info(f"[场景2] 「{name}」二级审批已通过，已转终审，msg_id={sent.id}")
        return

    # ---- 3) 终审人的任意回复 -> 去招聘群找简历回复 ----
    name, rec = state.find_by_field("final_review_msg_id", reply_to_id)
    if rec and rec.get("stage") == "waiting_final_review":
        if sender_username != config.LEADER_FINAL.lower():
            return
        await handle_final_approved(name, rec)
        return


async def handle_final_approved(candidate_name: str, rec: dict):
    """终审通过后：去招聘群搜同名候选人的简历消息，回复它。"""
    resume_msg = None
    async for m in client.iter_messages(config.GROUP_RECRUIT, search=candidate_name, limit=50):
        if "候选人编码" in (m.raw_text or ""):
            resume_msg = m
            break

    if not resume_msg:
        log.warning(f"[场景2] 终审通过，但在招聘群未找到候选人「{candidate_name}」的简历消息，需要人工处理")
        state.update(candidate_name, stage="final_approved_no_resume_found")
        return

    recruiter = await resume_msg.get_sender()
    recruiter_username = recruiter.username or str(recruiter.id)

    reply_text = build_recruit_reply_message(
        candidate_name=candidate_name,
        position=rec.get("position", ""),
        salary_confirm=rec.get("salary_confirm", ""),
        salary_probation=rec.get("salary_probation", ""),
        recruiter_username=recruiter_username,
        hrbp_username=rec.get("hrbp_username", ""),
    )
    await client.send_message(config.GROUP_RECRUIT, reply_text, reply_to=resume_msg.id)

    state.update(
        candidate_name,
        recruiter_username=recruiter_username,
        resume_msg_id=resume_msg.id,
        stage="waiting_recruiter_dm",
    )
    log.info(f"[场景2] 「{candidate_name}」终审通过，已在招聘群回复简历消息，等待招聘私聊补充入职信息")


# ==================== 场景三：招聘私聊补充信息 -> 发布入职确认 ====================
@client.on(events.NewMessage(incoming=True))
async def on_private_message(event):
    if not event.is_private:
        return

    text = event.raw_text or ""
    if "招聘信息" not in text and "入职信息" not in text:
        return

    sender = await event.get_sender()
    sender_username = sender.username or ""
    if not sender_username:
        log.warning("[场景3] 收到私聊消息，但对方没有设置用户名，无法匹配到候选人记录")
        return

    candidate_name, rec = state.find_pending_for_recruiter(sender_username, text)
    if not rec:
        log.info(f"[场景3] 收到来自 @{sender_username} 的私聊消息，但未匹配到待处理候选人，已忽略")
        return

    dm_fields = parse_kv_fields(text)
    merged_fields = dict(rec.get("raw_fields", {}))
    merged_fields.update(dm_fields)
    merged_fields.setdefault("候选人姓名", candidate_name)

    dept_text = merged_fields.get("入职部门", "") or merged_fields.get("编制组织", "")
    leaders = get_leader_tags(rec["org_unit"], dept_text)

    final_text = build_onboarding_confirm_message(rec["org_unit"], merged_fields, leaders)

    await client.send_message(
        config.GROUP_LEADERSHIP,
        final_text,
        reply_to=rec["offer_confirm_msg_id"],
    )
    state.update(candidate_name, stage="done")
    log.info(f"[场景3] 「{candidate_name}」入职信息确认已发布到联合管理工作群，流程结束")


async def main():
    await client.start()
    me = await client.get_me()
    log.info(f"已登录账号：{me.username or me.id}")
    log.info("SSC Offer 自动化流程已启动，开始监听...")
    await client.run_until_disconnected()


if __name__ == "__main__":
    asyncio.run(main())
