# 应用目录

环境入口由 `config.py` 统一加载：

- `config_common.py`：不决定消息去向的共用规则。
- `config_test.py`：测试群、测试审批人、测试状态文件。
- `config_prod.py`：生产群、生产审批人、生产状态文件。
- `.env.test` / `.env.prod`：只保存在服务器上的密钥与账号校验值。

测试环境不会继承生产配置，并在启动时检查发送目标是否与生产群重叠。完整部署与发布规则见仓库根目录的 `ENVIRONMENTS.md`。
