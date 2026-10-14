# -*- coding: utf-8 -*-
"""场景十六：SSC在自己的收藏夹收到带"培训通知"关键词的消息，触发：
1. 花名册（机器人）G列（入职日期）是今天的人；
2. 向他们的私人TG（AF列）私发：进培训学习群的链接 + "进群自学pdf 和 视频 并参加考试哦"。
草稿先发收藏夹，经审批码18（测试18）放行后逐个私发。

纯逻辑单独放在这里，不涉及Telegram调用，方便独立测试；表格读取复用
training_sync.TrainingSyncRosterRepository（只读）。花名册C列只用来显示名字。
"""

from training_sync import _cell, _col_index, parse_training_date
from wallet_reminder import normalize_work_tg

TRAINING_NOTICE_LINK = "https://t.me/+gL8gzMBNRNZlYWVl"
TRAINING_NOTICE_MESSAGE = TRAINING_NOTICE_LINK + "\n\n进群自学pdf 和 视频 并参加考试哦"

# 花名册（机器人）：表头1行，数据从第2行开始。G=入职日期，AF=私人TG，C=名字（只显示用）。
ROSTER_COLUMNS = {"name_c": "C", "date_raw": "G", "private_tg": "AF"}
DATA_START_INDEX = 1


def parse_people(rows):
    idx = {field: _col_index(letter) for field, letter in ROSTER_COLUMNS.items()}
    people = []
    for row in rows[DATA_START_INDEX:]:
        person = {field: _cell(row, i) for field, i in idx.items()}
        if not person["name_c"] and not person["private_tg"]:
            continue
        people.append(person)
    return people


def person_label(person):
    return person.get("name_c") or person.get("private_tg") or "（未识别）"


def plan_training_notices(rows, target_date):
    """返回dict：hired今日入职的人，to_send有可用私人TG的人（带解析好的tg，tg相同只留一个），
    no_tg私人TG（AF列）为空或认不出来的人。"""
    hired = [p for p in parse_people(rows) if parse_training_date(p.get("date_raw")) == target_date]
    to_send, no_tg, seen = [], [], set()
    for person in hired:
        tg = normalize_work_tg(person.get("private_tg"))
        if not tg:
            no_tg.append(person)
        elif tg.casefold() not in seen:
            seen.add(tg.casefold())
            to_send.append({**person, "tg": tg})
    return {"hired": hired, "to_send": to_send, "no_tg": no_tg}
