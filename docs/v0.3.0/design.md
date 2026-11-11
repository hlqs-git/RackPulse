# RackPulse v0.3.0 技术设计

状态：设计待审阅；尚未开发或发布v0.3.0。生产环境不在本次执行范围。

## 目标与边界

保留K3s、PostgreSQL、Thanos指标、Webhook与32柜映射；不访问生产、不批量重采、不重算或重写历史日报。新增兼容读取层、事件时间语义、交互卡片、趋势与安全卡片投递。详细设备事件继续存储于原始summaries.events，不以展示归并结果替换。

已选择兼容升级：新增字段/表，保留旧键与旧表。另一方案是迁移并重算全部历史日报，违反当前边界，不采用。仅改展示不足以修复查询故障建模与卡片重试，因此analysis/jobs/repository/CLI也需修改；采集指标与映射不变。

## 统一报告模型与历史适配

新增report_model.py：build_report_view(day, report, previous, history, inventory)产生同一ReportView，render_preview(view)与render_cards(view)共用该视图。preview显示与卡片相同的数值、排序和告警，布局可以不同。send只发送render_cards的结果，不读存储的旧text。report --format text|cards|raw，raw原样导出数据库日报，cards导出实际Webhook交互卡片payload列表；默认text。

不依赖当前机柜映射改写历史：先使用历史configuration快照；缺快照时以现有32柜清单补展示占位，明确来源。缺失机柜必须有行，但数值为null/—，不算零值或正常。POD从GB200-1-*、GB200-2-*分别确定；未知命名进入额外未归组卡片，不能静默丢失。

旧报告读取时复制适配，不UPDATE历史JSON。旧duration_minutes表示累计时长，旧错误1440分钟datasource_error不能视为已验证区间。旧事件若有明确发生/恢复时间可按日窗口求交；仅有累计时长时当天时长标记未知，不以1440封顶伪装修复。保留legacy字段及推导依据。

## 事件时间与采集失败

所有序列化展示时间带Asia/Shanghai偏移+08:00。day window仍为[00:00,次日00:00)。

新增first_occurred_at、day_duration_minutes、total_duration_minutes、recovered_at、observation_status、time_basis；保留started_at与duration_minutes，旧duration_minutes继续保持累计语义，支持0.2读取日末状态。当天时长只累计本日有效观察到的异常分钟，最大1440；累计时长来自连续、同规则/设备的已知异常分钟，不能因时间戳跨度自动填补未知采集区间。恢复只在有效样本证明条件结束时记录；查询失败不能证明恢复。

日末状态仍使用type|device键，保存不足阈值的开放区间。午夜恢复允许当天0分钟、累计大于0；不能将前日累计再次加到本日时长。不同设备/规则/不可比配置不跨日接续。历史日重跑只写新修订并使次日待重算，不自动重算后续日期。

每个查询块记录query_started_at、query_finished_at、rack、metric、affected_window和安全错误类别；瞬时失败最终重试成功仅记执行诊断。最终失败产生查询事件：实际观察时间属于任务执行时间，受影响历史窗口独立展示；持续监控故障时长为null，不能赋值1440，也不能将请求耗时叫故障持续时间。品牌检查失败同样处理。analysis接收失败分钟/指标的有效性掩码，区分“成功查询但无数据”和“查询失败无法判断”，避免失败窗口产生伪设备缺失、伪恢复或伪连续性。

## 四类状态

- execution_status：queued/running/succeeded/failed；旧任务status保留，partial通过适配映射为执行完成且采集不完整。
- collection_status：complete/partial/no_data/unknown，依据查询结果和各指标覆盖率；查询成功不代表完整。
- monitoring_status：normal/degraded/unavailable/unknown；有查询失败/缺采则降级，但不代表设备故障。
- device_health：unknown/normal/abnormal，仅由直接设备健康证据支持。现有指标没有健康证据，默认unknown；不得以利用率、PSU数量直接判硬件异常。

卡片同时显示四类状态说明。异常机柜数量指重点监控异常或可评估指标异常的机柜去重数，另列设备异常已确认数与健康未知数，防止误读。

## 卡片与归并

使用飞书机器人interactive消息，主卡片含机柜总数、异常柜数、有效设备分钟加权GPU利用率、完整PSU可观测MWh、同口径昨日变化、最多10项重点事件和状态摘要。

POD1/POD2卡片各覆盖16柜，异常优先、其次自然编号。每柜显示利用率、来源明确的平均/峰值kW与可观测MWh、GPU/PSU完整率和状态。混合来源分字段/行，不合并成单一总功率。无有效来源为—，有效零值保留。每个POD卡片超限时按整机柜行继续拆分，不截断任何机柜。卡片不能保证固定手机屏数。

设备缺采归并仅展示层，按设备身份、相同观测区间/等级归并GPU→节点→机柜；不跨未知区间扩张故障范围。默认缺采连续5分钟进入重点；Critical不按时长过滤，超出主卡片容量时另附重点事件卡片，不能只保留计数。原始设备事件完整留存。

卡片使用飞书支持的静态交互卡片布局，不引入需要回调服务器的按钮。发布前对照官方自定义机器人/卡片协议核验JSON、长度、签名及错误码。

## 能耗、趋势与排名

内部保持W/kWh以兼容历史；展示kW/MWh。full_psu、partial_psu、gpu_proxy三组完全分开。无有效分钟时能耗为null；旧记录minutes=0且energy_kwh=0适配为null，不改变原JSON。

7/30日窗口包含报告日期，按自然日补日期占位，缺日保持null。利用率使用有效设备分钟加权；展示有效天数与覆盖率，不平均各柜均值。能耗按来源分别显示可观测量及覆盖率；设备集合、来源或覆盖不匹配的变化标记不可比，不把部分覆盖观测能耗当完整日增长趋势。

昨日比较仅同品牌、同PSU集合、完整全天覆盖的相同机柜集合；说明可比柜数。排名默认日均GPU利用率<10%、GPU与完整PSU覆盖均≥95%，同一来源下按平均功率降序，列利用率、功率、覆盖率；无法比较的机柜排除并说明原因。阈值可配置，不推断业务浪费或故障。

## 卡片投递

新增card_deliveries表。规范化JSON计算内容哈希，记录renderer_version、day、card_key、payload_hash、payload、status、attempts、timestamps与安全错误。父批次哈希固定卡片清单，发送/预览从同一清单产生。读历史数据只读，不因新版渲染自动发送；显式send才创建新批次。

卡片状态pending→sending→sent/failed/unknown；唯一键(day,channel,batch_hash,card_key)。数据库原子领取，sent不重发；确定失败可有限退避重试并单卡重试，unknown不得自动重试。发送中进程终止转unknown，避免将可能已送达的消息再发。每个尝试独立追加记录，不覆盖过去错误；显式force创建审计批次。429/明确可重试业务码按官方语义处理；不确定5xx/读超时保守unknown，不承诺端到端恰好一次。

不从v0.2通知记录删除/迁移内容；保留旧记录用于审计。卡片级失败不能让已发送主卡片重复发送。长度按最终JSON UTF-8字节计算，并留签名与封装余量；限制可配置并有保守默认值。

## 验证与交付

先执行tests.md中的红绿回归，再开发；GitHub Actions新增真实PostgreSQL隔离服务执行集成与0.2→0.3→0.2兼容测试。完整通过后才发布版本标签和ghcr.io/hlqs-git/rackpulse:0.3.0，验证镜像清单/digest并提供K3s命令。生产升级必须由用户决定执行。

当前仓库没有2026-11-09和2026-11-10真实日报JSON，日期相同的现有测试属于合成数据。可先完成同日期合成回归；真实历史回归必须使用用户导出的只读快照，不得宣称合成测试替代真实验收。

## 审阅修正：旧版事件排序兼容

查询失败的新字段day_duration_minutes/total_duration_minutes为null，因为故障持续时间未知；为避免v0.2按负duration排序崩溃，旧duration_minutes保留数值0，并设置time_basis=query_observation、legacy_duration_placeholder=true。此0只为旧渲染器结构兼容，不表示实测零分钟，新渲染器必须显示未知。旧版回滚界面可能显示0分钟，因此回滚说明需明确该限制。旧started_at使用实际查询观察时间并带+08:00，不使用历史窗口零点。测试必须用真实v0.2渲染函数读取包含该事件的v3日报，而不只验证容器启动。
