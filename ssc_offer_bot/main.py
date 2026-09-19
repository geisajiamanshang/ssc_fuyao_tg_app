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
  1. pip install -r requirements.txt
  2. 在 .env 中填写 TG_API_ID / TG_API_HASH
  3. 用 BOT_ENV=test 运行测试配置，或用 BOT_ENV=prod 运行生产配置
  4. 测试审批使用“测试1/测试2/测试3”，生产审批使用“1/2/3”。
"""

import asyncio
import logging
import unicodedata

from telethon import TelegramClient, events

import config
from state_store import StateStore
from approval_queue import select_pending
from parsers import parse_kv_fields, get_field, strip_header_footer
from parsers import is_offer_message, offer_header_org, is_approval, mentions_ssc
from templates import (
    build_offer_confirm_message,
    build_recruit_reply_message,
    build_onboarding_confirm_message,
)
from daily_reports import DailyReportSender
from regularization import (
    RegularizationDriveRepository,
    build_regularization_messages,
    regularization_trigger_scope,
    trigger_keyword_matches,
)
from anniversary import AnniversaryDriveRepository, anniversary_destination

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
outbox = StateStore(config.DB_PATH + ".outbox.json")
ssc_send_lock = asyncio.Lock()
hrgs_forwards = StateStore(config.DB_PATH + ".hrgs_forward.json")
hrgs_forward_lock = asyncio.Lock()
HRGS_BOT_USERNAME = "HRGS_ssc_bot"
daily_report_state = StateStore(config.DAILY_REPORT_STATE_PATH)
regularization_events = StateStore(config.REGULARIZATION_STATE_PATH)
regularization_lock = asyncio.Lock()
regularization_drive = RegularizationDriveRepository(
    config.REGULARIZATION_OUTPUT_FOLDER_ID
)
anniversary_events = StateStore(config.ANNIVERSARY_STATE_PATH)
anniversary_lock = asyncio.Lock()
anniversary_drive = AnniversaryDriveRepository(
    config.ANNIVERSARY_DRIVE_ROOT_ID, config.ANNIVERSARY_DRIVE_PATH
)


async def forward_onboarding_to_hrgs(message, chat_id):
    """仅转发SSC已经发布到联合管理群的入职确认，保留原消息和附件。"""
    if not config.HRGS_FORWARD_ENABLED:
        return
    if chat_id != config.GROUP_LEADERSHIP:
        return
    compact = "".join((message.raw_text or "").split())
    if "入职信息确认" not in compact:
        return
    me = await client.get_me()
    if message.sender_id != me.id:
        return
    key = f"{chat_id}:{message.id}"
    async with hrgs_forward_lock:
        if hrgs_forwards.get(key):
            return
        try:
            recipient = await client.get_entity(HRGS_BOT_USERNAME)
            if (not getattr(recipient, "bot", False)
                    or (getattr(recipient, "username", "") or "").casefold() != HRGS_BOT_USERNAME.casefold()):
                log.error("[HRGS转发] 收件人不是指定机器人，停止转发")
                return
            # 在网络请求前记录；并发监听和直接发送回调不会重复转发。
            hrgs_forwards.set(key, {"status": "forwarding", "source_msg_id": message.id})
            forwarded = await client.forward_messages(recipient, message.id, from_peer=chat_id)
            hrgs_forwards.update(key, status="forwarded", forwarded_msg_id=forwarded.id)
            log.info("[HRGS转发] 入职确认msg_id=%s 已转发给@%s", message.id, HRGS_BOT_USERNAME)
        except Exception:
            log.exception("[HRGS转发] msg_id=%s 转发失败；已发起的请求结果需核查，避免重复转发", message.id)


@client.on(events.NewMessage(chats=config.GROUP_LEADERSHIP, outgoing=True))
async def on_ssc_onboarding_published(event):
    await forward_onboarding_to_hrgs(event.message, event.chat_id)


async def get_ssc_reviewer():
    """统一使用登录账号的收藏夹，不按环境或SSC用户名另选收件人。"""
    return await client.get_me()


async def queue_group_message(destination, text, *, candidate, expected_stage,
                              updates, id_field=None, kind="message", reply_to=None,
                              file=None, approval_code=None):
    """所有群消息统一先送收藏夹，由该类消息的审批码放行。"""
    approval_code = approval_code or config.OFFER_APPROVAL_CODE
    if destination not in config.ALLOWED_DESTINATION_IDS:
        raise RuntimeError(
            f"[{config.ENVIRONMENT}] 目标群 {destination} 不在当前环境白名单，已阻止发送"
        )
    async with ssc_send_lock:
        reviewer = await get_ssc_reviewer()
        draft = await client.send_message(reviewer.id, text, file=file, parse_mode=None)
        outbox.set(str(draft.id), {
            "draft_id": draft.id, "destination": destination, "reply_to": reply_to,
            "candidate": candidate, "expected_stage": expected_stage,
            "updates": updates, "id_field": id_field, "kind": kind, "status": "pending",
            "review_chat_id": reviewer.id, "approval_code": str(approval_code),
        })
        state.update(candidate, stage=expected_stage)
        log.info(
            "[SSC审批] 草稿msg_id=%s，目标群=%s，等待SSC在接收草稿的会话发送%s",
            draft.id, destination, approval_code,
        )
        return draft


@client.on(events.NewMessage())
async def on_ssc_send_approval(event):
    approval_code = (event.raw_text or "").strip()
    if approval_code not in config.APPROVAL_CODES:
        return
    me = await client.get_me()
    reviewer = await get_ssc_reviewer()
    if not event.is_private or event.chat_id != reviewer.id or event.sender_id != reviewer.id:
        return
    async with ssc_send_lock:
        all_outbox_items = list(outbox.all().values())
        item = select_pending(
            all_outbox_items, state.all(), reviewer.id, approval_code,
            event.message.id, event.message.reply_to_msg_id,
        )
        if item is None:
            return
        rec = state.get(item["candidate"])
        if not rec or rec.get("stage") != item["expected_stage"]:
            log.warning("[SSC审批] 草稿状态已失效，msg_id=%s", item["draft_id"])
            return
        # 获取指定草稿的最新编辑内容，不把其他草稿或参考资料当作修改版。
        draft = await client.get_messages(reviewer.id, ids=item["draft_id"])
        if not draft or (not draft.raw_text and not draft.media):
            log.warning("[SSC审批] 草稿不存在或为空，msg_id=%s", item["draft_id"])
            return
        text = draft.raw_text or ""
        media = draft.media
        if not media and draft.id != item["draft_id"]:
            original_draft = await client.get_messages(reviewer.id, ids=item["draft_id"])
            media = original_draft.media if original_draft else None
        updates = dict(item["updates"])
        if item["kind"] == "offer":
            fields = parse_kv_fields(text)
            org = get_field(fields, "入职编制组织", "编制组织") or offer_header_org(text)
            if not get_field(fields, "候选人姓名") or not org:
                log.warning("[SSC审批] 修改后的Offer缺少候选人姓名或编制组织，未发送")
                return
            updates.update(raw_fields=fields, org_unit=org, offer_confirm_text=text,
                           position=get_field(fields, "职位", "应聘岗位"),
                           salary_confirm=get_field(fields, "转正薪资"),
                           salary_probation=get_field(fields, "试用薪资"))
        elif item["kind"] == "onboarding":
            # SSC修改编制组织/部门后，依最终入职确认字段重算备注名单。
            fields = parse_kv_fields(text)
            org = get_field(fields, "入职编制组织", "编制组织")
            leaders = get_leader_tags(org, get_field(fields, "入职部门"))
            if not leaders:
                return
            import re
            text = re.sub(r"^[^\n]*【入职信息确认】", org + "【入职信息确认】", text, count=1)
            text = re.sub(r"(?:\n[ \t]*)?@[A-Za-z0-9_]+(?:[ \t]+@[A-Za-z0-9_]+)*[ \t]+请知悉[ \t]*$", "", text).rstrip()
            text += "\n\n" + " ".join("@" + u for u in leaders) + " 请知悉"
        key = str(item["draft_id"])
        # 先持久化发送中状态；发送结果不确定时禁止重复1盲目重发。
        outbox.update(key, status="sending", approval_msg_id=event.message.id)
        try:
            sent = await client.send_message(item["destination"], text,
                                             file=media, reply_to=item["reply_to"], parse_mode=None)
            if item["id_field"]:
                updates[item["id_field"]] = sent.id
            state.update(item["candidate"], **updates)
            outbox.update(key, status="sent", sent_msg_id=sent.id)
            log.info("[SSC审批] 已发送至群=%s msg_id=%s", item["destination"], sent.id)
            # 主动覆盖程序发布的消息；同一消息的监听回调由持久化记录去重。
            await forward_onboarding_to_hrgs(sent, item["destination"])
        except Exception:
            log.exception("[SSC审批] 发送或保存失败，草稿msg_id=%s；结果待核查，不自动重发", item["draft_id"])


async def _send_saved_text(reviewer_id, text):
    """将参考资料按 Telegram 文本长度拆分后发送到收藏夹。"""
    remaining = (text or "").strip()
    while remaining:
        if len(remaining) <= 3900:
            chunk, remaining = remaining, ""
        else:
            cut = remaining.rfind("\n", 0, 3900)
            cut = cut if cut >= 1000 else 3900
            chunk, remaining = remaining[:cut].rstrip(), remaining[cut:].lstrip()
        await client.send_message(reviewer_id, chunk, parse_mode=None)


@client.on(events.NewMessage(chats=config.GROUP_REGULARIZATION_TRIGGER))
async def on_regularization_trigger(event):
    text = event.raw_text or ""
    normalized = unicodedata.normalize("NFKC", text)
    if (not config.ALLOW_MANUAL_TRIGGERS
            and event.sender_id != config.REGULARIZATION_TRIGGER_BOT_ID):
        log.info(
            "[转正提醒] 忽略非指定机器人消息：chat_id=%s sender_id=%s",
            event.chat_id, event.sender_id,
        )
        return
    if not trigger_keyword_matches(normalized, config.REGULARIZATION_TRIGGER_KEYWORD):
        log.info(
            "[转正提醒] 消息未命中关键词：chat_id=%s msg_id=%s",
            event.chat_id, event.message.id,
        )
        return

    log.info(
        "[转正提醒] 已捕捉触发消息：environment=%s chat_id=%s msg_id=%s sender_id=%s",
        config.ENVIRONMENT, event.chat_id, event.message.id, event.sender_id,
    )
    trigger_scope = regularization_trigger_scope(
        normalized, config.REGULARIZATION_TRIGGER_KEYWORD
    )

    event_key = f"{event.chat_id}:{event.message.id}"
    async with regularization_lock:
        previous = regularization_events.get(event_key)
        if previous and previous.get("status") in {"processing", "queued"}:
            return
        regularization_events.set(event_key, {"status": "processing"})
        reviewer = await get_ssc_reviewer()
        try:
            from datetime import datetime
            from zoneinfo import ZoneInfo

            today = datetime.now(ZoneInfo(config.DAILY_REPORT_TIMEZONE)).date()
            monthly_text, source_file = await asyncio.to_thread(
                regularization_drive.load_month, today
            )
            names, messages = build_regularization_messages(monthly_text, trigger_scope)
            if not names:
                await client.send_message(
                    reviewer.id,
                    "转正提醒处理失败：在当月转正信息中未匹配到提醒消息里的花名。",
                    parse_mode=None,
                )
                regularization_events.set(event_key, {
                    "status": "failed", "reason": "names_not_found",
                    "source_file_id": source_file.get("id"),
                })
                return

            # 参考信息先发；预转正提醒最后入审批队列，确保它是收藏夹中最近的草稿。
            missing = []
            for section_name in ("转正通知", "转正信息同步", "转正申请"):
                section_text = messages.get(section_name, "")
                if section_text:
                    await _send_saved_text(reviewer.id, section_text)
                else:
                    missing.append(section_name)
            if missing:
                await client.send_message(
                    reviewer.id,
                    "转正资料提示：未找到「" + "、".join(missing) + "」对应内容。",
                    parse_mode=None,
                )

            reminder = messages.get("预转正提醒", "")
            if not reminder:
                raise RuntimeError("当月转正信息中未找到对应预转正提醒")
            if len(reminder) > 4096:
                raise RuntimeError("预转正提醒超过 Telegram 单条消息长度，无法进入单条审批")

            candidate_key = f"regularization:{event_key}"
            draft = await queue_group_message(
                config.GROUP_LEADERSHIP,
                reminder,
                candidate=candidate_key,
                expected_stage="waiting_ssc_regularization",
                updates={"stage": "regularization_sent", "names": names},
                kind="message",
                approval_code=config.REGULARIZATION_APPROVAL_CODE,
            )
            regularization_events.set(event_key, {
                "status": "queued", "names": names, "draft_id": draft.id,
                "source_file_id": source_file.get("id"),
            })
            log.info(
                "[转正提醒] %s 的资料已发送收藏夹；草稿msg_id=%s，等待SSC发送%s",
                "、".join(names), draft.id, config.REGULARIZATION_APPROVAL_CODE,
            )
        except Exception as exc:
            regularization_events.set(event_key, {
                "status": "failed", "reason": str(exc)[:500],
            })
            log.exception("[转正提醒] msg_id=%s 处理失败", event.message.id)
            await client.send_message(
                reviewer.id,
                "转正提醒处理失败，请查看机器人日志。错误：" + str(exc)[:300],
                parse_mode=None,
            )


@client.on(events.NewMessage(chats=config.GROUP_ANNIVERSARY_TRIGGER))
async def on_anniversary_trigger(event):
    text = event.raw_text or ""
    normalized = unicodedata.normalize("NFKC", text)
    if (not config.ALLOW_MANUAL_TRIGGERS
            and event.sender_id != config.ANNIVERSARY_TRIGGER_BOT_ID):
        log.info(
            "[周年提醒] 忽略非指定机器人消息：chat_id=%s sender_id=%s",
            event.chat_id, event.sender_id,
        )
        return
    if not all(keyword in normalized for keyword in config.ANNIVERSARY_TRIGGER_KEYWORDS):
        return

    event_key = f"{event.chat_id}:{event.message.id}"
    async with anniversary_lock:
        previous = anniversary_events.get(event_key)
        if previous and previous.get("status") in {"processing", "queued"}:
            return
        anniversary_events.set(event_key, {"status": "processing"})
        reviewer = await get_ssc_reviewer()
        try:
            destination, fields = anniversary_destination(
                normalized, config.ANNIVERSARY_GROUP_RULES
            )
            if not destination:
                raise LookupError(
                    "无法根据编制组织和部门匹配周年全员群："
                    f"编制组织={fields['org_unit'] or '未填写'}，"
                    f"部门={fields['department'] or '未填写'}"
                )

            people, info_file = await asyncio.to_thread(
                anniversary_drive.load, normalized
            )
            drafts = []
            for person in people:
                # 带海报发送时文字是图片说明，Telegram 上限低于纯文本消息。
                if len(person["greeting"]) > 1000:
                    raise RuntimeError(f"{person['name']}的周年祝贺超过海报说明长度")
                candidate_key = f"anniversary:{event_key}:{person['name']}"
                draft = await queue_group_message(
                    destination,
                    person["greeting"],
                    file=person["poster"],
                    candidate=candidate_key,
                    expected_stage="waiting_ssc_anniversary",
                    updates={"stage": "anniversary_sent", "name": person["name"]},
                    kind="message",
                    approval_code=config.ANNIVERSARY_APPROVAL_CODE,
                )
                drafts.append({"name": person["name"], "draft_id": draft.id})

            anniversary_events.set(event_key, {
                "status": "queued", "drafts": drafts, "destination": destination,
                "info_file_id": info_file.get("id"),
            })
            log.info(
                "[周年提醒] %s 的海报和祝贺已发送收藏夹，等待SSC发送%s",
                "、".join(item["name"] for item in people),
                config.ANNIVERSARY_APPROVAL_CODE,
            )
        except Exception as exc:
            anniversary_events.set(event_key, {
                "status": "failed", "reason": str(exc)[:500],
            })
            log.exception("[周年提醒] msg_id=%s 处理失败", event.message.id)
            await client.send_message(
                reviewer.id,
                "入职周年提醒处理失败，未发送到全员群。错误：" + str(exc)[:300],
                parse_mode=None,
            )


@client.on(events.NewMessage())
async def debug_all_messages(event):
    try:
        chat = await event.get_chat()
        chat_title = getattr(chat, "title", None) or getattr(chat, "first_name", "私聊/未知")
    except Exception:
        chat_title = "获取失败"
    log.info(
        f"[DEBUG] chat_id={event.chat_id} chat_title={chat_title!r} "
        f"mentioned={event.message.mentioned} text={event.raw_text[:80]!r}"
    )


def get_leader_tags(org_unit: str, dept_text: str) -> list:
    """严格按Drive步骤备注匹配入职通知领导，兼容空格和大小写。"""
    def normalized(value):
        return "".join(unicodedata.normalize("NFKC", value or "").casefold().split())

    org, dept = normalized(org_unit), normalized(dept_text)
    for rule in config.DEPARTMENT_LEADER_TAGS:
        rule_org = normalized(rule["org_unit"])
        if org and rule_org and rule_org in org:
            if any(normalized(kw) in dept for kw in rule["dept_keywords"]):
                return rule["leaders"]
    log.warning("[场景3] 步骤备注未匹配通知名单：org_unit=%r dept_text=%r，停止发送", org_unit, dept_text)
    return []


# ==================== 场景一：HRBP群 -> 联合管理工作群 ====================
@client.on(events.NewMessage(chats=config.GROUP_HRBP))
async def on_hrbp_offer(event):
    msg = event.message
    text = msg.raw_text or ""
    if not is_offer_message(text):
        return
    me = await client.get_me()
    if not mentions_ssc(msg, me):
        log.info("[场景1] 跳过：消息未@当前登录SSC账号，msg_id=%s", msg.id)
        return  # 只处理@了我的消息

    fields = parse_kv_fields(text)
    candidate_name = get_field(fields, "候选人姓名")
    org_unit = get_field(fields, "入职编制组织", "编制组织") or offer_header_org(text)

    if not candidate_name:
        log.warning("[场景1] 缺少候选人姓名，msg_id=%s", msg.id)
        return
    if not org_unit:
        log.warning(f"[场景1] 候选人 {candidate_name} 未解析出入职编制组织，已跳过")
        return

    body = strip_header_footer(text)
    new_text = build_offer_confirm_message(org_unit, body)

    sender = await event.get_sender()
    hrbp_username = (getattr(sender, "username", None)
                     or str(event.sender_id))

    state.set(candidate_name, {
        "candidate_name": candidate_name,
        "org_unit": org_unit,
        "hrbp_username": hrbp_username,
        "offer_confirm_text": new_text,
        "position": get_field(fields, "职位", "应聘岗位"),
        "salary_confirm": get_field(fields, "转正薪资"),
        "salary_probation": get_field(fields, "试用薪资"),
        "raw_fields": fields,
        "stage": "waiting_ssc_offer",
    })
    await queue_group_message(config.GROUP_LEADERSHIP, new_text,
                              candidate=candidate_name, expected_stage="waiting_ssc_offer",
                              updates={"stage": "sent_to_leadership"},
                              id_field="offer_confirm_msg_id", kind="offer", file=msg.media)


# ==================== 场景二：联合管理工作群里的审批链 ====================
approval_lock = asyncio.Lock()


async def approval_target(event):
    """沿引用链找到SSC原始Offer；普通群回复匹配最近的SSC Offer。"""
    me = await client.get_me()
    target = None
    if event.message.reply_to_msg_id:
        target = await event.message.get_reply_message()
    else:
        async for previous in client.iter_messages(
            config.GROUP_LEADERSHIP, max_id=event.message.id, limit=50
        ):
            compact = "".join((previous.raw_text or "").casefold().split())
            known_prompt = any(
                state.find_by_field(field, previous.id)[1]
                for field in ("offer_confirm_msg_id", "second_review_msg_id", "final_review_msg_id")
            )
            if previous.sender_id == me.id and (known_prompt or "offer信息确认" in compact):
                target = previous
                break
    visited = set()
    for _ in range(20):
        if not target or target.id in visited:
            return None, None
        visited.add(target.id)
        if target.sender_id == me.id:
            for field in ("offer_confirm_msg_id", "second_review_msg_id", "final_review_msg_id"):
                name, rec = state.find_by_field(field, target.id)
                if rec:
                    org = rec.get("org_unit")
                    if field == "offer_confirm_msg_id":
                        org = get_field(parse_kv_fields(target.raw_text or ""), "入职编制组织", "编制组织") or org
                    return (name, dict(rec, org_unit=org)) if org else (None, None)
        compact = "".join((target.raw_text or "").casefold().split())
        if target.sender_id == me.id and "offer信息确认" in compact:
            name, rec = state.find_by_field("offer_confirm_msg_id", target.id)
            if not rec:
                return None, None
            fields = parse_kv_fields(target.raw_text or "")
            org = get_field(fields, "入职编制组织", "编制组织") or rec.get("org_unit")
            return (name, dict(rec, org_unit=org)) if org else (None, None)
        if not getattr(target, "reply_to_msg_id", None):
            return None, None
        target = await target.get_reply_message()
    log.warning("[场景2] 引用链超过20层，已跳过")
    return None, None


@client.on(events.NewMessage(chats=config.GROUP_LEADERSHIP))
async def on_leadership_reply(event):
    async with approval_lock:
        await process_leadership_reply(event)


async def process_leadership_reply(event):
    msg = event.message
    sender = await event.get_sender()
    username = (getattr(sender, "username", None) or "").casefold()
    leaders = {
        value.strip().lstrip("@").casefold()
        for value in (config.LEADER_FIRST, config.LEADER_SECOND_TECH, config.LEADER_FINAL)
        if value and value.strip().lstrip("@")
    }
    if username not in leaders:
        log.info("[场景2] 未匹配审批领导：username=%s msg_id=%s", username, msg.id)
        return
    if not is_approval(msg.raw_text or ""):
        log.info("[场景2] 非明确同意回复：msg_id=%s", msg.id)
        return
    name, rec = await approval_target(event)
    if not rec:
        log.warning("[场景2] 未匹配Offer或审批提示：msg_id=%s reply_to=%s", msg.id, msg.reply_to_msg_id)
        return
    if msg.id <= rec.get("last_approval_msg_id", 0):
        return
    stage = rec.get("stage")
    if stage == "sent_to_leadership":
        tech = any(kw in rec["org_unit"] for kw in config.TECH_CENTER_KEYWORDS)
        leader = config.LEADER_SECOND_TECH if tech else config.LEADER_FINAL
        next_stage = "waiting_second_review" if tech else "waiting_final_review"
        id_field = "second_review_msg_id" if tech else "final_review_msg_id"
        label = "二级审批" if tech else "三级审批（终审）"
    elif stage == "waiting_second_review":
        leader, next_stage, id_field, label = config.LEADER_FINAL, "waiting_final_review", "final_review_msg_id", "三级审批（终审）"
    elif stage in {"waiting_final_review", "final_approved_no_resume_found"}:
        await handle_final_approved(name, rec)
        state.update(name, last_approval_msg_id=msg.id)
        return
    else:
        return
    await queue_group_message(
        config.GROUP_LEADERSHIP,
        # 固定审批提示：所有路径只按目标审批级别选择，不改写正文。
        (f"@{leader.strip().lstrip('@')} 初审已通过，请领导二级审批，谢谢"
         if next_stage == "waiting_second_review"
         else f"@{leader.strip().lstrip('@')} 初审已通过，请领导终审，谢谢"),
        reply_to=rec["offer_confirm_msg_id"],
        candidate=name, expected_stage="waiting_ssc_" + next_stage,
        updates={"org_unit": rec["org_unit"], "stage": next_stage}, id_field=id_field,
    )
    state.update(name, last_approval_msg_id=msg.id)
    log.info("[场景2] %s 回复同意，候选人 %s 的%s提示等待SSC审批", username, name, label)


def matches_recruit_candidate(text: str, candidate_name: str, candidate_code: str = "") -> bool:
    """招聘简历无需Offer标题；编码优先，姓名忽略空格与大小写。"""
    def normalized(value):
        return "".join(unicodedata.normalize("NFKC", value or "").casefold().split())

    fields = parse_kv_fields(text)
    resume_code = get_field(fields, "候选人编码")
    resume_name = get_field(fields, "候选人姓名")
    if candidate_code and resume_code:
        return normalized(candidate_code) == normalized(resume_code)
    return bool(normalized(candidate_name) and normalized(resume_name)
                and normalized(candidate_name) == normalized(resume_name))


async def handle_final_approved(candidate_name: str, rec: dict):
    """终审通过后：去招聘群搜同名候选人的简历消息，回复它。"""
    resume_msg = None
    candidate_code = get_field(rec.get("raw_fields", {}), "候选人编码")
    # 编码优先；姓名搜索失败时扫描近期消息，兼容Telegram索引和空格差异。
    searches = list(dict.fromkeys(value for value in (candidate_code, candidate_name) if value)) + [None]
    for search in searches:
        kwargs = {"search": search, "limit": 100} if search else {"limit": 1000}
        async for m in client.iter_messages(config.GROUP_RECRUIT, **kwargs):
            if matches_recruit_candidate(m.raw_text or "", candidate_name, candidate_code):
                resume_msg = m
                break
        if resume_msg:
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
    await queue_group_message(
        config.GROUP_RECRUIT, reply_text, reply_to=resume_msg.id,
        candidate=candidate_name, expected_stage="waiting_ssc_recruit_reply",
        updates={"recruiter_username": recruiter_username, "resume_msg_id": resume_msg.id,
                 "resume_fields": parse_kv_fields(resume_msg.raw_text or ""),
                 "stage": "waiting_recruiter_dm"},
    )
    log.info("[场景2] %s 终审通过，招聘群通知等待SSC审批", candidate_name)


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
    resume_fields = rec.get("resume_fields", {})
    if not resume_fields and rec.get("resume_msg_id"):
        resume_message = await client.get_messages(config.GROUP_RECRUIT, ids=rec["resume_msg_id"])
        if resume_message:
            resume_fields = parse_kv_fields(resume_message.raw_text or "")
    merged_fields = dict(resume_fields)
    merged_fields.update(rec.get("raw_fields", {}))
    merged_fields.update(dm_fields)
    merged_fields.setdefault("候选人姓名", candidate_name)
    # 输出模板中简历来源填推荐人，招聘通道填资源来源；私聊明确字段优先。
    merged_fields["简历来源"] = dm_fields.get("简历来源") or get_field(resume_fields, "简历推荐人") or merged_fields.get("简历来源", "")
    merged_fields["招聘通道"] = dm_fields.get("招聘通道") or get_field(resume_fields, "招聘通道", "简历来源") or merged_fields.get("招聘通道", "")

    # 老记录从群内取回原Offer，新记录直接使用发送时保存的正文。
    offer_text = rec.get("offer_confirm_text", "")
    if not offer_text:
        original_offer = await client.get_messages(config.GROUP_LEADERSHIP, ids=rec["offer_confirm_msg_id"])
        offer_text = (original_offer.raw_text or "") if original_offer else ""
    if not offer_text:
        log.warning("[场景3] 原Offer消息不可用，已停止生成入职确认：%s", candidate_name)
        return
    original_fields = parse_kv_fields(offer_text)
    org_unit = get_field(original_fields, "入职编制组织", "编制组织") or rec["org_unit"]
    leaders = get_leader_tags(org_unit, get_field(original_fields, "入职部门"))
    if not leaders:
        return
    final_text = build_onboarding_confirm_message(org_unit, merged_fields, leaders, offer_text)

    await queue_group_message(
        config.GROUP_LEADERSHIP,
        final_text,
        reply_to=rec["offer_confirm_msg_id"],
        candidate=candidate_name, expected_stage="waiting_ssc_onboarding",
        updates={"stage": "done"}, kind="onboarding",
    )
    log.info("[场景3] %s 入职确认等待SSC审批", candidate_name)


async def main():
    await client.start()
    me = await client.get_me()
    if config.EXPECTED_SSC_USER_ID and me.id != config.EXPECTED_SSC_USER_ID:
        await client.disconnect()
        raise RuntimeError(
            f"登录账号ID {me.id} 与配置SSC账号ID {config.EXPECTED_SSC_USER_ID} 不一致"
        )
    await get_ssc_reviewer()
    daily_report_task = None
    if config.DAILY_REPORT_ENABLED:
        daily_report_sender = DailyReportSender(
            client,
            daily_report_state,
            folder_id=config.DAILY_REPORT_FOLDER_ID,
            recipient_username=config.DAILY_REPORT_RECIPIENT,
            timezone=config.DAILY_REPORT_TIMEZONE,
            poll_seconds=config.DAILY_REPORT_POLL_SECONDS,
        )
        daily_report_task = asyncio.create_task(daily_report_sender.run())
    log.info("当前环境：%s；已登录账号：%s", config.ENVIRONMENT, me.username or me.id)
    log.info("SSC Offer 自动化流程已启动，开始监听...")
    try:
        await client.run_until_disconnected()
    finally:
        if daily_report_task:
            daily_report_task.cancel()
            await asyncio.gather(daily_report_task, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
