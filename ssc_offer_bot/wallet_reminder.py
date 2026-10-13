# -*- coding: utf-8 -*-
"""场景十五：SSC在自己的收藏夹发带"钱包提醒"关键词的消息，触发：
1. 花名册（机器人）里AR列（入职日期）是今天的人员；
2. 用花名册B列去钱包表单找：表单D列等于这个人的B列、并且F列恰好是
   "首次提交（新人入职）"的条目，找得到就算已填写（只按这一条规则，没有别的匹配方式）；
3. 没填写的人，向他的工作TG（花名册AE列）发提醒：
   "请及时填写钱包表单并发送邮件给ssc，详细规则查看扶摇-ssc-bot 机器人 新人入职通知 待办事项2"。
草稿先发收藏夹，经审批码17（测试17）放行后逐个私发。

比较时不分大小写、去空格、全半角统一；空白单元格不参与比较。花名册B列为空的人
没法核对是否填写，不当成"没填"去提醒，而是单独列出来请SSC人工确认。花名册C列只
用来在通知里显示名字，不参与匹配。
纯逻辑单独放在这里，不涉及Telegram调用，方便独立测试；表格读取复用
training_sync.TrainingSyncRosterRepository（只读）。
"""

import re
import unicodedata

from training_sync import _cell, _col_index, parse_training_date

WALLET_REMINDER_MESSAGE = "请及时填写钱包表单并发送邮件给ssc，详细规则查看扶摇-ssc-bot 机器人 新人入职通知 待办事项2"
WALLET_FIRST_SUBMIT_TYPE = "首次提交（新人入职）"

# 花名册（机器人）：表头1行，数据从第2行开始（跟培训同步用的是同一张表）。
# B列用来匹配；C列只用于显示名字。
ROSTER_COLUMNS = {"key_b": "B", "name_c": "C", "date_raw": "AR", "work_tg": "AE"}
# 钱包表单：第1行表头。D列确认员工，F列是提交类型。
FORM_COLUMNS = {"key_d": "D", "submit_type": "F"}
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
        if not person["key_b"] and not person["name_c"]:
            continue
        people.append(person)
    return people


def select_hired_on(people, target_date):
    """AR列解析出的日期等于target_date的人；解析不了的行静默跳过。"""
    return [p for p in people if parse_training_date(p.get("date_raw")) == target_date]


def parse_wallet_entries(rows):
    """钱包表单行 -> 只保留F列恰好是"首次提交（新人入职）"的条目，返回这些条目D列
    值（规范化后）的集合；D列为空的行跳过。"""
    idx = {field: _col_index(letter) for field, letter in FORM_COLUMNS.items()}
    wanted = _norm(WALLET_FIRST_SUBMIT_TYPE)
    entries = set()
    for row in rows[DATA_START_INDEX:]:
        if _norm(_cell(row, idx["submit_type"])) != wanted:
            continue
        key = _norm(_cell(row, idx["key_d"]))
        if key:
            entries.add(key)
    return entries


def has_filled(person, entries):
    """花名册B列的值出现在这些条目的D列里就算已填写；B列为空返回False（由调用方
    另外处理"无法核对"）。"""
    key = _norm(person.get("key_b"))
    return bool(key) and key in entries


def person_label(person):
    """通知里显示的名字：优先C列，没有用B列。"""
    return person.get("name_c") or person.get("key_b") or "（未识别）"


def plan_wallet_reminders(roster_rows, wallet_rows, target_date):
    """返回dict：hired今日入职的人，filled已填写的人，to_remind需要提醒且有工作TG的人
    （带解析好的tg），no_tg需要提醒但AE列没有可用工作TG的人，unverifiable花名册B列
    为空、没法核对的人（不提醒）。tg相同的只留一个。"""
    hired = select_hired_on(parse_roster_people(roster_rows), target_date)
    entries = parse_wallet_entries(wallet_rows)
    filled, to_remind, no_tg, unverifiable, seen = [], [], [], [], set()
    for person in hired:
        if not _norm(person.get("key_b")):
            unverifiable.append(person)
            continue
        if has_filled(person, entries):
            filled.append(person)
            continue
        tg = normalize_work_tg(person.get("work_tg"))
        if not tg:
            no_tg.append(person)
        elif tg.casefold() not in seen:
            seen.add(tg.casefold())
            to_remind.append({**person, "tg": tg})
    return {"hired": hired, "filled": filled, "to_remind": to_remind,
            "no_tg": no_tg, "unverifiable": unverifiable}
