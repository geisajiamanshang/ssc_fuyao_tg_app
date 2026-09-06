# -*- coding: utf-8 -*-
"""
辅助脚本：列出你账号下所有会话（群组/频道/私聊）的名字和数字ID。

首次登录会要求输入手机号 + 收到的验证码（以及如果开了两步验证，还要输入密码）。
运行一次后，session 文件会保存登录状态，以后不用重复登录。

用法：
    python3 list_chats.py

把输出里对应群组名字后面的数字ID，复制到 config.py 里替换掉群名字符串，
用数字ID比用群名字符串更稳定可靠。
"""

import asyncio
from telethon import TelegramClient

import config

client = TelegramClient(config.SESSION_NAME, config.API_ID, config.API_HASH)


async def main():
    await client.start()
    print("正在获取会话列表...\n")
    async for dialog in client.iter_dialogs():
        kind = "群组/频道" if dialog.is_group or dialog.is_channel else "私聊"
        print(f"[{kind}] id={dialog.id}  name={dialog.name}")


if __name__ == "__main__":
    with client:
        client.loop.run_until_complete(main())
