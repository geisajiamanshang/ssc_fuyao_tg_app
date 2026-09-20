#!/usr/bin/env bash
# 对应实例只跟随自己的固定分支：bash auto_update.sh test|prod
set -euo pipefail

ENVIRONMENT="${1:-}"
case "$ENVIRONMENT" in
  test) BRANCH="test"; SERVICE_NAME="ssc-offer-bot-test" ;;
  prod) BRANCH="main"; SERVICE_NAME="ssc-offer-bot-prod" ;;
  *) echo "用法: bash auto_update.sh test|prod" >&2; exit 2 ;;
esac

APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOT_DIR="$APP_ROOT/ssc_offer_bot"

if [[ "$(git -C "$APP_ROOT" branch --show-current)" != "$BRANCH" ]]; then
  echo "拒绝更新：$ENVIRONMENT 实例只能跟随 $BRANCH 分支" >&2
  exit 1
fi
if [[ -n "$(git -C "$APP_ROOT" status --porcelain)" ]]; then
  echo "拒绝更新：仓库存在未提交修改" >&2
  exit 1
fi

BEFORE="$(git -C "$APP_ROOT" rev-parse HEAD)"
git -C "$APP_ROOT" fetch origin "$BRANCH"
git -C "$APP_ROOT" merge --ff-only "origin/$BRANCH"
AFTER="$(git -C "$APP_ROOT" rev-parse HEAD)"

if [[ "$BEFORE" == "$AFTER" ]]; then
  echo "$(date '+%F %T') 没有新代码"
  exit 0
fi

if git -C "$APP_ROOT" diff --name-only "$BEFORE" "$AFTER" | grep -q 'requirements.txt'; then
  "$APP_ROOT/.venv/bin/pip" install -r "$BOT_DIR/requirements.txt"
fi
(cd "$BOT_DIR" && "$APP_ROOT/.venv/bin/python" -m unittest discover -p 'test_*.py')
systemctl restart "$SERVICE_NAME"
systemctl --no-pager --full status "$SERVICE_NAME"
