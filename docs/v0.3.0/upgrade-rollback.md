# v0.3.0 升级与回滚操作设计

状态：v0.3.0已发布；隔离PostgreSQL迁移与真实0.2镜像兼容测试通过。以下操作由用户核对备份后自行执行，开发会话未访问生产。

## 升级前

记录当前Deployment完整配置、镜像digest、Secret/ConfigMap引用及Alembic版本；将含凭据备份放在受控位置。pg_dump备份后在独立数据库验证可恢复。只读导出2026-11-09/10两日日报JSON供脱敏回归，不触发run重采。

保留原32柜配置、环境变量、PVC与PostgreSQL版本。始终单副本/Recreate。等待当前任务/发送结束，避免发送中断；有unknown投递先核实。

## 升级（发布且测试完成后）

迁移和应用容器必须统一版本：

```sh
kubectl -n rackpulse set image deployment/rackpulse \
  app=ghcr.io/hlqs-git/rackpulse:0.3.0 \
  migrate=ghcr.io/hlqs-git/rackpulse:0.3.0
kubectl -n rackpulse rollout status deployment/rackpulse --timeout=300s
kubectl -n rackpulse logs deployment/rackpulse -c migrate
```

同步修改本地Kustomize image配置，避免后续apply覆盖。检查ready、迁移版本、两日历史text/cards/raw预览及32柜覆盖，再由运维显式发送测试；未经核对不force历史日报。不得批量run历史数据。

## 回滚（不能只rollout undo）

先暂停应用，记录原副本数和环境；停止所有投递进程。使用0.3镜像建立一次性迁移Job（沿用现有Secret和安全上下文），执行alembic downgrade 0001。0002降级必须是保留表与记录的逻辑降级。Job结束并确认Alembic=0001后，才将app和migrate镜像统一切回0.2.0。

旧镜像只认识0001，因此跳过该步骤会导致initContainer迁移失败。回滚不删除PVC、不恢复覆盖数据库、不删除新表。0.2不会识别卡片状态，先以SCHEDULER_ENABLED=false启动，核对已发日报后再决定恢复自动调度。0.2原有时长/显示缺陷也会恢复。

可执行Job见deploy/k8s/v030-rollback-job.example.yaml。CI演练结果和镜像digest见版本说明。

## 可执行回滚清单（发布后，由用户自行执行）

先记录当前副本数并等待在途任务/发送结束；已备份且决定回滚后：

```sh
kubectl -n rackpulse scale deployment/rackpulse --replicas=0
# 确认应用Pod已经退出，再执行数据库逻辑降级
kubectl apply -f deploy/k8s/v030-rollback-job.example.yaml
kubectl -n rackpulse wait --for=condition=complete job/rackpulse-v030-logical-downgrade --timeout=300s
kubectl -n rackpulse logs job/rackpulse-v030-logical-downgrade
kubectl -n rackpulse set env deployment/rackpulse SCHEDULER_ENABLED=false
kubectl -n rackpulse set image deployment/rackpulse app=ghcr.io/hlqs-git/rackpulse:0.2.0 migrate=ghcr.io/hlqs-git/rackpulse:0.2.0
kubectl -n rackpulse scale deployment/rackpulse --replicas=1
kubectl -n rackpulse rollout status deployment/rackpulse --timeout=300s
```

Job失败必须停止，不得继续切回旧镜像。确认历史报告可读且无重复通知风险后，用户自行决定恢复SCHEDULER_ENABLED=true。同步更新本地Kustomize配置。再次回滚时已有Job名称会冲突，先核对其状态与日志，决定是否删除已完成Job对象；不涉及删除任何数据库数据。

## 预览与只读导出

```sh
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse report --date 2026-11-09 --format text
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse report --date 2026-11-09 --format cards > 2026-11-09.cards.json
kubectl -n rackpulse exec deployment/rackpulse -c app -- rackpulse report --date 2026-11-09 --format raw > 2026-11-09.raw.json
```

11-10使用同样命令替换日期。导出不执行run、不会访问Thanos、不发送消息；共享前脱敏处理。
