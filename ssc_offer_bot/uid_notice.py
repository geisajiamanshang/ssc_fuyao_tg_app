# -*- coding: utf-8 -*-
"""场景十八：SSC在自己的收藏夹发"通知uid"，机器人等SSC发人员名单（花名），到花名册里
按花名找到每个人的工作TG（AE列），每人一条"请尽快注册stow钱包并填写钱包表单"草稿进收藏夹，
经审批码19（测试19）放行后逐个私发。

列位置按表头文字找（C列"花名"、AE列"工作TG"），不写死字母：花名册的版本升级过，
有的版本工作TG在AD列、有的在AE列，按表头找不会找错列。

纯逻辑单独放在这里，不涉及Telegram调用，方便独立测试；表格读取复用
training_sync.TrainingSyncRosterRepository（只读）。
"""

import re
import unicodedata

from training_sync import _cell
from wallet_reminder import normalize_work_tg

UID_NOTICE_MESSAGE = "请尽快注册stow钱包并填写钱包表单，否则会影响发薪流程"

HEADER_SEARCH_ROWS = 6
NAME_HEADER_WORD = "花名"
TG_HEADER_WORDS = ("工作", "tg")
STATUS_HEADER_WORD = "在职状态"

_SPLIT_RE = re.compile(r"[\s,，、;；/　]+")
# 名字/TG用户名里允许出现的字符：文字、数字、下划线、@、点、横杠、间隔号。
# 句子里的标点（：。（）→ 等）都不在内，机器人自己发的提示因此不会被当成名单。
_TOKEN_RE = re.compile(r"^[\w@.\-·]+$")
MAX_TOKEN_LEN = 33
MAX_TOKENS = 200


def _norm(value):
    return "".join(unicodedata.normalize("NFKC", value or "").split()).casefold().replace("*", "")


def parse_name_list(text):
    """名单文本 -> 去重后的名字/TG列表（保持顺序）。纯数字的（序号、审批码）丢掉。
    出现不像名字的内容（句子、标点、过长）、或者个数不合理时返回None，表示这条消息
    不是名单，调用方不要当名单处理。"""
    tokens, seen = [], set()
    for raw in _SPLIT_RE.split(text or ""):
        token = raw.strip()
        if not token:
            continue
        if len(token) > MAX_TOKEN_LEN or not _TOKEN_RE.match(token):
            return None
        if token.replace(".", "").isdigit():
            continue
        key = _norm(token)
        if key not in seen:
            seen.add(key)
            tokens.append(token)
    if not tokens or len(tokens) > MAX_TOKENS:
        return None
    return tokens


def _col_letter(index):
    letters = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def find_columns(rows):
    """按表头文字找列：返回 (header_index, name_col, tg_col, status_col)；找不到表头行或
    花名/工作TG列返回None。status_col可能是None。"""
    for i, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        # 表头格子写的就是"花名"（可带*号）；"在职花名册"这种标题行不算。
        name_col = next((c for c in range(len(row)) if _norm(_cell(row, c)) == NAME_HEADER_WORD), None)
        tg_col = next(
            (c for c in range(len(row))
             if all(word in _cell(row, c).casefold() for word in TG_HEADER_WORDS)),
            None,
        )
        if name_col is None or tg_col is None:
            continue
        status_col = next((c for c in range(len(row)) if STATUS_HEADER_WORD in _cell(row, c)), None)
        return i, name_col, tg_col, status_col
    return None


def describe_columns(rows):
    cols = find_columns(rows)
    if cols is None:
        return (f"前{HEADER_SEARCH_ROWS}行里找不到表头含“{NAME_HEADER_WORD}”的行，"
                f"或者表头里没有“工作TG”这一列")
    _, name_col, tg_col, _ = cols
    return f"花名在{_col_letter(name_col)}列，工作TG在{_col_letter(tg_col)}列"


def plan_uid_notices(rows, tokens):
    """tokens里的每一项按花名（或直接写的@工作TG）在花名册里找人。返回dict：
    to_send   [{name, tg, status}] 找到且有可用工作TG的人（tg相同只留一个）
    no_tg     [{name}] 找到了但工作TG列为空/认不出来
    not_found [token] 花名册里没有这个花名
    ambiguous [token] 同名多个人且工作TG不同，没法确定是谁（不发）
    调用前先用find_columns确认表头。"""
    header_index, name_col, tg_col, status_col = find_columns(rows)
    people = []
    for row in rows[header_index + 1:]:
        name = _cell(row, name_col)
        if not name:
            continue
        people.append({
            "name": name,
            "key": _norm(name),
            "tg": normalize_work_tg(_cell(row, tg_col)),
            "status": _cell(row, status_col) if status_col is not None else "",
        })
    to_send, no_tg, not_found, ambiguous, seen_tg = [], [], [], [], set()
    for token in tokens:
        as_tg = normalize_work_tg(token) if token.startswith("@") else ""
        if as_tg:
            matches = [p for p in people if p["tg"].casefold() == as_tg.casefold()]
        else:
            matches = [p for p in people if p["key"] == _norm(token)]
        if not matches:
            not_found.append(token)
            continue
        active = [p for p in matches if p["status"] == "在职"]
        matches = active or matches
        if len({p["tg"].casefold() for p in matches}) > 1:
            ambiguous.append(token)
            continue
        person = matches[0]
        if not person["tg"]:
            no_tg.append({"name": person["name"]})
        elif person["tg"].casefold() not in seen_tg:
            seen_tg.add(person["tg"].casefold())
            to_send.append({"name": person["name"], "tg": person["tg"], "status": person["status"]})
    return {"to_send": to_send, "no_tg": no_tg, "not_found": not_found, "ambiguous": ambiguous}
