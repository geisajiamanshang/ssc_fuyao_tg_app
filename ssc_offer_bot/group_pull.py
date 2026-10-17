# -*- coding: utf-8 -*-
"""场景十七：SSC在自己的收藏夹发"拉人"，从花名册里找出M列（编制组织）是"技术中心"的人，
把他们的工作TG（AE列）拉进指定群，并把名单按"花名 工作tg"一行一个列出来。

纯逻辑单独放在这里，不涉及Telegram调用，方便独立测试；表格读取复用
training_sync.TrainingSyncRosterRepository（只读）。

拉人是对真人的操作，列位置又是SSC口头给的（M列、AE列），而花名册里别的功能记录的
布局是编制组织在L列、工作TG在AD列、AE列是私人联系方式，两边对不上。所以先核对表头：
M列表头不含"编制组织"、AE列表头不含"TG"就不拉人，把实际表头和按表头文字找到的列
告诉SSC，由SSC确认后再改。
"""

from training_sync import _cell, _col_index
from wallet_reminder import normalize_work_tg

ROSTER_COLUMNS = {"name": "C", "center": "M", "work_tg": "AE"}
CENTER_HEADER_WORD = "编制组织"
TG_HEADER_WORD = "TG"
NAME_HEADER_WORD = "花名"
HEADER_SEARCH_ROWS = 6


def _col_letter(index):
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def find_header_row(rows):
    """前几行里C列表头含"花名"的那一行的下标；找不到返回None。"""
    c = _col_index(ROSTER_COLUMNS["name"])
    for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        if NAME_HEADER_WORD in _cell(row, c):
            return i
    return None


def check_headers(rows):
    """返回 (ok, 说明)。ok为False时说明里写明实际表头和按表头文字找到的列。"""
    header_index = find_header_row(rows)
    if header_index is None:
        return False, f"前{HEADER_SEARCH_ROWS}行里找不到C列表头含“{NAME_HEADER_WORD}”的表头行"
    header = rows[header_index]
    center_col = _col_index(ROSTER_COLUMNS["center"])
    tg_col = _col_index(ROSTER_COLUMNS["work_tg"])
    center_text, tg_text = _cell(header, center_col), _cell(header, tg_col)
    if CENTER_HEADER_WORD in center_text and TG_HEADER_WORD in tg_text.upper():
        return True, ""
    by_center = [_col_letter(i) for i in range(len(header)) if CENTER_HEADER_WORD in _cell(header, i)]
    by_tg = [_col_letter(i) for i in range(len(header)) if "工作" in _cell(header, i)
             and TG_HEADER_WORD in _cell(header, i).upper()]
    return False, (
        f"表头对不上：{ROSTER_COLUMNS['center']}列表头是“{center_text}”，{ROSTER_COLUMNS['work_tg']}列表头是“{tg_text}”；"
        f"表头含“{CENTER_HEADER_WORD}”的列是{'、'.join(by_center) or '没找到'}，"
        f"表头含“工作TG”的列是{'、'.join(by_tg) or '没找到'}"
    )


def plan_group_pull(rows, center_word="技术中心"):
    """返回dict：people（花名+解析好的tg，tg相同只留一个）、no_tg（AE列为空或认不出来的人）。
    调用前先用check_headers核对表头。"""
    header_index = find_header_row(rows)
    start = 0 if header_index is None else header_index + 1
    idx = {field: _col_index(letter) for field, letter in ROSTER_COLUMNS.items()}
    people, no_tg, seen = [], [], set()
    for row in rows[start:]:
        name = _cell(row, idx["name"])
        if not name or center_word not in _cell(row, idx["center"]):
            continue
        tg = normalize_work_tg(_cell(row, idx["work_tg"]))
        if not tg:
            no_tg.append({"name": name, "raw": _cell(row, idx["work_tg"])})
        elif tg.casefold() not in seen:
            seen.add(tg.casefold())
            people.append({"name": name, "tg": tg})
    return {"people": people, "no_tg": no_tg}


def format_people(people):
    """"花名 工作tg"，一行一个。"""
    return "\n".join(f"{p['name']} {p['tg']}" for p in people)


def chunk_lines(text, limit=3500):
    """Telegram单条消息有长度上限，按行切成几段。"""
    chunks, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks
