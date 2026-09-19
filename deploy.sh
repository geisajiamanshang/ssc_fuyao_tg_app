#!/usr/bin/env bash
# 在独立目录部署测试或生产实例：bash deploy.sh test|prod
set -euo pipefail

ENVIRONMENT="${1:-}"
case "$ENVIRONMENT" in
  test) BRANCH="test"; SERVICE_NAME="ssc-offer-bot-test" ;;
  prod) BRANCH="main"; SERVICE_NAME="ssc-offer-bot-prod" ;;
  *) echo "用法: bash deploy.sh test|prod" >&2; exit 2 ;;
esac

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$APP_ROOT/ssc_offer_bot"
CURRENT_BRANCH="$(git -C "$APP_ROOT" branch --show-current)"

if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
  echo "拒绝部署：$ENVIRONMENT 环境必须使用 $BRANCH 分支，当前是 $CURRENT_BRANCH" >&2
  exit 1
fi
if [[ -n "$(git -C "$APP_ROOT" status --porcelain)" ]]; then
  echo "拒绝部署：仓库存在未提交修改" >&2
  exit 1
fi

ENV_FILE="$BOT_DIR/.env.$ENVIRONMENT"
if [[ ! -f "$ENV_FILE" ]]; then
  cp "$BOT_DIR/.env.$ENVIRONMENT.example" "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "已创建 $ENV_FILE。填入真实密钥后重新执行部署；该文件不会提交 Git。" >&2
  exit 2
fi

python3 -m venv "$APP_ROOT/.venv"
"$APP_ROOT/.venv/bin/pip" install --upgrade pip
"$APP_ROOT/.venv/bin/pip" install -r "$BOT_DIR/requirements.txt"

echo "运行自动化测试……"
(cd "$BOT_DIR" && "$APP_ROOT/.venv/bin/python" -m unittest discover -p 'test_*.py')

SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=SSC Offer Bot ($ENVIRONMENT)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$BOT_DIR
Environment=BOT_ENV=$ENVIRONMENT
ExecStart=$APP_ROOT/.venv/bin/python $BOT_DIR/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
systemctl --no-pager --full status "$SERVICE_NAME"
