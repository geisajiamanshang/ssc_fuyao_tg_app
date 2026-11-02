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
STAGE_DIFF_WAITING_INPUT = "diff_waiting_input"
STAGE_DIFF_WAITING_CONFIRM = "diff_waiting_confirm"
STAGE_SENDING = "sending"
# 这两个阶段在等SSC发确认码"1"。
CONFIRM_STAGES = (STAGE_WAITING_TGS_CONFIRM, STAGE_WAITING_SEND_CONFIRM, STAGE_DIFF_WAITING_CONFIRM)

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


# ---------- "不同群发"：每个TG发各自不同的消息 ----------
# 一行一条："@用户名 消息"（TG和消息之间空格、逗号或冒号隔开）；
# 或者Markdown表格："| @用户名 | 消息 |"（表头行、|---|分隔行自动跳过）。
_LINE_RE = re.compile(
    r"^((?:https?://)?(?:www\.)?t\.me/[A-Za-z0-9_]+|@[A-Za-z0-9_]+)[\s,，:：;；]*(.*)$")
_SEPARATOR_CELL_RE = re.compile(r"^:?-+:?$")
_HEADER_NAMES = {"tg", "tg名", "tg用户名", "用户名", "telegram"}
MAX_MESSAGE_LENGTH = 4096


def parse_tg_messages(text):
    """名单文本 -> (items, bad)。items：[(TG, 消息)]，按出现顺序，完全相同的(TG, 消息)只留一条
    （同一个TG可以对应多条不同消息）；bad：认不出的原行。"""
    items, bad, seen = [], [], set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("|"):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if all(_SEPARATOR_CELL_RE.match(cell) for cell in cells if cell) and any(cells):
                continue
            if cells and cells[0].casefold() in _HEADER_NAMES:
                continue
            token, message = cells[0], " ".join(cell for cell in cells[1:] if cell)
        else:
            match = _LINE_RE.match(line)
            token, message = (match.group(1), match.group(2).strip()) if match else ("", "")
        tg = normalize_work_tg(token) if token else ""
        if not tg or not message or len(message) > MAX_MESSAGE_LENGTH:
            bad.append(line)
            continue
        key = (tg.casefold(), message)
        if key not in seen:
            seen.add(key)
            items.append((tg, message))
    return items, bad


def looks_like_table_attempt(items, bad):
    """这条消息是不是在"尝试发TG+消息的表"：有认出的行，或有以@/|开头、含t.me的行。
    都没有的（普通聊天、别的功能的触发词）直接忽略。"""
    return bool(items) or any(line.startswith(("@", "|")) or "t.me/" in line for line in bad)


def preview(message, limit=40):
    message = " ".join(message.split())
    return message if len(message) <= limit else message[:limit] + "…"


def format_tg_messages(items):
    return "\n".join(f"{index}. {tg} ← {preview(message)}" for index, (tg, message) in enumerate(items, 1))


def chunk_text(text, limit=3500):
    """长文本按行切成不超过limit字的几段（Telegram单条消息上限4096字）。"""
    chunks, current = [], ""
    for line in text.split("\n"):
        line = line[:limit]
        if current and len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks
