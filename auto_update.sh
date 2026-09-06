#!/usr/bin/env bash
# 自动拉取 GitHub 最新代码并重启服务，配合 crontab 定时执行使用。
#
# 用法（在VPS上，仓库目录下手动测试一次）：
#   bash auto_update.sh
#
# 配合 crontab 定时跑，比如每5分钟检查一次有没有新代码：
#   crontab -e
#   然后加一行（把路径换成你实际的部署路径）：
#   */5 * * * * /bin/bash /root/ssc_fuyao_tg_app/auto_update.sh >> /root/ssc_fuyao_tg_app/update.log 2>&1

set -e

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_NAME="ssc-offer-bot"
BRANCH="main"

cd "$APP_DIR"

BEFORE=$(git rev-parse HEAD)
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" == "$AFTER" ]; then
    echo "$(date '+%F %T') 没有新代码，跳过"
    exit 0
fi

echo "$(date '+%F %T') 检测到新代码：$BEFORE -> $AFTER"

# requirements.txt 有变化时才重新安装依赖，节省时间
if git diff --name-only "$BEFORE" "$AFTER" | grep -q "requirements.txt"; then
    echo "requirements.txt 有变化，重新安装依赖"
    "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
fi

echo "重启服务 $SERVICE_NAME"
systemctl restart "$SERVICE_NAME"
