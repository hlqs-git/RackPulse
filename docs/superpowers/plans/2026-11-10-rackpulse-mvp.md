# RackPulse MVP Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付可部署、可追溯、支持历史重跑的 GB200 中文监控日报服务。

**Architecture:** 单个 Python 服务提供 FastAPI、单实例调度器和任务执行器，PostgreSQL保存配置快照、任务、检查点、汇总、日报和通知记录。采集以机柜/指标/小时分块，分析使用统一分钟网格，飞书通过独立适配器发送。

**Tech Stack:** Python 3.12、FastAPI、httpx、APScheduler 3.x、SQLAlchemy 2.x、psycopg 3、Alembic、PyYAML、pytest、Docker Compose。

**Spec:** `docs/superpowers/specs/2026-11-10-rackpulse-mvp-design.md`

## Global Constraints

- 固定 Asia/Shanghai；上一日窗口为 [00:00, 次日00:00)，默认60秒，共1440桶。
- 32柜，每柜72 GPU、48 PSU，且只有一种PSU品牌。
- LiteOn/Delta分别采集；未知品牌和映射不可编造。
- Thanos只读、有超时、有限并发和重试；旧样本默认超过120秒无效。
- 缺失不填零；完整PSU、部分PSU、GPU代理的功率及能耗分别汇总。
- 非root应用容器；Webhook和鉴权信息不得进入仓库或日志。
- 外部发送超时标记unknown，不承诺端到端恰好一次。
- 本地当前Python为3.13.15；生产及最终兼容性验证使用Python3.12容器。当前目录无Git元数据，不初始化或提交仓库。

## Review Focus

- host正则重叠或设备重复返回：拒绝歧义，不能重复计功率（任务1、2）。
- HTTP 200携带Thanos warnings/飞书失败码：不得当成功（任务2、6）。
- 午夜边界和跨日异常重跑：不重复采样、不伪造恢复（任务3、4、5）。
- 并发任务、进程中断和Webhook结果不确定：不重复提交/盲目通知（任务4、5、6）。
- 配置缺项、数据库不可用和日志中含密钥：明确阻止正式运行并脱敏（任务1、7、8）。

---

## Task 1: 配置、时间窗口和领域类型

**Files:** `pyproject.toml`, `src/rackpulse/config.py`, `src/rackpulse/domain.py`, `src/rackpulse/timewindow.py`, `config/racks.example.yaml`, `.env.example`, `.gitignore`, `tests/test_config.py`, `tests/test_timewindow.py`。

**Interfaces:** `load_config(path: str) -> AppConfig`; `day_window(day: date) -> DayWindow`；配置包含rack_id、gpu_host_pattern、psu_vendor和可配置规则。领域类型包括DeviceSample、RackSummary、Event及PowerSource。

- [ ] 写失败测试：`test_day_window`断言1440桶且UTC起点为前日16:00；`test_inventory`断言32个唯一机柜；`test_unknown_vendor_blocks_run`断言未配置品牌无法正式运行；`test_overlapping_hosts`断言重复映射被拒绝。
- [ ] 运行 `python -m pytest tests/test_config.py tests/test_timewindow.py -v`，确认功能缺失导致失败。
- [ ] 实现上述接口；示例中仅填写已知GB200-2-7 GPU映射，其余空值显式待配置；提供运行前发现/验证入口。校验标识、正则、阈值、超时和并发范围。
- [ ] 重跑测试，预期全部通过。

## Task 2: Thanos查询与分块采集

**Files:** `src/rackpulse/thanos.py`, `src/rackpulse/collector.py`, `tests/test_thanos.py`, `tests/test_collector.py`, `tests/fixtures/thanos/*.json`。

**Interfaces:** `ThanosClient.query_range(query: str, start: datetime, end: datetime, step: int) -> list[MetricSeries]`；`Collector.collect_block(rack: RackConfig, metric: str, window: DayWindow) -> list[DeviceSample]`。httpx transport可注入。

- [ ] 写失败测试：超时/503有限重试、401不重试、200带warnings失败、小时块边界无重复、原始样本超过120秒无效；副本值相同去重、冲突值无效；Delta/LiteOn编号起点不影响身份；另一品牌存在时产生冲突。
- [ ] 运行 `python -m pytest tests/test_thanos.py tests/test_collector.py -v`，确认预期失败。
- [ ] 实现只读GET查询、dedup与原始分辨率参数、有限并发退避、取消传播、响应结构验证。为每个指标查询对应原始timestamp以检查新鲜度；不使用滚动均值代替分钟样本。增加另一厂商品牌存在性检查。只记录安全错误类别，不记录含密钥URL。
- [ ] 重跑测试，预期全部通过。

## Task 3: 分钟统计与异常引擎

**Files:** `src/rackpulse/analysis.py`, `src/rackpulse/rules.py`, `tests/test_analysis.py`, `tests/test_rules.py`。

**Interfaces:** `analyze_rack(rack: RackConfig, samples: list[DeviceSample], window: DayWindow, history: list[RackSummary]) -> RackSummary`；`detect_events(summary: RackSummary, previous_state: dict) -> tuple[list[Event], dict]`。

- [ ] 写失败测试：48路PSU的60kW持续60分钟得到60kWh；47路只计部分PSU；PSU全缺改GPU代理且不混合能耗；NaN/Inf/负功率排除，零保留；一分钟出现72卡不代表全天完整；高低负载比例分母为有效设备分钟。
- [ ] 写失败测试：59/60分钟高负载边界、9/10分钟全缺边界、缺失打断负载区间、跨午夜未恢复事件；3个合格历史日前不判断功率异常，30%阈值与设备集合变化不误报。
- [ ] 运行 `python -m pytest tests/test_analysis.py tests/test_rules.py -v`，确认预期失败。
- [ ] 实现分钟网格、分来源功率积分、设备/采样覆盖率、Info负载和Warning/Critical规则，保存未恢复状态。日前基线使用前7日中至少3个覆盖率≥95%的完整PSU日均值中位数。
- [ ] 重跑测试，预期全部通过。

## Task 4: PostgreSQL持久化和迁移

**Files:** `src/rackpulse/db.py`, `src/rackpulse/models.py`, `src/rackpulse/repository.py`, `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_initial.py`, `tests/integration/test_repository.py`。

**Interfaces:** `Repository.acquire_day(day: date)`, `save_checkpoint(task_id: str, key: str, payload: dict)`, `publish_report(day: date, payload: dict) -> Report`, `get_report(day: date) -> Report | None`；事务管理明确封装在Repository中。

- [ ] 写失败测试：两连接竞争同日任务仅一个成功；重复发布只存在一个当前日报；失败事务保留旧版本；配置指纹改变不复用检查点；清理检查点后日末规则状态仍存在。
- [ ] 运行 `python -m pytest tests/integration/test_repository.py -v`，连接独立测试PostgreSQL并确认预期失败。
- [ ] 实现初始迁移、事务/唯一约束、会话级日期锁和陈旧任务恢复。所有锁在结束或连接关闭时释放，通知记录不级联删除。持久化次日待重算标记。
- [ ] 执行迁移并重跑集成测试，预期全部通过；测试数据库不得使用生产URL。

## Task 5: 日报与任务编排

**Files:** `src/rackpulse/report.py`, `src/rackpulse/jobs.py`, `tests/test_report.py`, `tests/integration/test_jobs.py`。

**Interfaces:** `render_report(day: date, summaries: list[RackSummary], previous: dict | None) -> str`；`DailyJob.run(day: date) -> str`返回任务ID。使用任务1–4接口。

- [ ] 写失败测试：缺失/不可比标记、三类来源独立显示、Info不计故障、无数据机柜不计正常；中途失败恢复成功块；采集失败生成明确不完整报告；历史重跑关联次日并标记待重算；失败不覆盖已成功日报。
- [ ] 运行 `python -m pytest tests/test_report.py tests/integration/test_jobs.py -v`，确认预期失败。
- [ ] 实现任务生命周期、检查点恢复、事件和规则状态提交、原子日报修订、中文摘要及昨日同口径对比。规则建议标为可能原因，未恢复不显示恢复时间。
- [ ] 重跑测试，预期全部通过。

## Task 6: 飞书适配器和通知记录

**Files:** `src/rackpulse/notifications.py`, `tests/test_notifications.py`, `tests/integration/test_delivery.py`。

**Interfaces:** `FeishuAdapter.send(text: str) -> DeliveryResult`；`DeliveryService.send_report(day: date, force: bool = False) -> DeliveryResult`。结果包含sent/failed/unknown/skipped与安全错误码。

- [ ] 写失败测试：HTTP200业务错误不成功、429退避、读超时unknown且不重试、同内容并发发送只一次、unknown保留、修订不自动发送；签名、长文分段及测试消息标识；Webhook不出现在日志中。
- [ ] 运行 `python -m pytest tests/test_notifications.py tests/integration/test_delivery.py -v`，确认预期失败。
- [ ] 实现内容哈希唯一约束、发送前持久化、进程中断后的sending转unknown；分段独立记录状态，不重发已确认段。强制发送显式审计，默认无Webhook时不尝试网络请求。
- [ ] 重跑测试，预期全部通过。

## Task 7: API、调度与CLI

**Files:** `src/rackpulse/api.py`, `src/rackpulse/scheduler.py`, `src/rackpulse/cli.py`, `src/rackpulse/logging.py`, `tests/test_api.py`, `tests/test_scheduler.py`。

**Interfaces:** `create_app() -> FastAPI`；CLI提供validate-config、discover、run --date、report --date、send --date、test-webhook；调度器调用DailyJob。

- [ ] 写失败测试：缺少API token的变更请求拒绝；生成任务返回202和任务ID；无报告404；数据库不可用readiness失败；北京时间08:00使用正确前一日；关闭服务停止调度；密钥、HTTP客户端日志及异常日志脱敏。
- [ ] 运行 `python -m pytest tests/test_api.py tests/test_scheduler.py -v`，确认预期失败。
- [ ] 实现健康/就绪、任务生成与状态、日报查询、通知接口和CLI；单进程执行器处理持久任务，重启恢复未完成任务；scheduler允许显式禁用，部署只启动一实例。
- [ ] 重跑测试，预期全部通过。

## Task 8: 部署、文档与整体验证

**Files:** `Dockerfile`, `compose.yaml`, `.dockerignore`, `README.md`, `tests/integration/test_end_to_end.py`。

**Interfaces:** `docker compose up --build`提供应用和数据库；默认API仅绑定127.0.0.1；命名卷保存数据库。迁移成功后启动服务。

- [ ] 写失败端到端测试：固定完整日Thanos响应→32柜报告→飞书成功；重跑同日不重复通知；中途采集失败恢复；配置缺项阻止正式任务。
- [ ] 运行 `python -m pytest tests/integration/test_end_to_end.py -v`，确认预期失败。
- [ ] 编写Python3.12非root镜像、数据库/应用健康检查、环境示例与中文运维说明，说明补齐映射、指标验证、手动重跑、unknown核实、备份恢复和端点鉴权。
- [ ] 运行完整 `python -m pytest`、`python -m compileall src`、`docker compose config`；有Docker时构建并在Python3.12容器运行完整测试及PostgreSQL集成测试。缺工具或现场凭据时准确记录未验证项目。
- [ ] 对照设计逐项检查，进行整体代码审阅，修复问题后重跑受影响测试。真实Thanos与飞书验收单列，未提供凭据不得标为通过。

## 自检与执行方式

设计各部分对应任务1–8；跨日状态、品牌冲突、基线不足、长消息部分发送、发送中崩溃均有测试归属。模块接口以上述签名为准。此计划尚未执行。

推荐当前会话原生执行：任务共享配置、领域类型和事务接口，顺序实施便于保持一致；完成后使用独立审阅代理进行整体检查。也可选择每任务独立实施代理与审阅代理，成本更高但中间审阅更密集。
