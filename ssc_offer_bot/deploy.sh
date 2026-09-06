#!/usr/bin/env bash
# VPS 部署脚本。
# 用法：SSH 上服务器后，在你想放代码的目录下执行：
#   bash deploy.sh
#
# 会做的事：
#   1. 安装 python3-venv（如果没有）
#   2. 创建虚拟环境并安装依赖
#   3. 提示你填写 .env
#   4. 生成 systemd service 文件（需要你自己 sudo 启用，脚本会打印命令，不会替你执行 sudo）
#
# 前提：代码已经在当前目录（比如你已经 git clone 下来了）。

set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="ssc-offer-bot"
PYTHON_BIN="python3"

echo "== 部署目录: $APP_DIR =="

if ! command -v $PYTHON_BIN >/dev/null 2>&1; then
  echo "未找到 python3，请先安装（例如 Debian/Ubuntu: apt update && apt install -y python3 python3-venv python3-pip）"
  exit 1
fi

echo "== 创建虚拟环境 (.venv) =="
$PYTHON_BIN -m venv "$APP_DIR/.venv"

echo "== 安装依赖 =="
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo ""
  echo "!! 已生成 .env 文件，请编辑填入真实的 TG_API_ID / TG_API_HASH:"
  echo "   nano $APP_DIR/.env"
  echo ""
fi

echo "== 生成 systemd service 文件（内容如下，需要你自己复制到 /etc/systemd/system/） =="
cat <<EOF

# ---- 复制以下内容到 /etc/systemd/system/${SERVICE_NAME}.service ----
[Unit]
Description=SSC Offer Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}
ExecStart=${APP_DIR}/.venv/bin/python3 ${APP_DIR}/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
# ---- 复制到此为止 ----

然后执行：
  sudo systemctl daemon-reload
  sudo systemctl enable ${SERVICE_NAME}
  sudo systemctl start ${SERVICE_NAME}
  sudo journalctl -u ${SERVICE_NAME} -f     # 查看实时日志

注意：第一次启动前，建议先用下面命令手动登录一次（需要输入手机号+验证码），
避免 systemd 后台启动时卡在等待交互式验证码输入：
  ${APP_DIR}/.venv/bin/python3 ${APP_DIR}/list_chats.py

EOF

echo "== 完成 =="
