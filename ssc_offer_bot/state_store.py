# -*- coding: utf-8 -*-
"""
本地状态存储：用一个 JSON 文件记录每个候选人当前走到流程的哪一步。

数据结构（每个候选人一条记录，key = 候选人姓名）：
{
  "张三": {
    "candidate_name": "张三",
    "org_unit": "技术中心",
    "hrbp_username": "someone",
    "offer_confirm_msg_id": 12345,       # 发到联合管理工作群的【offer信息确认】消息ID
    "second_review_msg_id": 12346,       # 二级审批回复的消息ID（仅技术中心会有）
    "final_review_msg_id": 12347,        # 终审回复的消息ID
    "recruiter_username": "zhaoyang312", # 招聘群里发简历的人
    "resume_msg_id": 999,                # 招聘群里简历消息的ID
    "position": "...",
    "salary_confirm": "...",
    "salary_probation": "...",
    "raw_fields": {...},                 # 场景一原始消息解析出的所有字段
    "stage": "sent_to_leadership"        # 状态机见下方
  }
}

stage 状态机取值：
  sent_to_leadership      -> 已转发到联合管理工作群，等一级领导回复"好的"
  waiting_second_review   -> （技术中心）等二级审批人回复
  waiting_final_review    -> 等终审人回复
  waiting_recruiter_dm    -> 终审已通过，已在招聘群回复，等招聘私聊补充入职信息
  done                    -> 流程结束
  final_approved_no_resume_found -> 终审通过但在招聘群没找到对应简历消息，需要人工介入
"""

import json
import os
import tempfile
from threading import Lock


class StateStore:
    def __init__(self, path: str):
        self.path = path
        self.lock = Lock()
        self.data = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            with open(self.path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {}

    def _save(self):
        d = os.path.dirname(os.path.abspath(self.path)) or "."
        fd, tmp_path = tempfile.mkstemp(dir=d)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.path)
        except Exception:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise

    def get(self, candidate_name: str):
        return self.data.get(candidate_name)

    def set(self, candidate_name: str, record: dict):
        with self.lock:
            self.data[candidate_name] = record
            self._save()

    def update(self, candidate_name: str, **kwargs):
        with self.lock:
            rec = self.data.setdefault(candidate_name, {"candidate_name": candidate_name})
            rec.update(kwargs)
            self._save()

    def all(self):
        return self.data

    def find_by_field(self, field: str, value):
        """按某个字段值（比如某条消息ID）找到对应候选人记录。"""
        if value is None:
            return None, None
        for name, rec in self.data.items():
            if rec.get(field) == value:
                return name, rec
        return None, None

    def find_pending_for_recruiter(self, recruiter_username: str, text: str):
        """
        在招聘私聊消息里，找出这条消息对应的是哪个候选人。
        优先用候选人姓名是否出现在私聊文本里来判断；
        如果这个招聘只有一个候选人在等待，就直接用那一条。
        """
        candidates = [
            (name, rec)
            for name, rec in self.data.items()
            if rec.get("recruiter_username") == recruiter_username
            and rec.get("stage") == "waiting_recruiter_dm"
        ]
        for name, rec in candidates:
            if name and name in text:
                return name, rec
        if len(candidates) == 1:
            return candidates[0]
        return None, None
