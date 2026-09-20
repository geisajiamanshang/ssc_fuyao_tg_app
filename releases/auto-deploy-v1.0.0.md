# Prod 自动部署监控 v1.0.0

发布日期：2026-09-21
版本标识：auto-deploy-v1.0.0
用户确认在 VPS 的 `/root/ssc_fuyao_tg_app_prod` 目录以 crontab 定时执行 `auto_update.sh prod`，实现"main 分支有新合并 -> 自动拉取 -> 自动重启"。

## 功能范围

- `auto_update.sh test|prod`：按参数固定跟随各自分支（test -> `test` 分支，prod -> `main` 分支），拒绝在错误分支或存在未提交修改时更新。
- 有新提交时：`git merge --ff-only` 拉取（只快进，不会用 `reset --hard` 丢弃任何本地提交）；若 `requirements.txt` 变化则重装依赖；随后跑一遍仓库自带的 `unittest` 全量测试。
- **测试没通过就不重启服务**：`set -euo pipefail` 下，测试失败会让脚本在 `systemctl restart` 之前就非零退出，此时代码已经落地到工作区，但正在跑的旧进程不受影响，继续用回滚前的代码提供服务，直到下一次拉到能通过测试的提交为止。
- `deploy.sh test|prod`：与 `auto_update.sh` 共用同一套分支/服务名映射（`ssc-offer-bot-test` / `ssc-offer-bot-prod`），用于从零搭建 systemd 服务。

## 验证

在本地沙盒（伪造 git remote + 伪造 systemctl）里跑过以下 5 个场景，行为均符合预期：

1. 无新提交 -> 直接退出，不触碰服务。
2. 新提交且测试全部通过 -> 拉取代码、跑测试、`systemctl restart ssc-offer-bot-prod`。
3. 新提交但测试有失败 -> 代码落地但**不会**调用 `systemctl restart`，旧进程继续运行。
4. 部署目录存在未提交的本地修改 -> 拒绝更新。
5. 当前签出分支与 `prod`/`test` 参数不匹配 -> 拒绝更新。

## 部署到 VPS

`/root/ssc_fuyao_tg_app_prod` 目录下执行一次确认没有本地改动、且分支为 `main`；然后加入 crontab（每 5 分钟检查一次）：

```bash
crontab -e
# 追加一行：
*/5 * * * * /bin/bash /root/ssc_fuyao_tg_app_prod/auto_update.sh prod >> /root/ssc_fuyao_tg_app_prod/update.log 2>&1
```

此文件是仓库内版本记录，不是 Git tag 或 GitHub Release。
