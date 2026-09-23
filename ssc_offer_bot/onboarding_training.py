# -*- coding: utf-8 -*-
"""新人培训考试通过后，按TG用户名在Drive中查找该新人的入职信息并拆分为分区。

入职助手/输出 文件夹下每个新人一份独立 TXT（可能直接放在输出文件夹，也可能按
日期/月份子文件夹存放；同一天可能有多个人），文件内容用与转正信息相同的
【段落名】标题分区约定，但每份文件只对应一个人，不需要转正模块里“多人汇总/
旧版本-新版本”的去重逻辑。

三个需要经收藏夹审批放行的分区名固定为：新人入职通知 / 入职信息同步 / 欢迎；
文件里出现的其它分区一律作为参考资料，原样分条发到收藏夹，不设审批码。
"""

import re

from daily_reports import DRIVE_FILES_URL, _drive_session


GATED_SECTION_NAMES = ("新人入职通知", "入职信息同步", "欢迎")
_SECTION_RE = re.compile(r"(?m)^[ \t]*【(?P<name>[^【】\r\n]+)】[ \t]*$")
_TG_FIELD_RE = re.compile(r"(?:TG|Telegram|telegram)\s*[:：@]*\s*@?([A-Za-z][A-Za-z0-9_]{3,})")


def _escape_query(value):
    return value.replace("\\", "\\\\").replace("'", "\\'")


def split_named_sections(text):
    """按【段落名】切分文本，返回 [(name, body), ...]，保留原始出现顺序。"""
    matches = list(_SECTION_RE.finditer(text or ""))
    sections = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        sections.append((match.group("name"), body))
    return sections


def username_matches_text(username, text):
    """判断文件内容是否属于该TG用户名：优先匹配显式TG字段，兜底做全文子串匹配。"""
    if not username or not text:
        return False
    target = username.lstrip("@").casefold()
    for field_match in _TG_FIELD_RE.finditer(text):
        if field_match.group(1).casefold() == target:
            return True
    compact = text.casefold()
    return f"@{target}" in compact or target in compact


class OnboardingTrainingDriveRepository:
    def __init__(self, output_folder_id):
        self.output_folder_id = output_folder_id

    @staticmethod
    def _list_children(session, auth_params, folder_id):
        params = {
            **auth_params,
            "q": f"'{_escape_query(folder_id)}' in parents and trashed = false",
            "fields": "files(id,name,mimeType,modifiedTime,size)",
            "orderBy": "modifiedTime desc",
            "pageSize": 100,
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        response = session.get(DRIVE_FILES_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json().get("files", [])

    @staticmethod
    def _download_text(session, auth_params, drive_file):
        url = f"{DRIVE_FILES_URL}/{drive_file['id']}"
        response = session.get(
            url, params={**auth_params, "alt": "media"}, timeout=120
        )
        response.raise_for_status()
        raw = response.content
        encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            raise ValueError(
                "入职信息文件编码无法识别，请将 TXT 保存为 UTF-8 后重试"
            ) from exc
        return text.replace("\r\n", "\n").replace("\r", "\n")

    def _recent_candidate_files(self, session, auth_params, limit=30):
        """输出文件夹下既可能直接放TXT，也可能按日期/月份子文件夹存放；
        两种结构都收集，按修改时间倒序，最近修改的文件优先扫描。"""
        folder_mime = "application/vnd.google-apps.folder"
        top_level = self._list_children(session, auth_params, self.output_folder_id)

        candidates = [
            item for item in top_level
            if item.get("mimeType") != folder_mime
            and item.get("name", "").lower().endswith(".txt")
        ]

        subfolders = sorted(
            (item for item in top_level if item.get("mimeType") == folder_mime),
            key=lambda item: item.get("modifiedTime", ""),
            reverse=True,
        )
        for subfolder in subfolders[:5]:
            children = self._list_children(session, auth_params, subfolder["id"])
            candidates.extend(
                item for item in children
                if item.get("mimeType") != folder_mime
                and item.get("name", "").lower().endswith(".txt")
            )

        candidates.sort(key=lambda item: item.get("modifiedTime", ""), reverse=True)
        return candidates[:limit]

    def find_by_username(self, username):
        """按TG用户名在最近修改的候选文件里查找该新人的入职信息全文。"""
        session, auth_params = _drive_session()
        candidates = self._recent_candidate_files(session, auth_params)
        for drive_file in candidates:
            text = self._download_text(session, auth_params, drive_file)
            if username_matches_text(username, text):
                return text, drive_file
        raise FileNotFoundError(f"未在入职助手/输出文件夹中找到 @{username.lstrip('@')} 的入职信息")
