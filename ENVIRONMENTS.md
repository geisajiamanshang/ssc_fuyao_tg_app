# Test / Prod 环境规则

## 分支与实例

| 环境 | Git 分支 | VPS 目录 | systemd 服务 | 审批码 |
|---|---|---|---|---|
| 测试 | `test` | `/root/ssc_fuyao_tg_app_test` | `ssc-offer-bot-test` | `测试1` / `测试2` / `测试3` / `测试4` / `测试4.1` / `测试11` / `测试21` / `测试6` / `测试6.1` / `测试6.2` / `测试7` |
| 生产 | `main` | `/root/ssc_fuyao_tg_app_prod` | `ssc-offer-bot-prod` | `1` / `2` / `3` / `4` / `4.1` / `11` / `21` / `6` / `6.1` / `6.2` / `7` |

两个实例必须使用不同的 `.env`、Telegram session、状态文件和日志。不要在同一个工作目录切换分支运行两个实例。

联合管理工作群里的Offer审批链（一级/二级/终审）除了回复文字，领导也可以直接在@他的审批提示消息上点 👌 表情，效果等同于回复审批通过；同一条消息上其他人点的无关表情会被忽略，只认配置的一级/二级/终审领导账号。

审批码 `测试11`/`11` 用于"入职确认已发布到联合管理群后，再转发到预入职登记群"这一步（`GROUP_PRE_ONBOARDING`）。该目标群ID需要用 `list_chats.py` 取得后分别填入 `.env.test` / `.env.prod` 的 `GROUP_PRE_ONBOARDING`；未配置前该功能自动跳过，不影响其余流程。

审批码 `测试21`/`21` 用于"转正提醒-恒睿-转正倒数4天"触发后，员工本人的转正申请单独放行到联合管理工作群，与预转正提醒的审批码（`测试2`/`2`）并存、互不干扰。SSC可以在收藏夹里先改好转正申请的内容，再发送该审批码，放行的是修改后的最新版本。

审批码 `测试6`/`6`、`测试6.1`/`6.1`、`测试6.2`/`6.2` 用于新人培训群"新人培训考试通过"（@ffuuyao）触发后：按消息里@的新人TG用户名到Drive云端 入职助手/输出 文件夹查找该新人的入职信息，按【段落名】分区分条发到收藏夹。"新人入职通知"经`6`放行到联合管理群，"入职信息同步"经`6.1`放行到人事数据同步-SSC3组（`GROUP_REGULARIZATION_SYNC`），"欢迎"经`6.2`按部门匹配路由表放行到对应全员群；其余分区仅作参考资料，不设审批码。三个审批码相互独立，SSC可分别在收藏夹改完内容再放行，每条转发成功后自动删除收藏夹里对应的草稿。触发群 `GROUP_TRAINING` 的群ID待补充，未配置前该功能自动跳过，不影响其余流程。

审批码 `测试7`/`7` 用于SSC3组内部工作沟通群（`GROUP_SSC3_INTERNAL_CHAT`）/ 转正提醒来源群（`GROUP_REGULARIZATION_TRIGGER`，两群共用同一个监控来源）里出现"全员群"关键词后：自动取该消息之前最近一条带图片+文字的通知消息，转发到收藏夹。**每发送一次`7`只转发到剩余全员群里的下一个**，需要SSC连续发送5次才能覆盖全部5个全员群（`ANNIVERSARY_GROUP_RULES`里配置的部门全员群）；每次转发的都是收藏夹草稿当前的最新内容，SSC可以在两次发送之间修改草稿。第5个群发送成功后才会自动删除收藏夹里的这条草稿。

## 修改和发布流程

1. 所有功能修改只提交到 `test` 分支。
2. GitHub 自动运行全部单元测试。
3. 在测试 Telegram 群完整验证 Offer、转正、周年及 SSC 收藏夹审批。
4. 确认测试成功后，创建 `test → main` Pull Request。
5. PR 测试通过并人工确认后才能合并；生产实例只拉取 `main`。

未经第 3 步确认，不得合并到 `main`。

## VPS 首次部署

测试与生产分别克隆，不共享目录：

```bash
git clone -b test https://github.com/geisajiamanshang/ssc_fuyao_tg_app.git /root/ssc_fuyao_tg_app_test
git clone -b main https://github.com/geisajiamanshang/ssc_fuyao_tg_app.git /root/ssc_fuyao_tg_app_prod
```

分别复制示例并填写真实密钥：

```bash
cp /root/ssc_fuyao_tg_app_test/ssc_offer_bot/.env.test.example /root/ssc_fuyao_tg_app_test/ssc_offer_bot/.env.test
cp /root/ssc_fuyao_tg_app_prod/ssc_offer_bot/.env.prod.example /root/ssc_fuyao_tg_app_prod/ssc_offer_bot/.env.prod
```

真实 `TG_API_HASH`、Google 服务账号 JSON 和 `.session` 不能提交 Git。完成首次 Telegram 登录后运行：

```bash
cd /root/ssc_fuyao_tg_app_test && bash deploy.sh test
cd /root/ssc_fuyao_tg_app_prod && bash deploy.sh prod
```

## 生产发布条件

- GitHub 单元测试全部通过。
- 测试群完整业务流程通过。
- `test` 环境日志中没有向生产群发送的记录。
- PR 只允许从 `test` 合并到 `main`。
