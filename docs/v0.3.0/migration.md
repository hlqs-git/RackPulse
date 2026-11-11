# v0.3.0 数据库兼容迁移方案

1. 0001与所有旧表保持原状；新增0002，仅CREATE独立card_deliveries和card_delivery_attempts表及索引，不ALTER/DROP旧列，不UPDATE历史JSON。
2. card_deliveries：id、day、channel、batch_hash、card_key、payload_hash、renderer_version、payload(JSON)、status、attempts、created_at、updated_at；唯一约束(day,channel,batch_hash,card_key)。attempts记录每次发送尝试、开始/结束、结果、安全错误类别。数据库内原子状态变更保护并发领取。
3. 新日报JSON添加schema_version=3和新增时间/状态字段；started_at、duration_minutes、summaries、events、power、text、rule_state等旧键保留。旧代码忽略新增字段并可读取新增日报；新代码兼容旧JSON。
4. v0.2镜像启动会执行alembic upgrade head。Alembic数据库已处0002时，旧镜像只认识0001，将无法启动：回滚必须先使用0.3迁移工具执行0002→0001的“逻辑降级”，降级函数不删除新表或卡片记录，再启动0.2。迁移升级create tables使用checkfirst，支持日后重新升级。此兼容限制必须在隔离PostgreSQL与真实0.2镜像中验证。
5. 逻辑降级仅更改Alembic版本标记，保留新增表/索引/数据，不执行DROP。禁止使用旧版本alembic处理未知0002版本。不得回滚/删除旧报告或规则状态。
6. 回滚至0.2后发送器恢复为纯文本，无法识别新版卡片记录；为避免重复，回滚时暂关自动调度，人工核对当天已发内容后再启用。旧版跨日时长问题会重新存在，不能声称回滚保留修复。
7. 迁移前使用pg_dump备份，验证独立实例恢复；DDL事务超时、锁等待超时需有限配置。执行人是用户/运维，不由当前开发会话操作生产。

审阅补充：查询失败事件的新持续字段为null，但旧duration_minutes需使用数字0作明确标记的结构兼容占位，避免0.2排序报错；旧版展示0不能作为真实时长。兼容测试须实际调用0.2报告渲染器读取新日报，不止检查启动。
