# RackPulse

GB200 GPU 数据中心中文监控日报服务。按 Asia/Shanghai 上一自然日采集 Thanos 分钟数据，区分完整PSU、部分PSU和GPU代理功率，保存日报修订与任务记录，支持飞书通知。

当前范围为**统计状态并通知**：日报只展示实测统计、数据完整性、固定阈值状态和昨日对比，不调用AI或大模型，不输出故障原因推测或排查建议。高低负载与采集缺失由确定性规则标记。

## 配置与部署

支持两种部署方式：下文为Docker Compose；Kubernetes请见 [K8s部署说明](deploy/k8s/README.md)，提供Kustomize清单、Secret配置、持久化存储和健康探针。

1. 复制 `.env.example` 为 `.env`，填写数据库密码、URL、API token、Thanos 地址/鉴权和飞书机器人地址及可选签名密钥。数据库URL中的密码特殊字符须URL编码。
2. 复制 `config/racks.example.yaml` 为 `config/racks.yaml`。此文件采用兼容YAML的JSON格式，也可改用普通YAML。补齐32柜的 `gpu_host_pattern` 和 `psu_vendor`（`liteon` / `delta`）。仅GB200-2-7的GPU映射已知，其余故意留空；缺项会阻止正式调度。
3. 执行 `docker compose up --build -d`。应用启动前自动执行Alembic迁移，仅运行一个应用实例。API仅绑定本机8000，生产远程接入请经受控反向代理。
4. 检查 `GET /health`、`GET /ready` 及 `docker compose logs app`。默认北京时间08:00生成前一日数据并发送首次日报。

每柜预期72 GPU、48 PSU，单柜仅一种PSU品牌。GPU身份为host+gpu_id；PSU身份为rack+host+psu_id。PSU编号从0或1开始都可。采集另一品牌仅用于冲突检查，冲突时不统计PSU功率。

## 常用命令

容器命令均继承Compose的环境与配置：

```sh
docker compose exec app rackpulse validate-config
docker compose exec app rackpulse discover --date 2026-11-09
docker compose exec app rackpulse run --date 2026-11-09
docker compose exec app rackpulse report --date 2026-11-09
docker compose exec app rackpulse test-webhook
docker compose exec app rackpulse send --date 2026-11-09
```

手动run只生成，不自动推送。重新发送使用send；相同内容已领取发送记录会跳过。核实发送结果后需要强制再发才加 `--force`，此操作可能产生重复消息并有独立记录。discover为只读辅助，不自动写入机柜配置。

## API

除健康端点外均需 `Authorization: Bearer <API_TOKEN>`。OpenAPI位于 `/docs`。

| 方法与路径 | 用途 |
|---|---|
| POST /jobs，JSON `{"day":"2026-11-09"}` | 返回202和task_id，异步生成 |
| GET /jobs/{task_id} | queued/running/succeeded/partial/failed |
| GET /reports/{day} | 中文正文、结构化汇总、配置与规则快照 |
| POST /notifications/test | 明确标识的测试消息 |
| POST /notifications/send，JSON `{"day":"2026-11-09","force":false}` | 推送已有日报 |

## 统计口径与异常

- 窗口为北京时间[00:00,次日00:00)，1440个分钟桶。Thanos查询使用原始分辨率、去重、禁用部分响应，并检查样本年龄（默认120秒）。
- 采样完整率=有效设备分钟/(预期设备数×1440)。日内见过72卡不代表全天完整。无效值和冲突副本排除，零值有效，缺失不补零。
- 每分钟48路有效PSU为完整实测；1–47路仅代表部分PSU和；PSU全缺才用GPU功率和参考。分别积分kWh及覆盖分钟，不能将代理值或部分值当作机柜总功率。
- 低负载<10%、高负载≥80%连续60分钟为Info；设备数量不足为Warning；全无有效数据连续10分钟为Critical。功率偏离30%仅评估完整PSU且同设备集合，基线取前7日至少3个覆盖≥95%的有效日均值中位数。基线不足不做推断。
- 跨日事件持久化日末状态；历史重跑使次日 `needs_recompute=true` 时请按日期顺序重跑后续日报。已经发送的历史通知不会被静默替换。

## 失败、幂等与恢复

小时级检查点带配置指纹；成功日报提交后清理临时分钟数据。失败保留检查点供同配置重跑。PostgreSQL日期锁避免并发统计，数据库保存日报修订，读取只返回最新版本。不完整重跑不会覆盖完整日报。

飞书发送前记录领取状态，避免同内容并发重复；记录每个分段结果。读超时、远端5xx、进程发送中断均可能已送达，保存unknown并停止自动重发，需人工核实。不能承诺接收端恰好一次。修订不自动发送。

原始分钟数据长期仍在Thanos。数据库保存任务/日报/异常（日报结构化JSON内）、日末状态与通知记录。生产请定期使用 `pg_dump` 备份数据库，并在独立环境验证恢复；不要通过删除卷解决任务错误。

## 开发验证

```sh
python -m venv .venv
# 激活虚拟环境后
python -m pip install -e '.[test]'
python -m pytest
python -m compileall src
```

PostgreSQL测试仅在设置专用 `TEST_DATABASE_URL` 时执行，请勿指向生产数据库。测试使用固定HTTP响应，不会发送真实飞书通知。现场验收需另外验证真实Thanos标签、72/48设备归属、历史数据保留范围以及飞书投递；本地夹具通过不能替代现场验收。

Python3.12容器是部署目标。本次开发主机为Python3.13且未安装Docker，因此构建、容器健康检查、PostgreSQL真实事务和现场连接需在具备环境后执行。7/30日趋势、多渠道、AI与Web界面属于后续阶段。
