# SSC Telegram 自动化

本仓库使用严格隔离的测试与生产环境：

- `test` 分支仅用于测试 Telegram 群。
- `main` 分支仅用于生产；测试群完整验收前禁止合并。
- 测试和生产使用不同的代码目录、`.env`、Telegram session、状态文件、日志及 systemd 服务。

详细配置、VPS 目录和发布流程见 [ENVIRONMENTS.md](ENVIRONMENTS.md)。

## 本地检查

```bash
cd ssc_offer_bot
python -m unittest discover -p 'test_*.py'
```

## 启动

```bash
# 测试
BOT_ENV=test python main.py

# 生产（只允许在 main 分支及生产目录运行）
BOT_ENV=prod python main.py
```

若未设置 `BOT_ENV`，程序默认选择 `test`，避免误发生产群。

真实 Telegram API Hash、Google 服务账号 JSON 和 session 文件不得提交 Git。
