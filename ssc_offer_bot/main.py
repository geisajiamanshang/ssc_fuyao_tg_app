# -*- coding: utf-8 -*-
"""
SSC Offer 审批流转自动化 主程序。

流程总览：
  场景一：HRBP群 @我 的"【Offer】+附件简历"消息
          -> 改写格式 -> 转发到联合管理工作群，@一级领导

  场景二：联合管理工作群里
          一级领导回复"好的"（或在@他的消息上点👌表情，效果相同）
            -> 技术中心：@二级审批人；其他中心：直接 @终审人
          （技术中心）二级审批人任意回复（或点👌表情）
            -> @终审人
          终审人任意回复（或点👌表情）
            -> 去招聘群搜同名候选人的简历消息，回复它，@招聘 + @hrbp，
               并提示"请招聘私聊我"补充招聘/入职信息

  场景三：招聘私聊我，消息里包含"招聘信息"或"入职信息"关键词
          -> 合并已有信息 + 私聊补充信息，拼出完整【入职信息确认】
          -> 回复到联合管理工作群里对应的【offer信息确认】消息，@对应部门领导

  场景四：联合管理工作群的入职信息确认发布成功后
          -> 再次经收藏夹审批（测试11/11）
          -> 放行后原样转发到预入职登记群

  场景五：转正提醒-恒睿-转正倒数4天 触发后
          -> 转正申请单独经收藏夹审批（测试21/21，与预转正提醒的审批码2并存）
          -> 放行后转发到联合管理工作群；SSC可在批准前修改收藏夹里的草稿，
             放行时发送的是修改后的最新内容

  场景六：新人培训群里 @YYZXpeixun_bot 发的"新人培训考试通过"消息，@ffuuyao
          -> 按消息里@的新人TG用户名，到Drive云端 入职助手/输出 文件夹查找
             该新人的入职信息，按【段落名】分区分条发到收藏夹
          -> "新人入职通知""入职信息同步""欢迎"三个分区各自经独立审批码
             （测试6/6、测试6.1/6.1、测试6.2/6.2）放行，其余分区仅作参考资料
          -> 分别放行到联合管理群 / 人事数据同步-SSC3组 / 按部门匹配的全员群，
             每条转发成功后自动删除收藏夹里对应的草稿

  场景七：SSC3组内部工作沟通群 / 转正提醒来源群里出现"全员群"关键词
          -> 取该消息之前最近一条图文通知，转发到收藏夹
          -> SSC每发送一次审批码（测试7/7），只转发到剩余全员群里的下一个，
             需要连续发送5次才能覆盖全部5个全员群；发送时取的是当前草稿
             的最新内容，SSC可以在两次发送之间修改收藏夹草稿
          -> 第5个群发送成功后自动删除收藏夹里的这条草稿

  场景八：洛羽-SSC主管-CN私聊里出现账号申请类关键词（外事号/推特号/申请
          邮箱/注册TG等，转发消息或直接打字均可）
          -> 随机30-60秒后自动回复"ok"
          -> 从转发来源昵称或消息文本里提取花名，到Drive云端 入职助手/
             输出 文件夹按花名反查该人的入职信息，生成【员工帐号申请】
          -> 发到收藏夹，SSC发送审批码（测试5/5）后按关键词是否含"外事"
             放行到对应的外事/工作帐号需求群

运行前请务必先：
  1. pip install -r requirements.txt
  2. 在 .env 中填写 TG_API_ID / TG_API_HASH
  3. 用 BOT_ENV=test 运行测试配置，或用 BOT_ENV=prod 运行生产配置
  4. 测试审批使用“测试1/测试2/测试3/测试11/测试21/测试6/测试6.1/测试6.2/测试7/测试5”，
     生产审批使用“1/2/3/11/21/6/6.1/6.2/7/5”。
"""

import asyncio
import logging
import random
import unicodedata
import re
from datetime import datetime, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from telethon import TelegramClient, events, utils
from telethon.tl.types import UpdateMessageReactions, ReactionEmoji
from telethon.tl.functions.messages import GetMessageReactionsListRequest

import config
from state_store import StateStore
from approval_queue import select_pending
from batch_approval import missing_approvals, recover_approvals
from parsers import parse_kv_fields, get_field, strip_header_footer, fix_swapped_onboarding_date_contact
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
    department_for_name,
    extract_section_for_names,
    greeting_for_name,
    match_department_group,
    names_from_trigger,
    regularization_trigger_scope,
    split_sections,
    today_trigger_matches,
    today_trigger_scope,
    trigger_keyword_matches,
)
from anniversary import AnniversaryDriveRepository, anniversary_destination
from onboarding_training import (
    GATED_SECTION_NAMES,
    OnboardingTrainingDriveRepository,
    split_named_sections,
)
from account_request import (
    account_request_category,
    build_account_request_text,
    matches_account_request_keyword,
    name_from_direct_text,
    name_from_forward_sender_name,
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
onboarding_training_events = StateStore(config.ONBOARDING_TRAINING_STATE_PATH)
onboarding_training_lock = asyncio.Lock()
onboarding_training_drive = OnboardingTrainingDriveRepository(
    config.ONBOARDING_TRAINING_OUTPUT_FOLDER_ID
)
all_staff_notice_events = StateStore(config.ALL_STAFF_NOTICE_STATE_PATH)
all_staff_notice_lock = asyncio.Lock()
account_request_events = StateStore(config.ACCOUNT_REQUEST_STATE_PATH)
account_request_lock = asyncio.Lock()


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
    if event.chat_id in config.EXCLUDED_CHAT_IDS:
        return
    await forward_onboarding_to_hrgs(event.message, event.chat_id)


async def get_ssc_reviewer():
    """统一使用登录账号的收藏夹，不按环境或SSC用户名另选收件人。"""
    return await client.get_me()


async def queue_group_message(destination, text, *, candidate, expected_stage,
                              updates, id_field=None, kind="message", reply_to=None,
                              file=None, approval_code=None, delete_draft_after_send=False):
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
            "delete_draft_after_send": delete_draft_after_send,
        })
        state.update(candidate, stage=expected_stage)
        log.info(
            "[SSC审批] 草稿msg_id=%s，目标群=%s，等待SSC在接收草稿的会话发送%s",
            draft.id, destination, approval_code,
        )
        return draft


async def queue_pre_onboarding_registration(candidate, text):
    """入职确认已发布到联合管理群后，再次经收藏夹审批转发到预入职登记群。

    复用 queue_group_message 的审批码放行机制，但审批码是新的
    PRE_ONBOARDING_APPROVAL_CODE（测试11/11），与入职确认本身的审批码
    （OFFER_APPROVAL_CODE）分开，需要SSC再次在收藏夹确认才会发送。
    expected_stage 固定用"done"：入职确认发送成功后候选人状态已经是
    done，这里不改变候选人主流程的阶段，只是在done之后再挂一次转发。
    """
    if not config.PRE_ONBOARDING_FORWARD_ENABLED:
        return
    try:
        await queue_group_message(
            config.GROUP_PRE_ONBOARDING, text,
            candidate=candidate, expected_stage="done", updates={"stage": "done"},
            kind="pre_onboarding", approval_code=config.PRE_ONBOARDING_APPROVAL_CODE,
        )
        log.info("[预入职登记] %s 已提交收藏夹，等待SSC发送%s放行到预入职登记群",
                 candidate, config.PRE_ONBOARDING_APPROVAL_CODE)
    except Exception:
        log.exception("[预入职登记] %s 入队失败", candidate)


async def queue_all_staff_broadcast(candidate, text, file=None):
    """一条图文通知先进SSC收藏夹；SSC每发送一次审批码7，只转发到剩余全员群
    里的下一个，全部5个群都发完之前草稿保持待审批状态，可以重复发送同一个
    审批码；直到第5个群发送成功才删除收藏夹里的这条草稿。这样SSC可以每发
    一次核对一次效果，而不是一次性无法撤回地广播到全部5个群。
    """
    destinations = [rule["chat_id"] for rule in config.ANNIVERSARY_GROUP_RULES]
    for destination in destinations:
        if destination not in config.ALLOWED_DESTINATION_IDS:
            raise RuntimeError(
                f"[{config.ENVIRONMENT}] 全员群 {destination} 不在当前环境白名单，已阻止发送"
            )
    async with ssc_send_lock:
        reviewer = await get_ssc_reviewer()
        draft = await client.send_message(reviewer.id, text, file=file, parse_mode=None)
        outbox.set(str(draft.id), {
            "draft_id": draft.id, "destinations": destinations,
            "remaining_destinations": list(destinations), "sent_destinations": [],
            "candidate": candidate, "expected_stage": "waiting_ssc_all_staff_broadcast",
            "updates": {"stage": "all_staff_broadcast_sent"}, "id_field": None,
            "kind": "all_staff_broadcast", "status": "pending",
            "review_chat_id": reviewer.id, "approval_code": str(config.ALL_STAFF_NOTICE_APPROVAL_CODE),
            "delete_draft_after_send": True,
        })
        state.update(candidate, stage="waiting_ssc_all_staff_broadcast")
        log.info(
            "[全员群转发] 草稿msg_id=%s，等待SSC每发送一次%s转发到下一个全员群"
            "（共%s个，需连续发送%s次才能覆盖全部）",
            draft.id, config.ALL_STAFF_NOTICE_APPROVAL_CODE,
            len(destinations), len(destinations),
        )
        return draft


@client.on(events.NewMessage())
async def on_ssc_send_approval(event):
    if event.chat_id in config.EXCLUDED_CHAT_IDS:
        return
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
            if item["kind"] == "all_staff_broadcast":
                remaining = list(item.get("remaining_destinations") or item["destinations"])
                sent_so_far = list(item.get("sent_destinations") or [])
                destination = remaining.pop(0)
                sent = await client.send_message(destination, text,
                                                 file=media, parse_mode=None)
                sent_so_far.append(destination)
                if remaining:
                    # 还有全员群没发完：保持pending，让SSC能对同一草稿再次发送
                    # 同一个审批码，转发到下一个群；不提前更新候选人状态机。
                    outbox.update(key, status="pending",
                                 remaining_destinations=remaining,
                                 sent_destinations=sent_so_far)
                    log.info(
                        "[SSC审批] 已广播至全员群=%s msg_id=%s；还剩%s个群，"
                        "SSC可继续发送%s",
                        destination, sent.id, len(remaining), item["approval_code"],
                    )
                else:
                    state.update(item["candidate"], **updates)
                    outbox.update(key, status="sent",
                                 remaining_destinations=[], sent_destinations=sent_so_far)
                    log.info(
                        "[SSC审批] 已广播完全部全员群，最后一个=%s msg_id=%s",
                        destination, sent.id,
                    )
                    if item.get("delete_draft_after_send"):
                        try:
                            await client.delete_messages(reviewer.id, [item["draft_id"]])
                        except Exception:
                            log.exception("[SSC审批] 已发送但删除收藏夹草稿失败，msg_id=%s", item["draft_id"])
            else:
                sent = await client.send_message(item["destination"], text,
                                                 file=media, reply_to=item["reply_to"], parse_mode=None)
                if item["id_field"]:
                    updates[item["id_field"]] = sent.id
                if item["kind"] == "offer":
                    updates.update(offer_sent_at=sent.date.isoformat(),
                                   offer_chat_id=item["destination"], approvals={})
                state.update(item["candidate"], **updates)
                outbox.update(key, status="sent", sent_msg_id=sent.id)
                if updates.get("stage") == "waiting_recruiter_dm":
                    asyncio.create_task(replay_pending_recruiter_dm(item["candidate"]))
                log.info("[SSC审批] 已发送至群=%s msg_id=%s", item["destination"], sent.id)
                # 主动覆盖程序发布的消息；同一消息的监听回调由持久化记录去重。
                await forward_onboarding_to_hrgs(sent, item["destination"])
                if item["kind"] == "onboarding":
                    # 另起任务：此时仍持有ssc_send_lock，queue_group_message需要
                    # 重新获取同一把锁，必须等当前 async with 退出后才能执行。
                    asyncio.create_task(queue_pre_onboarding_registration(item["candidate"], text))
                if item.get("delete_draft_after_send"):
                    try:
                        await client.delete_messages(reviewer.id, [item["draft_id"]])
                    except Exception:
                        log.exception("[SSC审批] 已发送但删除收藏夹草稿失败，msg_id=%s", item["draft_id"])
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
    if event.chat_id in config.EXCLUDED_CHAT_IDS:
        return
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

            # 转正通知/转正信息同步是纯参考资料，直接发收藏夹；转正申请、预转正提醒
            # 分别走各自审批码，最后入审批队列，确保它们是收藏夹中最近的草稿。
            missing = []
            for section_name in ("转正通知", "转正信息同步"):
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

            application = messages.get("转正申请", "")
            if not application:
                raise RuntimeError("当月转正信息中未找到对应转正申请")
            if len(application) > 4096:
                raise RuntimeError("转正申请超过 Telegram 单条消息长度，无法进入单条审批")

            reminder = messages.get("预转正提醒", "")
            if not reminder:
                raise RuntimeError("当月转正信息中未找到对应预转正提醒")
            if len(reminder) > 4096:
                raise RuntimeError("预转正提醒超过 Telegram 单条消息长度，无法进入单条审批")

            candidate_key = f"regularization:{event_key}"
            application_key = f"regularization_application:{event_key}"
            application_draft = await queue_group_message(
                config.GROUP_LEADERSHIP,
                application,
                candidate=application_key,
                expected_stage="waiting_ssc_regularization_application",
                updates={"stage": "regularization_application_sent", "names": names},
                kind="message",
                approval_code=config.REGULARIZATION_APPLICATION_APPROVAL_CODE,
            )
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
                "application_draft_id": application_draft.id,
                "source_file_id": source_file.get("id"),
            })
            log.info(
                "[转正提醒] %s 的转正申请已发送收藏夹；草稿msg_id=%s，等待SSC发送%s",
                "、".join(names), application_draft.id,
                config.REGULARIZATION_APPLICATION_APPROVAL_CODE,
            )
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


@client.on(events.NewMessage(chats=config.GROUP_REGULARIZATION_TRIGGER))
async def on_regularization_today_trigger(event):
    if event.chat_id in config.EXCLUDED_CHAT_IDS:
        return
    text = event.raw_text or ""
    normalized = unicodedata.normalize("NFKC", text)
    if (not config.ALLOW_MANUAL_TRIGGERS
            and event.sender_id != config.REGULARIZATION_TRIGGER_BOT_ID):
        return
    if not today_trigger_matches(normalized, config.REGULARIZATION_TODAY_TRIGGER_KEYWORD):
        return

    trigger_scope = today_trigger_scope(
        normalized, config.REGULARIZATION_TODAY_TRIGGER_KEYWORD
    )
    event_key = f"today:{event.chat_id}:{event.message.id}"
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
            sections = split_sections(monthly_text)
            names = names_from_trigger(trigger_scope, sections.get("转正信息同步", ""))
            if not names:
                await client.send_message(
                    reviewer.id,
                    "今日转正处理失败：在当月转正信息中未匹配到提醒消息里的花名。",
                    parse_mode=None,
                )
                regularization_events.set(event_key, {
                    "status": "failed", "reason": "names_not_found",
                    "source_file_id": source_file.get("id"),
                })
                return

            drafts = []
            for name in names:
                greeting = greeting_for_name(sections.get("转正通知", ""), name)
                if not greeting:
                    raise LookupError(f"当月转正信息中未找到{name}的转正通知")
                if len(greeting) > 1000:
                    raise RuntimeError(f"{name}的转正通知超过海报说明长度")
                department = department_for_name(sections.get("转正信息同步", ""), name)
                destination = match_department_group(department, config.ANNIVERSARY_GROUP_RULES)
                if not destination:
                    raise LookupError(
                        f"{name}：无法根据部门匹配全员群（部门-小组={department or '未填写'}）"
                    )
                poster = await asyncio.to_thread(regularization_drive.find_poster, today, name)
                candidate_key = f"regularization_today:{event_key}:{name}"
                draft = await queue_group_message(
                    destination,
                    greeting,
                    file=poster,
                    candidate=candidate_key,
                    expected_stage="waiting_ssc_regularization_today",
                    updates={"stage": "regularization_today_sent", "name": name},
                    kind="message",
                    approval_code=config.REGULARIZATION_TODAY_APPROVAL_CODE,
                    delete_draft_after_send=True,
                )
                drafts.append({"name": name, "draft_id": draft.id, "destination": destination})

            if config.GROUP_REGULARIZATION_SYNC:
                sync_text = extract_section_for_names(
                    "转正信息同步", sections.get("转正信息同步", ""), names
                )
                if sync_text:
                    sync_draft = await queue_group_message(
                        config.GROUP_REGULARIZATION_SYNC,
                        sync_text,
                        candidate=f"regularization_today_sync:{event_key}",
                        expected_stage="waiting_ssc_regularization_today_sync",
                        updates={"stage": "regularization_today_sync_sent", "names": names},
                        kind="message",
                        approval_code=config.REGULARIZATION_TODAY_SYNC_APPROVAL_CODE,
                        delete_draft_after_send=True,
                    )
                    drafts.append({
                        "name": "、".join(names), "draft_id": sync_draft.id,
                        "destination": config.GROUP_REGULARIZATION_SYNC, "kind": "sync",
                    })

            regularization_events.set(event_key, {
                "status": "queued", "drafts": drafts,
                "source_file_id": source_file.get("id"),
            })
            log.info(
                "[今日转正] %s 的海报和祝贺已发送收藏夹，等待SSC发送%s",
                "、".join(item["name"] for item in drafts),
                config.REGULARIZATION_TODAY_APPROVAL_CODE,
            )
        except Exception as exc:
            regularization_events.set(event_key, {
                "status": "failed", "reason": str(exc)[:500],
            })
            log.exception("[今日转正] msg_id=%s 处理失败", event.message.id)
            await client.send_message(
                reviewer.id,
                "今日转正处理失败，未发送到全员群。错误：" + str(exc)[:300],
                parse_mode=None,
            )


@client.on(events.NewMessage(chats=config.GROUP_ANNIVERSARY_TRIGGER))
async def on_anniversary_trigger(event):
    if event.chat_id in config.EXCLUDED_CHAT_IDS:
        return
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
                    delete_draft_after_send=True,
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


def _training_target_username(text):
    """训练机器人消息里除了 @ffuuyao 外的第一个@用户名即新人本人。"""
    for match in re.finditer(r"@([A-Za-z][A-Za-z0-9_]{3,})", text or ""):
        username = match.group(1)
        if username.casefold() not in {"ffuuyao", "oiyr90557"}:
            return username
    return ""


@client.on(events.NewMessage())
async def on_onboarding_training_passed(event):
    if not config.ONBOARDING_TRAINING_ENABLED:
        return
    if event.chat_id != config.GROUP_TRAINING or event.chat_id in config.EXCLUDED_CHAT_IDS:
        return
    text = event.raw_text or ""
    if config.ONBOARDING_TRAINING_TRIGGER_KEYWORD not in text:
        return
    if not mentions_ssc(event.message):
        return
    username = _training_target_username(text)
    if not username:
        log.info(
            "[新人培训] 触发消息未找到新人TG用户名：chat_id=%s msg_id=%s",
            event.chat_id, event.message.id,
        )
        return

    log.info(
        "[新人培训] 已捕捉触发消息：environment=%s chat_id=%s msg_id=%s username=@%s",
        config.ENVIRONMENT, event.chat_id, event.message.id, username,
    )

    event_key = f"{event.chat_id}:{event.message.id}"
    async with onboarding_training_lock:
        previous = onboarding_training_events.get(event_key)
        if previous and previous.get("status") in {"processing", "queued"}:
            return
        onboarding_training_events.set(event_key, {"status": "processing"})
        reviewer = await get_ssc_reviewer()
        try:
            full_text, source_file = await asyncio.to_thread(
                onboarding_training_drive.find_by_username, username
            )
            sections = split_named_sections(full_text)
            if not sections:
                raise RuntimeError("入职信息文件未按【段落名】格式分区，无法处理")

            gated_by_name = {
                name: body for name, body in sections
                if name in GATED_SECTION_NAMES and body
            }
            missing = [name for name in GATED_SECTION_NAMES if name not in gated_by_name]

            # 三个固定分区以外的内容是纯参考资料，原样分条发到收藏夹，不设审批码。
            for name, body in sections:
                if name not in GATED_SECTION_NAMES and body:
                    await _send_saved_text(reviewer.id, f"【{name}】\n\n{body}")

            draft_ids = {}

            if "新人入职通知" in gated_by_name:
                notice_draft = await queue_group_message(
                    config.GROUP_LEADERSHIP,
                    gated_by_name["新人入职通知"],
                    candidate=f"onboarding_training_notice:{username}",
                    expected_stage="waiting_ssc_onboarding_training_notice",
                    updates={"stage": "onboarding_training_notice_sent", "username": username},
                    kind="message",
                    approval_code=config.ONBOARDING_TRAINING_NOTICE_APPROVAL_CODE,
                    delete_draft_after_send=True,
                )
                draft_ids["新人入职通知"] = notice_draft.id

            if "入职信息同步" in gated_by_name and config.GROUP_REGULARIZATION_SYNC:
                sync_draft = await queue_group_message(
                    config.GROUP_REGULARIZATION_SYNC,
                    gated_by_name["入职信息同步"],
                    candidate=f"onboarding_training_sync:{username}",
                    expected_stage="waiting_ssc_onboarding_training_sync",
                    updates={"stage": "onboarding_training_sync_sent", "username": username},
                    kind="message",
                    approval_code=config.ONBOARDING_TRAINING_SYNC_APPROVAL_CODE,
                    delete_draft_after_send=True,
                )
                draft_ids["入职信息同步"] = sync_draft.id

            if "欢迎" in gated_by_name:
                department_text = ""
                for name, body in sections:
                    if name != "欢迎" and body:
                        dept_match = re.search(r"部门-小组\s*[:：]\s*([^\n]+)", body)
                        if dept_match:
                            department_text = dept_match.group(1).strip()
                            break
                welcome_destination = match_department_group(
                    department_text, config.ANNIVERSARY_GROUP_RULES
                )
                if welcome_destination:
                    welcome_draft = await queue_group_message(
                        welcome_destination,
                        gated_by_name["欢迎"],
                        candidate=f"onboarding_training_welcome:{username}",
                        expected_stage="waiting_ssc_onboarding_training_welcome",
                        updates={"stage": "onboarding_training_welcome_sent", "username": username},
                        kind="message",
                        approval_code=config.ONBOARDING_TRAINING_WELCOME_APPROVAL_CODE,
                        delete_draft_after_send=True,
                    )
                    draft_ids["欢迎"] = welcome_draft.id
                else:
                    missing.append("欢迎（未匹配到部门对应的全员群）")

            if missing:
                await client.send_message(
                    reviewer.id,
                    "新人培训入职信息提示：未找到「" + "、".join(missing) + "」对应内容。",
                    parse_mode=None,
                )

            onboarding_training_events.set(event_key, {
                "status": "queued", "username": username, "draft_ids": draft_ids,
                "source_file_id": source_file.get("id"),
            })
            log.info(
                "[新人培训] @%s 的入职信息已处理，草稿=%s", username, draft_ids,
            )
        except Exception as exc:
            onboarding_training_events.set(event_key, {
                "status": "failed", "reason": str(exc)[:500],
            })
            log.exception("[新人培训] msg_id=%s 处理失败", event.message.id)
            await client.send_message(
                reviewer.id,
                "新人培训入职信息处理失败，请查看机器人日志。错误：" + str(exc)[:300],
                parse_mode=None,
            )


@client.on(events.NewMessage())
async def on_all_staff_notice_trigger(event):
    if not config.ALL_STAFF_NOTICE_ENABLED:
        return
    if (event.chat_id not in config.ALL_STAFF_NOTICE_TRIGGER_CHAT_IDS
            or event.chat_id in config.EXCLUDED_CHAT_IDS):
        return
    text = event.raw_text or ""
    if config.ALL_STAFF_NOTICE_TRIGGER_KEYWORD not in text:
        return

    log.info(
        "[全员群转发] 已捕捉触发消息：environment=%s chat_id=%s msg_id=%s",
        config.ENVIRONMENT, event.chat_id, event.message.id,
    )

    event_key = f"{event.chat_id}:{event.message.id}"
    async with all_staff_notice_lock:
        previous = all_staff_notice_events.get(event_key)
        if previous and previous.get("status") in {"processing", "queued"}:
            return
        all_staff_notice_events.set(event_key, {"status": "processing"})
        reviewer = await get_ssc_reviewer()
        try:
            source_message = None
            async for candidate_message in client.iter_messages(
                event.chat_id, limit=20, max_id=event.message.id
            ):
                if candidate_message.id == event.message.id:
                    continue
                if candidate_message.media and (candidate_message.raw_text or "").strip():
                    source_message = candidate_message
                    break
            if source_message is None:
                raise RuntimeError("未在最近消息中找到需要转发到全员群的图文通知")

            candidate_key = f"all_staff_notice:{event_key}"
            draft = await queue_all_staff_broadcast(
                candidate_key, source_message.raw_text, file=source_message.media
            )
            all_staff_notice_events.set(event_key, {
                "status": "queued", "draft_id": draft.id,
                "source_message_id": source_message.id,
            })
            log.info(
                "[全员群转发] 已找到源消息msg_id=%s，草稿msg_id=%s，等待SSC发送%s",
                source_message.id, draft.id, config.ALL_STAFF_NOTICE_APPROVAL_CODE,
            )
        except Exception as exc:
            all_staff_notice_events.set(event_key, {
                "status": "failed", "reason": str(exc)[:500],
            })
            log.exception("[全员群转发] msg_id=%s 处理失败", event.message.id)
            await client.send_message(
                reviewer.id,
                "全员群通知转发失败，请查看机器人日志。错误：" + str(exc)[:300],
                parse_mode=None,
            )


async def _send_delayed_ok_reply(chat_id, message_id, delay_seconds):
    """随机延迟30-60秒回复"ok"，让自动回复看起来更像人工处理，而不是秒回。"""
    try:
        await asyncio.sleep(delay_seconds)
        await client.send_message(chat_id, "ok", reply_to=message_id, parse_mode=None)
    except Exception:
        log.exception("[账号申请] 延迟回复ok失败：chat_id=%s msg_id=%s", chat_id, message_id)


@client.on(events.NewMessage(incoming=True))
async def on_account_request_trigger(event):
    if not config.ACCOUNT_REQUEST_ENABLED:
        return
    if not event.is_private:
        return
    sender = await event.get_sender()
    sender_username = (getattr(sender, "username", "") or "").casefold()
    if sender_username != config.ACCOUNT_REQUEST_MANAGER_USERNAME.casefold():
        return
    text = event.raw_text or ""
    if not matches_account_request_keyword(text):
        return

    event_key = f"{event.chat_id}:{event.message.id}"
    async with account_request_lock:
        previous = account_request_events.get(event_key)
        if previous and previous.get("status") in {"processing", "queued"}:
            return
        account_request_events.set(event_key, {"status": "processing"})

        # "ok"回复走独立的延迟任务，不阻塞后面生成草稿；即使查找信息失败，
        # 洛羽也能先看到消息已经被处理，而不是像没反应一样。
        asyncio.create_task(_send_delayed_ok_reply(
            event.chat_id, event.message.id, random.uniform(30, 60)
        ))

        reviewer = await get_ssc_reviewer()
        try:
            category = account_request_category(text)

            forward_name = ""
            forward = event.message.forward
            if forward:
                forward_sender = getattr(forward, "sender", None)
                display_name = (
                    getattr(forward_sender, "first_name", "") if forward_sender
                    else (getattr(forward, "from_name", "") or "")
                )
                forward_name = name_from_forward_sender_name(display_name)
            target_name = forward_name or name_from_direct_text(text)
            if not target_name:
                raise RuntimeError("未能从消息中识别出申请人花名")

            profile_text, source_file = await asyncio.to_thread(
                onboarding_training_drive.find_by_display_name, target_name
            )
            fields = parse_kv_fields(profile_text)
            draft_text = build_account_request_text(category, fields)

            candidate_key = f"account_request:{event_key}"
            destination = (
                config.GROUP_ACCOUNT_REQUEST_FOREIGN if category == "外事"
                else config.GROUP_ACCOUNT_REQUEST_WORK
            )
            draft = await queue_group_message(
                destination, draft_text,
                candidate=candidate_key, expected_stage="waiting_ssc_account_request",
                updates={"stage": "account_request_sent"}, kind="message",
                approval_code=config.ACCOUNT_REQUEST_APPROVAL_CODE,
            )
            account_request_events.set(event_key, {
                "status": "queued", "draft_id": draft.id,
                "category": category, "name": target_name,
                "source_file_id": source_file.get("id"),
            })
            log.info(
                "[账号申请] %s（%s类）已生成草稿msg_id=%s，等待SSC发送%s",
                target_name, category, draft.id, config.ACCOUNT_REQUEST_APPROVAL_CODE,
            )
        except Exception as exc:
            account_request_events.set(event_key, {
                "status": "failed", "reason": str(exc)[:500],
            })
            log.exception("[账号申请] msg_id=%s 处理失败", event.message.id)
            await client.send_message(
                reviewer.id,
                "账号申请处理失败，请查看机器人日志。错误：" + str(exc)[:300],
                parse_mode=None,
            )


@client.on(events.NewMessage())
async def debug_all_messages(event):
    if event.chat_id in config.EXCLUDED_CHAT_IDS:
        return
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
            if any(normalized(kw) in dept or (kw and normalized(kw) in org)
                   for kw in rule["dept_keywords"]):
                leaders = list(rule["leaders"])
                if rule_org == normalized("效能中心") and "Nicky_lam" not in leaders:
                    leaders.insert(max(0, len(leaders) - 1), "Nicky_lam")
                return leaders
    log.warning("[场景3] 步骤备注未匹配通知名单：org_unit=%r dept_text=%r，停止发送", org_unit, dept_text)
    return []


# ==================== 场景一：HRBP群 -> 联合管理工作群 ====================
@client.on(events.NewMessage(chats=config.GROUP_HRBP))
async def on_hrbp_offer(event):
    if event.chat_id in config.EXCLUDED_CHAT_IDS:
        return
    msg = event.message
    if not mentions_ssc(msg):
        return

    text = msg.raw_text or ""
    if not is_offer_message(text):
        return

    _, existing = state.find_by_field("offer_source_key", f"{event.chat_id}:{msg.id}")
    if existing:
        return

    fields = parse_kv_fields(text)
    candidate_name = get_field(fields, "候选人姓名")
    org_unit = get_field(fields, "入职编制组织", "编制组织") or offer_header_org(text)

    if not candidate_name:
        log.warning(f"[场景1] 未能从消息中解析出候选人姓名，已跳过。原文前100字：{text[:100]!r}")
        return
    if not org_unit:
        log.warning(f"[场景1] 候选人 {candidate_name} 未解析出入职编制组织，已跳过")
        return

    body = strip_header_footer(text)
    new_text = build_offer_confirm_message(org_unit, body)

    sender = await event.get_sender()
    hrbp_username = sender.username or str(sender.id)

    state.set(candidate_name, {
        "candidate_name": candidate_name,
        "offer_source_key": f"{event.chat_id}:{msg.id}",
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
    """沿直接或间接引用找到SSC原始Offer，不猜测无引用的单条审批。"""
    me = await client.get_me()
    target = None
    if event.message.reply_to_msg_id:
        target = await event.message.get_reply_message()
    else:
        return None, None
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
    if event.chat_id in config.EXCLUDED_CHAT_IDS:
        return
    async with approval_lock:
        await process_leadership_reply(event)


def approval_roles(org):
    # 只有技术中心需要二级审批；效能中心等其他组织不进入该分支。
    return ["first", "second", "final"] if "技术中心" in "".join(
        unicodedata.normalize("NFKC", org or "").split()
    ) else ["first", "final"]


def role_username(role):
    return {
        "first": config.LEADER_FIRST,
        "second": config.LEADER_SECOND_TECH,
        "final": config.LEADER_FINAL,
    }[role].strip().lstrip("@").casefold()


def approval_role(sender, rec=None, msg_id=None):
    username = (getattr(sender, "username", None) or "").casefold()
    matches = [r for r in ("first", "second", "final")
               if username and username == role_username(r)]
    if rec is not None:
        matches = [r for r in approval_roles(rec.get("org_unit")) if r in matches]
        evidence = rec.get("approvals", {})
        # 历史回放或重复事件不能将同一次发言再次计为另一级审批。
        for role in matches:
            if evidence.get(role, {}).get("message_id") == msg_id:
                return role
        if len(matches) > 1:
            return next((r for r in matches if not evidence.get(r)), None)
    return matches[0] if len(matches) == 1 else None


def batch_approval(text):
    value = unicodedata.normalize("NFKC", text or "")
    return is_approval(value) and "以上" in value


def apply_approval_evidence(rec, role, msg_id, sender_id):
    roles = approval_roles(rec.get("org_unit"))
    if role not in roles:
        return [], False
    evidence = rec.setdefault("approvals", {})
    missing = [r for r in roles[:roles.index(role)]
               if not evidence.get(r) or (role != "final" and evidence[r]["message_id"] >= msg_id)]
    # 终审可先于缺失的初审/二级审批：保存事实，待其他级别补齐再放行。
    if role == "final":
        changed = not evidence.get(role)
        if changed:
            evidence[role] = {"message_id": msg_id, "sender_id": sender_id}
        return missing, changed
    if missing or evidence.get(role):
        return missing, False
    evidence[role] = {"message_id": msg_id, "sender_id": sender_id}
    return [], True


async def notify_missing(name, missing):
    labels = {"first": "一级（初审）", "second": "二级", "final": "三级（终审）"}
    reviewer = await get_ssc_reviewer()
    text = name + "-卡在" + "、".join(
        labels[r] + "领导 @" + role_username(r) + " 的审批" for r in missing
    )
    await client.send_message(reviewer.id, text, parse_mode=None)


async def todays_offer_records(event):
    """以原Offer的群内发布时间界定今日；旧状态也从Telegram核实。"""
    zone = ZoneInfo(config.DAILY_REPORT_TIMEZONE)
    day = event.message.date.astimezone(zone).date()
    found = []
    for name, stored in list(state.all().items()):
        source_id = stored.get("offer_confirm_msg_id")
        if not source_id or source_id >= event.message.id:
            continue
        if stored.get("offer_chat_id", config.GROUP_LEADERSHIP) != config.GROUP_LEADERSHIP:
            continue
        source = await client.get_messages(config.GROUP_LEADERSHIP, ids=source_id)
        if not source or source.date.astimezone(zone).date() != day:
            continue
        me = await client.get_me()
        if source.sender_id != me.id or "offer信息确认" not in (source.raw_text or "").casefold():
            continue
        fields = parse_kv_fields(source.raw_text or "")
        org = get_field(fields, "入职编制组织", "编制组织") or offer_header_org(source.raw_text or "")
        rec = dict(stored, org_unit=org or stored.get("org_unit", ""))
        found.append((name, rec))
    return found


async def recover_approval_evidence(event, records):
    """按时间回放群内历史，恢复旧状态缺少的审批证据；回放不发送消息。"""
    if not records:
        return
    oldest = min(rec["offer_confirm_msg_id"] for _, rec in records)
    by_name = {name: rec for name, rec in records}
    async for message in client.iter_messages(
        config.GROUP_LEADERSHIP, min_id=oldest,
        max_id=event.message.id, reverse=True
    ):
        if not is_approval(message.raw_text or ""):
            continue
        sender = await message.get_sender()
        if batch_approval(message.raw_text):
            zone = ZoneInfo(config.DAILY_REPORT_TIMEZONE)
            targets = []
            for name, rec in records:
                source = await client.get_messages(config.GROUP_LEADERSHIP, ids=rec["offer_confirm_msg_id"])
                if (source and source.id < message.id and
                        source.date.astimezone(zone).date() == message.date.astimezone(zone).date()):
                    targets.append((name, rec))
        else:
            # 仅明确引用链可回放为旧审批证据，不猜测无引用的“好的”。
            if not getattr(message, "reply_to_msg_id", None):
                continue
            from types import SimpleNamespace
            name, _ = await approval_target(SimpleNamespace(message=message))
            targets = [(name, by_name[name])] if name in by_name else []
        for name, rec in targets:
            role = ("final" if batch_approval(message.raw_text) and
                    (getattr(sender, "username", "") or "").casefold() == role_username("final")
                    else approval_role(sender, rec, message.id))
            if role:
                apply_approval_evidence(rec, role, message.id, message.sender_id)
    for name, rec in records:
        state.update(name, approvals=rec.get("approvals", {}))


async def advance_offer(name, rec):
    roles = approval_roles(rec.get("org_unit"))
    evidence = rec.get("approvals", {})
    if all(evidence.get(r) for r in roles):
        if rec.get("stage") not in {
            "waiting_ssc_recruit_reply", "waiting_recruiter_dm",
            "waiting_ssc_onboarding", "done",
        }:
            # 失效旧审批草稿，避免终审后又发送过时提示。
            state.update(name, stage="final_approved_no_resume_found")
            await handle_final_approved(name, dict(rec, stage="final_approved_no_resume_found"))
        return
    if not evidence.get("first"):
        return
    role = next(r for r in roles if not evidence.get(r))
    next_stage = "waiting_second_review" if role == "second" else "waiting_final_review"
    pending_stage = "waiting_ssc_" + next_stage
    if rec.get("stage") in {next_stage, pending_stage}:
        return
    leader = role_username(role)
    text = (f"@{leader} 初审已通过，请领导二级审批，谢谢" if role == "second"
            else f"@{leader} 初审已通过，请领导终审，谢谢")
    await queue_group_message(
        config.GROUP_LEADERSHIP, text,
        reply_to=rec["offer_confirm_msg_id"], candidate=name,
        expected_stage=pending_stage,
        updates={"org_unit": rec["org_unit"], "stage": next_stage},
        id_field="second_review_msg_id" if role == "second" else "final_review_msg_id",
    )


async def process_leadership_reply(event):
    msg = event.message
    sender = await event.get_sender()
    username = (getattr(sender, "username", "") or "").casefold()
    if username not in {role_username(r) for r in ("first", "second", "final")} or not is_approval(msg.raw_text or ""):
        return
    if batch_approval(msg.raw_text) and username == role_username("final"):
        await process_batch_final(event)
        return
    if batch_approval(msg.raw_text):
        records = await todays_offer_records(event)
    else:
        name, rec = await approval_target(event)
        records = [(name, rec)] if rec else []
    if not records:
        log.warning("[Offer审批] 未找到可关联的Offer，msg_id=%s", msg.id)
        return
    await recover_approval_evidence(event, records)
    for name, rec in records:
        try:
            rec["approvals"] = dict(state.get(name).get("approvals", {}))
            role = approval_role(sender, rec, msg.id)
            if not role:
                continue
            missing, changed = apply_approval_evidence(rec, role, msg.id, event.sender_id)
            if changed:
                state.update(name, approvals=rec["approvals"], last_approval_msg_id=msg.id)
            if missing:
                await notify_missing(name, missing)
                continue
            # 回放可能已补齐全部审批，仍需恢复未完成的下一步；advance_offer负责去重。
            state.update(name, approvals=rec["approvals"], last_approval_msg_id=msg.id)
            await advance_offer(name, rec)
        except Exception:
            log.exception("[Offer审批] 候选人=%s 处理失败；继续检查其他候选人", name)
            reviewer = await get_ssc_reviewer()
            await client.send_message(reviewer.id, name + "-审批处理异常，请检查日志", parse_mode=None)

async def _offer_record_for_message(message):
    """判断某条消息是否是可关联的Offer审批锚点消息（原始Offer信息确认，或
    二级/终审的@领导审批提示），返回(name, rec)；供表情回应(reaction)直接按
    被回应的消息判断复用，逻辑与approval_target里单条消息的匹配规则一致。"""
    me = await client.get_me()
    if not message or message.sender_id != me.id:
        return None, None
    for field in ("offer_confirm_msg_id", "second_review_msg_id", "final_review_msg_id"):
        name, rec = state.find_by_field(field, message.id)
        if rec:
            org = rec.get("org_unit")
            if field == "offer_confirm_msg_id":
                org = get_field(parse_kv_fields(message.raw_text or ""), "入职编制组织", "编制组织") or org
            return (name, dict(rec, org_unit=org)) if org else (None, None)
    compact = "".join((message.raw_text or "").casefold().split())
    if "offer信息确认" in compact:
        name, rec = state.find_by_field("offer_confirm_msg_id", message.id)
        if not rec:
            return None, None
        fields = parse_kv_fields(message.raw_text or "")
        org = get_field(fields, "入职编制组织", "编制组织") or rec.get("org_unit")
        return (name, dict(rec, org_unit=org)) if org else (None, None)
    return None, None


async def _find_approval_reactor(peer_id, msg_id):
    """按APPROVAL_REACTION_EMOJIS逐个查该消息的表情回应者列表（用API精确查询，
    不依赖UpdateMessageReactions里可能被截断的recent_reactions），在其中找第一个
    用户名能对上一级/二级/终审领导的人；无关成员点的表情（哪怕同一条消息上
    也有别人点了不相关表情）不会被误判。"""
    leader_usernames = {role_username(r) for r in ("first", "second", "final")}
    for emoji in config.APPROVAL_REACTION_EMOJIS:
        result = await client(GetMessageReactionsListRequest(
            peer=peer_id, id=msg_id, reaction=ReactionEmoji(emoticon=emoji), limit=100,
        ))
        users_by_id = {user.id: user for user in result.users}
        for item in result.reactions:
            user = users_by_id.get(getattr(item.peer_id, "user_id", None))
            if user is not None and (getattr(user, "username", "") or "").casefold() in leader_usernames:
                return user
    return None


@client.on(events.Raw(UpdateMessageReactions))
async def on_leadership_reaction(update):
    if utils.get_peer_id(update.peer) != config.GROUP_LEADERSHIP:
        return
    async with approval_lock:
        await process_leadership_reaction(update)


async def process_leadership_reaction(update):
    """领导在@他的审批提示消息上直接点表情（如👌），等价于回复审批通过。"""
    peer_id = utils.get_peer_id(update.peer)
    if peer_id in config.EXCLUDED_CHAT_IDS:
        return
    message = await client.get_messages(peer_id, ids=update.msg_id)
    name, rec = await _offer_record_for_message(message)
    if not rec:
        return
    reactor = await _find_approval_reactor(peer_id, update.msg_id)
    if not reactor:
        return
    sender = SimpleNamespace(username=reactor.username, id=reactor.id)
    try:
        rec["approvals"] = dict(state.get(name).get("approvals", {}))
        role = approval_role(sender, rec, update.msg_id)
        if not role:
            return
        missing, changed = apply_approval_evidence(rec, role, update.msg_id, reactor.id)
        if changed:
            state.update(name, approvals=rec["approvals"], last_approval_msg_id=update.msg_id)
        if missing:
            await notify_missing(name, missing)
            return
        state.update(name, approvals=rec["approvals"], last_approval_msg_id=update.msg_id)
        await advance_offer(name, rec)
    except Exception:
        log.exception("[Offer审批] 候选人=%s 表情回应处理失败；继续检查其他候选人", name)
        reviewer = await get_ssc_reviewer()
        await client.send_message(reviewer.id, name + "-审批处理异常，请检查日志", parse_mode=None)


async def process_batch_final(event):
    """终审当天Offer；所有业务通知仍先进入收藏夹。"""
    zone = ZoneInfo(config.DAILY_REPORT_TIMEZONE)
    day = event.message.date.astimezone(zone).date()
    me = await client.get_me()
    messages, authors = [], {}
    async for message in client.iter_messages(config.GROUP_LEADERSHIP, max_id=event.message.id):
        if message.date.astimezone(zone).date() < day:
            break
        messages.append(message)
        if message.sender_id not in authors:
            sender = await message.get_sender()
            authors[message.sender_id] = (getattr(sender, 'username', '') or '').casefold()
    warnings = []
    for message in sorted(messages, key=lambda m: m.id):
        if message.sender_id != me.id or 'offer信息确认' not in (message.raw_text or '').casefold():
            continue
        name, rec = state.find_by_field('offer_confirm_msg_id', message.id)
        if not rec:
            name = get_field(parse_kv_fields(message.raw_text or ''), '候选人姓名') or str(message.id)
            warnings.append(f'{name}：缺少流程记录，无法核实初审/二级审批，请核查')
            continue
        if rec.get('stage') in {'waiting_ssc_recruit_reply', 'waiting_recruiter_dm', 'waiting_ssc_onboarding', 'done'}:
            continue
        if rec.get('batch_final_msg_id', 0) >= event.message.id:
            continue
        verified = recover_approvals(rec, messages, authors,
            config.LEADER_FIRST.strip().lstrip('@').casefold(),
            config.LEADER_SECOND_TECH.strip().lstrip('@').casefold(), is_approval)
        evidence = dict(rec.get("approvals", {}))
        evidence.setdefault("final", {"message_id": event.message.id,
                                      "sender_id": getattr(event, "sender_id", None)})
        for role, field in (("first", "first_approved_msg_id"), ("second", "second_approved_msg_id")):
            if verified.get(field):
                evidence.setdefault(role, {"message_id": verified[field]})
            elif evidence.get(role):
                verified[field] = evidence[role]["message_id"]
        verified["approvals"] = evidence
        state.update(name, approvals=evidence)
        missing = missing_approvals(verified, config.TECH_CENTER_KEYWORDS)
        if missing:
            labels = {'first': f'一级领导 @{config.LEADER_FIRST} 的初审', 'second': f'二级领导 @{config.LEADER_SECOND_TECH} 的审批'}
            warnings.append(f'{name}：尚未经过' + '、'.join(labels[k] for k in missing) + '（未找到同意记录），本次不放行')
            continue
        state.update(name, **{k: verified[k] for k in ('first_approved_msg_id', 'second_approved_msg_id') if k in verified},
                     batch_final_msg_id=event.message.id)
        try:
            # 审批通过的原始Offer独立转到收藏夹，不依赖招聘群能否找到简历。
            if not rec.get('batch_offer_forward_status'):
                state.update(name, batch_offer_forward_status='sending')
                forwarded = await client.forward_messages(
                    me.id, message.id, from_peer=config.GROUP_LEADERSHIP)
                state.update(name, batch_offer_forward_status='sent',
                             batch_offer_saved_msg_id=forwarded.id)
            await handle_final_approved(name, verified)
            state.update(name, last_approval_msg_id=event.message.id)
            if state.get(name).get('stage') == 'final_approved_no_resume_found':
                warnings.append(f'{name}：审批已通过，但未找到招聘简历，未生成发送草稿')
        except Exception:
            log.exception('[批量终审] 候选人处理失败：%s', name)
            warnings.append(f'{name}：处理失败，请核查日志和收藏夹，避免重复发送')
    if warnings:
        await _send_saved_text(me.id, '批量终审检查提醒（' + str(day) + '）\n' + '\n'.join(warnings))


def matches_recruit_candidate(text: str, candidate_name: str, candidate_code: str = "") -> bool:
    """简历必须含编码；同时校验姓名，防止测试简历复用编码导致串人。"""
    def normalized(value):
        return "".join(c for c in unicodedata.normalize("NFKC", value or "").casefold()
                       if not c.isspace() and unicodedata.category(c) != 'Cf')

    fields = parse_kv_fields(text)
    resume_code = get_field(fields, "候选人编码")
    if not resume_code:
        return False
    resume_name = get_field(fields, "简历名", "候选人姓名")
    if candidate_code and resume_code:
        return (normalized(candidate_code) == normalized(resume_code)
                and bool(normalized(candidate_name))
                and normalized(candidate_name) == normalized(resume_name))
    return bool(normalized(candidate_name) and normalized(resume_name)
                and normalized(candidate_name) == normalized(resume_name))


def _normalized_name(value):
    return "".join(c for c in unicodedata.normalize("NFKC", value or "").casefold()
                   if not c.isspace() and unicodedata.category(c) != 'Cf')


def matches_recruit_candidate_by_name(text: str, candidate_name: str) -> bool:
    """招聘群里找不到带候选人编码的正式简历消息时的退而求其次匹配：只要有
    "候选人姓名"（或"姓名"）字段且和候选人姓名一致，就当作能定位到人的线索
    消息，比如HR发的面试邀约、Zoom会议链接等——这类消息通常不含候选人编码，
    但足够回复+@招聘，让招聘私聊补充完整的招聘/入职信息。"""
    fields = parse_kv_fields(text)
    resume_name = get_field(fields, "候选人姓名", "姓名")
    return bool(_normalized_name(candidate_name) and resume_name
                and _normalized_name(candidate_name) == _normalized_name(resume_name))


async def handle_final_approved(candidate_name: str, rec: dict):
    """终审通过后：去招聘群搜同名候选人的简历消息，回复它；找不到带编码的
    正式简历时，退而求其次找一条提到候选人姓名的其他消息（面试邀约、Zoom
    会议通知等），一样回复+@招聘，让招聘私聊补充完整信息。"""
    resume_msg = None
    fallback_msg = None
    candidate_code = get_field(rec.get("raw_fields", {}), "候选人编码")
    # 搜索索引未命中时分页遍历历史，避免格式差异和旧简历超出固定条数上限。
    searches = list(dict.fromkeys(value for value in (candidate_code, candidate_name) if value)) + [None]
    for search in searches:
        kwargs = {"search": search, "limit": None} if search else {"limit": None}
        async for m in client.iter_messages(config.GROUP_RECRUIT, **kwargs):
            text = m.raw_text or ""
            if matches_recruit_candidate(text, candidate_name, candidate_code):
                resume_msg = m
                break
            if fallback_msg is None and matches_recruit_candidate_by_name(text, candidate_name):
                fallback_msg = m
        if resume_msg:
            break

    used_fallback = not resume_msg and fallback_msg is not None
    resume_msg = resume_msg or fallback_msg

    if not resume_msg:
        log.warning(f"[场景2] 终审通过，但在招聘群未找到候选人「{candidate_name}」的简历消息，需要人工处理")
        state.update(candidate_name, stage="final_approved_no_resume_found")
        reviewer = await get_ssc_reviewer()
        await client.send_message(reviewer.id,
            candidate_name + "-终审已通过，但未找到编码和姓名匹配的简历，也没有找到提到该姓名的其他消息。"
            + f"查询招聘群ID：{config.GROUP_RECRUIT}；候选人编码：{candidate_code or '未填写'}。"
            + "请核对群ID及简历字段；修正后在收藏夹发送“重试招聘通知”。", parse_mode=None)
        return

    if used_fallback:
        log.warning(f"[场景2] 候选人「{candidate_name}」未找到正式简历，改用招聘群里提到该姓名的其他消息(msg_id={resume_msg.id})继续流程")
        reviewer = await get_ssc_reviewer()
        await client.send_message(reviewer.id,
            candidate_name + f"-未找到带编码的正式简历，已改用招聘群里msg_id={resume_msg.id}这条提到该姓名的消息"
            + "（如面试邀约/会议通知）继续流程，请核实简历信息是否需要人工补充。", parse_mode=None)

    recruiter = await resume_msg.get_sender()
    recruiter_username = recruiter.username or str(recruiter.id)

    reply_text = build_recruit_reply_message(
        candidate_name=candidate_name,
        position=rec.get("position", ""),
        salary_confirm=rec.get("salary_confirm", ""),
        salary_probation=rec.get("salary_probation", ""),
        recruiter_username=recruiter_username,
        hrbp_username=rec.get("hrbp_username", ""),
        probation_period=get_field(rec.get("raw_fields", {}), "试用期") or "2个月",
    )
    await queue_group_message(
        config.GROUP_RECRUIT, reply_text, reply_to=resume_msg.id,
        candidate=candidate_name, expected_stage="waiting_ssc_recruit_reply",
        updates={"recruiter_username": recruiter_username, "recruiter_id": recruiter.id,
                 "resume_msg_id": resume_msg.id,
                 "resume_fields": parse_kv_fields(resume_msg.raw_text or ""),
                 "stage": "waiting_recruiter_dm"},
    )
    log.info("[场景2] %s 终审通过，招聘群通知等待SSC审批", candidate_name)


@client.on(events.NewMessage())
async def retry_recruit_notifications(event):
    if event.chat_id in config.EXCLUDED_CHAT_IDS:
        return
    if (event.raw_text or '').strip() != '重试招聘通知':
        return
    me = await client.get_me()
    if not event.is_private or event.chat_id != me.id or event.sender_id != me.id:
        return
    async with approval_lock:
        for name, rec in list(state.all().items()):
            if rec.get('stage') != 'final_approved_no_resume_found':
                continue
            if not all(rec.get('approvals', {}).get(role) for role in approval_roles(rec.get('org_unit'))):
                continue
            try:
                await handle_final_approved(name, rec)
            except Exception:
                log.exception('[招聘重试] %s 处理失败', name)
                await client.send_message(me.id, name + '-招聘通知重试失败，请查看日志', parse_mode=None)


# ==================== 场景三：招聘私聊补充信息 -> 发布入职确认 ====================
async def replay_pending_recruiter_dm(name):
    rec = state.get(name) or {}
    pending = rec.get('pending_recruiter_dm')
    if not pending or rec.get('stage') != 'waiting_recruiter_dm':
        return
    try:
        message = await client.get_messages(pending['sender_id'], ids=pending['message_id'])
        if message:
            from types import SimpleNamespace
            await on_private_message(SimpleNamespace(is_private=True, raw_text=message.raw_text,
                message=message, get_sender=message.get_sender))
    except Exception:
        log.exception('[入职确认] %s 提前私聊恢复失败', name)


@client.on(events.NewMessage(incoming=True))
async def on_private_message(event):
    if not event.is_private:
        return

    text = event.raw_text or ""
    if "招聘信息" not in text and "入职信息" not in text:
        return

    sender = await event.get_sender()
    sender_username = sender.username or ""
    candidate_name, rec = state.find_pending_for_recruiter(sender_username, text, sender.id)
    if not rec:
        fields = parse_kv_fields(text)
        name = get_field(fields, '候选人姓名', '简历名')
        known = state.get(name) if name else None
        if not known:
            return
        reviewer = await get_ssc_reviewer()
        # 招聘通知待SSC审批时，收件人身份已保存在该草稿的updates中。
        pending_draft = next((r for r in outbox.all().values()
            if r.get('candidate') == name and r.get('status') in {'pending', 'sending'}
            and r.get('updates', {}).get('stage') == 'waiting_recruiter_dm'
            and r.get('updates', {}).get('recruiter_id') == sender.id), None)
        if known.get('stage') == 'waiting_ssc_recruit_reply' and pending_draft:
            state.update(name, pending_recruiter_dm={'sender_id':sender.id,
                                                   'message_id':event.message.id})
            notice = name + '-已收到招聘补充信息，等待招聘通知草稿通过“测试1”；放行后自动生成入职确认。'
        elif known.get('stage') in {'waiting_ssc_onboarding', 'done'}:
            return
        else:
            notice = (name + '-收到招聘补充信息，但未进入匹配的待入职阶段。'
                      + f"当前阶段：{known.get('stage', '未知')}；发送者ID：{sender.id}。"
                      + '请先处理招聘通知并确认发送者与简历发布者一致，完成后请招聘重发补充信息。')
        await client.send_message(reviewer.id, notice, parse_mode=None)
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
    merged_fields = fix_swapped_onboarding_date_contact(merged_fields)

    # 老记录从群内取回原Offer，新记录直接使用发送时保存的正文。
    offer_text = rec.get("offer_confirm_text", "")
    if not offer_text:
        original_offer = await client.get_messages(config.GROUP_LEADERSHIP, ids=rec["offer_confirm_msg_id"])
        offer_text = (original_offer.raw_text or "") if original_offer else ""
    if not offer_text:
        log.warning("[场景3] 原Offer消息不可用，已停止生成入职确认：%s", candidate_name)
        reviewer = await get_ssc_reviewer()
        await client.send_message(reviewer.id, candidate_name + '-入职确认未生成：原Offer消息不可用', parse_mode=None)
        return
    original_fields = parse_kv_fields(offer_text)
    org_unit = get_field(merged_fields, "入职编制组织", "编制组织") or rec["org_unit"]
    leaders = get_leader_tags(org_unit, get_field(merged_fields, "入职部门"))
    if not leaders:
        reviewer = await get_ssc_reviewer()
        await client.send_message(reviewer.id, candidate_name + '-入职确认未生成：未匹配通知名单；编制组织：' + org_unit
                                  + '；入职部门：' + get_field(merged_fields, '入职部门'), parse_mode=None)
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
    state.update(candidate_name, pending_recruiter_dm=None)


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
