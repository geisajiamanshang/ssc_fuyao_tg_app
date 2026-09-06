# SSC Offer 审批流转自动化

用你自己的 Telegram 账号（userbot，基于 Telethon / MTProto）监听三个场景，
自动完成 Offer 审批消息在多个群之间的转发、@ 不同审批人、以及最终入职信息确认的发布。

## 目录结构

```
ssc_offer_bot/
├── config.py          # 所有配置项（群组、审批人、部门领导名单）
├── state_store.py      # 本地状态存储（JSON文件），记录每个候选人流程走到哪一步
├── parsers.py           # "字段名：值" 格式文本解析
├── templates.py          # 各阶段发送消息的拼接模板
├── list_chats.py          # 辅助脚本：列出所有会话的数字ID
├── main.py                 # 主程序，三个场景的事件监听都在这里
└── requirements.txt
```

## 零、把代码推到你自己的 GitHub 仓库 & 克隆到本地

这两步需要你自己的 GitHub 登录凭证，我这边没有也不会帮你输入密钥/token，所以这部分
命令你自己在自己电脑上执行。假设你已经下载了本次对话里的所有文件到一个文件夹。

**在你的 Mac 上：**

```bash
mkdir -p "/Users/xiaojie/香港银河hrssc/AIdoing/官方tg应用/tg_app"
cd "/Users/xiaojie/香港银河hrssc/AIdoing/官方tg应用/tg_app"

git init
git remote add origin https://github.com/geisajiamanshang/ssc_fuyao_tg_app.git

# 把下载下来的文件（config.py / main.py / ... / deploy.sh 等）复制到当前目录后：
git add .
git commit -m "SSC offer 审批流转自动化 - 初始版本"
git branch -M main
git push -u origin main
```

推送时如果要求登录，用你的 GitHub 用户名 + Personal Access Token（不是密码，GitHub
早就不支持密码推送了，token 在 GitHub 网页 Settings -> Developer settings ->
Personal access tokens 里生成）。

推送成功之后，以后在别的机器上（比如 VPS）想拿这份代码，直接：

```bash
git clone https://github.com/geisajiamanshang/ssc_fuyao_tg_app.git
```

## 一、准备工作

### 1. 安装依赖

```bash
pip3 install -r requirements.txt
```

### 2. 填写 API 凭证

不要把 `api_id` / `api_hash` 写进 `config.py`（这个文件会被提交到 git 仓库）。
正确做法：

```bash
cp .env.example .env
```

然后编辑 `.env`，填入真实值（你给我的是这两个）：

```
TG_API_ID=37215318
TG_API_HASH=6bab1e029ff36064ad7e68d73223a0c5
```

`.env` 已经在 `.gitignore` 里排除，不会被提交上去。

> 提醒一下：你在聊天里直接发的这个 `api_hash`，等同于你账号的一把钥匙的一部分，
> 建议只在自己本地 `.env` 文件里使用，别再贴到任何公开的地方（包括公开的GitHub仓库、
> issue、截图等）。

### 3. 获取群组的数字ID

群名字符串在 Telethon 里不一定能稳定匹配到（尤其是群名有特殊字符、或者你在多个群里
名字相似时），强烈建议换成数字ID。运行：

```bash
python3 list_chats.py
```

首次运行会要求输入手机号 + 验证码（如果开了两步验证，还要输入密码），登录成功后
会在当前目录生成一个 `ssc_offer_bot.session` 文件，以后不用重复登录。

运行后会打印类似：

```
[群组/频道] id=-1001234567890  name=恒睿SSC/HRBP-沟通群
[群组/频道] id=-1009876543210  name=恒睿公司-联合管理工作群
[群组/频道] id=-1005555555555  name=恒睿公司招聘群
```

把这三个数字ID复制到 `config.py` 里，替换掉：

```python
GROUP_HRBP = -1001234567890
GROUP_LEADERSHIP = -1009876543210
GROUP_RECRUIT = -1005555555555
```

### 4. 检查审批人用户名 & 部门领导名单

`config.py` 里的 `LEADER_FIRST` / `LEADER_SECOND_TECH` / `LEADER_FINAL` 和
`DEPARTMENT_LEADER_TAGS` 已经按你描述的例子填好了，如果实际用户名或部门规则有出入，
直接改这个文件就行，不用动其他代码。

## 二、先在测试群跑通全流程，再上线

**强烈建议**：找三个测试群（可以直接新建，随便拉几个小号或者自己单独建群模拟），
把 `config.py` 里的三个 `GROUP_*` 先指向测试群，手动模拟一遍完整流程：

1. 在测试版"HRBP群"里发一条符合格式的 offer 消息并 @ 自己
2. 确认转发到"联合管理工作群"的消息格式对不对
3. 用一级领导的测试账号回复"好的"，确认按部门走对了分支
4. 走完二级/终审，确认招聘群那条回复消息内容对不对
5. 用招聘账号私聊，确认最终【入职信息确认】拼出来的格式跟公司模板一致

确认没问题后，再把 `GROUP_*` 换回真实的群ID正式上线。

## 三、运行

前台测试（能直接看到日志输出，Ctrl+C 停止）：

```bash
python3 main.py
```

## 四、长期后台运行 —— 在 VPS 上部署

同样，SSH 上你自己的服务器这一步需要你自己的 SSH 凭证，我这边没有 SSH 工具、也连不到
任意 IP，所以这部分你自己在终端里操作。步骤：

```bash
ssh root@187.7.20.109

# 装好 git（如果还没有）
apt update && apt install -y git python3 python3-venv python3-pip

# 拉代码
git clone https://github.com/geisajiamanshang/ssc_fuyao_tg_app.git
cd ssc_fuyao_tg_app

# 跑一键部署脚本（建虚拟环境、装依赖、生成.env、打印systemd配置）
bash deploy.sh

# 按脚本提示编辑 .env 填入真实的 TG_API_ID / TG_API_HASH
nano .env

# 先手动跑一次，完成手机号+验证码登录（生成 session 文件）
.venv/bin/python3 list_chats.py
# 把打印出来的群组ID填进 config.py 里的 GROUP_HRBP / GROUP_LEADERSHIP / GROUP_RECRUIT

# 验证没问题后，把 deploy.sh 打印出来的 systemd 配置内容
# 复制到 /etc/systemd/system/ssc-offer-bot.service，然后：
sudo systemctl daemon-reload
sudo systemctl enable ssc-offer-bot
sudo systemctl start ssc-offer-bot
sudo journalctl -u ssc-offer-bot -f   # 查看实时日志
```

也可以不用 systemd，简单用 nohup 或 tmux：

```bash
# nohup
nohup .venv/bin/python3 main.py > /dev/null 2>&1 &

# 或 tmux（推荐，方便随时进去看状态）
tmux new -s ssc_bot
.venv/bin/python3 main.py
# 按 Ctrl+B 再按 D 退出但不停止；下次用 tmux attach -t ssc_bot 重新进入
```

### 关于用 root 运行

长期用 root 跑这个进程不是最佳实践（一旦脚本或依赖有漏洞，风险面是整台服务器）。
如果条件允许，建议建一个普通用户专门跑这个服务：

```bash
adduser sscbot
su - sscbot
# 之后的 git clone / bash deploy.sh 等操作都用这个用户做
```

不是必须，只是一个建议。

## 五、日志与状态

- `bot.log`：所有处理记录、警告都会写在这里，出问题先看这个文件。
- `offer_state.json`：每个候选人当前流程状态，可以直接打开看，方便排查"卡在哪一步了"。
  如果某个候选人流程卡住，可以手动编辑这个文件纠正状态，或者删掉对应记录重新走一遍。

## 六、后续如果消息格式对不上，改这几个地方

- **场景一解析不出候选人姓名/编制组织**：检查 HRBP 群实际消息里字段名是不是正好叫
  "候选人姓名"、"编制组织"（`parsers.py` 里 `get_field` 支持传多个候选字段名，
  比如 `get_field(fields, "编制组织", "入职编制组织")`，可以按需要增加别名）。
- **开头/结尾替换不对**：改 `parsers.py` 里的 `strip_header_footer()` 正则。
- **各阶段发送的消息文字/排版跟公司实际模板不一致**：改 `templates.py`，都是普通
  字符串拼接，照着实际模板改字段顺序、换行、emoji 就行。
- **部门 -> 领导名单没覆盖到某个团队**：在 `config.py` 的 `DEPARTMENT_LEADER_TAGS`
  里加一条规则。没匹配到规则时会用 `DEFAULT_LEADERS` 兜底，并在日志里报警告，
  运行一段时间后翻一下日志就知道哪些部门规则还没补全。

## 七、需要你知道的风险

- 这是用你个人账号运行的自动化脚本（userbot），不是官方 Bot，理论上不完全符合
  Telegram 官方条款里关于自动化的部分。正常使用频率（几个群、按事件触发，不是高频
  轮询）一般不会有问题，但请自行评估这个风险。
- 脚本会自动往真实工作群发消息、自动回复审批人和领导，建议先按上面"测试群跑通"
  的步骤确认无误，避免在正式群里发错消息造成误会。
