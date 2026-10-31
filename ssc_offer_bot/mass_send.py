# -*- coding: utf-8 -*-
"""场景二十：SSC在自己的收藏夹发"群发"，机器人依次问：要群发的TG名单 -> 确认(1) ->
要群发的图文消息 -> 确认(1)，然后把这条图文消息逐个私发给名单里的每个TG。

纯逻辑（解析名单、会话状态判断、提示文案）放在这里，不涉及Telegram调用，方便独立测试。
"""

import re

from wallet_reminder import normalize_work_tg

# 机器人发到收藏夹的所有提示都以这个开头：提示会作为新消息再被监听器收到，靠这个前缀
# 认出"这是机器人自己发的"，不会把提示当成名单或要群发的消息内容。
NOTICE_PREFIX = "【群发】"

STAGE_WAITING_TGS = "waiting_tgs"
STAGE_WAITING_TGS_CONFIRM = "waiting_tgs_confirm"
STAGE_WAITING_MESSAGE = "waiting_message"
STAGE_WAITING_SEND_CONFIRM = "waiting_send_confirm"
STAGE_SENDING = "sending"
# 这两个阶段在等SSC发确认码"1"。
CONFIRM_STAGES = (STAGE_WAITING_TGS_CONFIRM, STAGE_WAITING_SEND_CONFIRM)

_SPLIT_RE = re.compile(r"[\s,，、;；]+")


def parse_tg_list(text):
    """名单文本（空格、逗号或一行一个隔开）-> (tgs, invalid)。
    tgs：规范成"@用户名"的列表，按出现顺序去重（不分大小写）；
    invalid：认不出来的片段。只认以@开头的用户名或t.me链接——不认裸单词，免得把一句
    普通的话里的英文单词当成用户名。"""
    tgs, invalid, seen = [], [], set()
    for token in _SPLIT_RE.split(text or ""):
        token = token.strip()
        if not token:
            continue
        tg = normalize_work_tg(token) if (token.startswith("@") or "t.me/" in token) else ""
        if not tg:
            invalid.append(token)
        elif tg.casefold() not in seen:
            seen.add(tg.casefold())
            tgs.append(tg)
    return tgs, invalid


def looks_like_tg_list_attempt(tgs, invalid):
    """这条消息是不是在"尝试发名单"：有认出的TG，或者有以@开头但认不出的片段。
    都没有的（普通聊天、审批码、别的功能的触发词）直接忽略，不回提示。"""
    return bool(tgs) or any(token.startswith("@") for token in invalid)


def session_expired(session, now_ts, wait_seconds):
    return not session or now_ts - session.get("since", 0) > wait_seconds


def waiting_for_confirm(session, now_ts, wait_seconds):
    """会话是不是正在等SSC发确认码（用来让审批码"1"不同时放行别的待审批草稿）。"""
    return (not session_expired(session, now_ts, wait_seconds)
            and session.get("stage") in CONFIRM_STAGES)


def format_tg_list(tgs):
    return "\n".join(tgs)


def format_report(ok, failed, remaining):
    """群发结果汇总。ok：成功的TG列表；failed：[(TG, 原因)]；remaining：因限流中止、没发的TG。"""
    total = len(ok) + len(failed) + len(remaining)
    lines = [f"{NOTICE_PREFIX}群发结束：共{total}个，成功{len(ok)}个，失败{len(failed)}个"
             + (f"，未发送{len(remaining)}个" if remaining else "") + "。"]
    if failed:
        lines.append("失败的：")
        lines.extend(f"{tg}（{reason}）" for tg, reason in failed)
    if remaining:
        lines.append("Telegram限流，已中止，下面这些没有发（过一阵再用\"群发\"重发）：")
        lines.extend(remaining)
    return "\n".join(lines)
