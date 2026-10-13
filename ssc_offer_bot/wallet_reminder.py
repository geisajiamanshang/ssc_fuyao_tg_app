# -*- coding: utf-8 -*-
"""场景十五：SSC在自己的收藏夹发带"钱包提醒"关键词的消息，触发：
1. 花名册（机器人）里AR列（入职日期）是今天的人员；
2. 钱包表单里F列是"首次提交（新人入职）"的条目——一个员工由C列、D列两个值确认
   （对应花名册的B列、C列），在这些条目里找得到就算已填写；
3. 没填写的人，向他的工作TG（花名册AE列）发提醒：
   "请及时填写钱包表单并发送邮件给ssc，详细规则查看扶摇-ssc-bot 机器人 新人入职通知 待办事项2"。
草稿先发收藏夹，经审批码17（测试17）放行后逐个私发。

花名册B/C列与表单C/D列各自存的是什么（编号/花名）没有样例核对，所以比较时不
要求位置对应：把一个人的B、C两个非空值当成一组，表单一行的C、D两个非空值当
成一组，人员那组全部包含在表单这组里就算匹配（不分大小写、去空格、全半角统一）。
纯逻辑单独放在这里，不涉及Telegram调用，方便独立测试；表格读取复用
training_sync.TrainingSyncRosterRepository（只读）。
"""

import re
import unicodedata

from training_sync import _cell, _col_index, parse_training_date

WALLET_REMINDER_MESSAGE = "请及时填写钱包表单并发送邮件给ssc，详细规则查看扶摇-ssc-bot 机器人 新人入职通知 待办事项2"
WALLET_FIRST_SUBMIT_TYPE = "首次提交（新人入职）"

# 花名册（机器人）：表头1行，数据从第2行开始（跟培训同步用的是同一张表）。
ROSTER_COLUMNS = {"key_b": "B", "key_c": "C", "date_raw": "AR", "work_tg": "AE"}
# 钱包表单：第1行表头。C、D两列共同确认一个员工，F列是提交类型。
FORM_COLUMNS = {"key_c": "C", "key_d": "D", "submit_type": "F"}
DATA_START_INDEX = 1

_USERNAME_ONLY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{4,31}$")
_AT_USERNAME_RE = re.compile(r"(?<![A-Za-z0-9_.])@([A-Za-z][A-Za-z0-9_]{4,31})")
_TME_RE = re.compile(r"t\.me/([A-Za-z][A-Za-z0-9_]{4,31})", re.I)
_PLACEHOLDERS = ("同上", "无", "暂无", "待补充", "没有", "-", "/")


def _norm(value):
    return "".join(unicodedata.normalize("NFKC", value or "").split()).casefold()


def normalize_work_tg(value):
    """AE列工作TG -> "@用户名"；空白/占位/认不出来返回""。支持@xxx、t.me/xxx
    链接、单独写的用户名，别的文字不猜。"""
    value = unicodedata.normalize("NFKC", value or "").strip()
    if not value or value in _PLACEHOLDERS:
        return ""
    match = _AT_USERNAME_RE.search(value) or _TME_RE.search(value)
    if match:
        return "@" + match.group(1)
    if _USERNAME_ONLY_RE.match(value):
        return "@" + value
    return ""


def parse_roster_people(rows):
    """花名册行 -> 人员字典列表（跳过表头；B、C列都空的行跳过）。"""
    idx = {field: _col_index(letter) for field, letter in ROSTER_COLUMNS.items()}
    people = []
    for row in rows[DATA_START_INDEX:]:
        person = {field: _cell(row, i) for field, i in idx.items()}
        if not person["key_b"] and not person["key_c"]:
            continue
        people.append(person)
    return people


def select_hired_on(people, target_date):
    """AR列解析出的日期等于target_date的人；解析不了的行静默跳过。"""
    return [p for p in people if parse_training_date(p.get("date_raw")) == target_date]


def parse_wallet_entries(rows):
    """钱包表单行 -> 只保留F列恰好是"首次提交（新人入职）"的条目，每条是C、D两个
    非空值（规范化后）组成的集合；C、D都空的行跳过。"""
    idx = {field: _col_index(letter) for field, letter in FORM_COLUMNS.items()}
    wanted = _norm(WALLET_FIRST_SUBMIT_TYPE)
    entries = []
    for row in rows[DATA_START_INDEX:]:
        if _norm(_cell(row, idx["submit_type"])) != wanted:
            continue
        keys = frozenset(k for k in (_norm(_cell(row, idx["key_c"])), _norm(_cell(row, idx["key_d"]))) if k)
        if keys:
            entries.append(keys)
    return entries


def person_keys(person):
    return frozenset(k for k in (_norm(person.get("key_b")), _norm(person.get("key_c"))) if k)


def has_filled(person, entries):
    keys = person_keys(person)
    return bool(keys) and any(keys <= entry for entry in entries)


def person_label(person):
    """通知里显示的名字：优先C列，没有用B列。"""
    return person.get("key_c") or person.get("key_b") or "（未识别）"


def plan_wallet_reminders(roster_rows, wallet_rows, target_date):
    """返回dict：hired今日入职的人，filled已填写的人，to_remind需要提醒且有工作TG的人
    （带解析好的tg），no_tg需要提醒但AE列没有可用工作TG的人。tg相同的只留一个。"""
    hired = select_hired_on(parse_roster_people(roster_rows), target_date)
    entries = parse_wallet_entries(wallet_rows)
    filled, to_remind, no_tg, seen = [], [], [], set()
    for person in hired:
        if has_filled(person, entries):
            filled.append(person)
            continue
        tg = normalize_work_tg(person.get("work_tg"))
        if not tg:
            no_tg.append(person)
        elif tg.casefold() not in seen:
            seen.add(tg.casefold())
            to_remind.append({**person, "tg": tg})
    return {"hired": hired, "filled": filled, "to_remind": to_remind, "no_tg": no_tg}
