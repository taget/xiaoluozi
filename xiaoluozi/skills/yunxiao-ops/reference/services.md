# 服务速查表

> 每个服务的高频命令和常用参数快速参考。
>
> ⚠️ **重要**：以下命令已通过 `--help` 验证。但 action 名称不遵循统一的 CRUD 约定——
> 有些用 `list`，有些与 resource 同名（如 `region region`），还有些用自定义名称（如 `records`, `evaluate`）。
> **当你不确定时，务必先运行 `yunxiao <service> <resource> --help` 确认实际 action 名。**

---

## 1. beacon（灯塔 — 库存安全水位管控）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao beacon stock-metrics list` | 查询库存观察指标数据 | `--region`, `--instance-family`, `--instance-type` |
| `yunxiao beacon stock-metrics inventory` | 查询库存看板数据 | `--region` |
| `yunxiao beacon stock-metrics metrics` | 查询库存可观察指标 | `--region` |
| `yunxiao beacon stock-metrics history` | 查询库存指标历史数据 | `--region` |
| `yunxiao beacon stock-metrics alert` | 查询库存报警记录 | `--region` |
| `yunxiao beacon stock-alert-metrics metrics` | 查询库存报警指标 | `--region` |
| `yunxiao beacon inventory inventory` | 查询库存 | `--region`, `--zone` |
| `yunxiao beacon ceres zone-instance-type-infos` | 查询 ceres 机型库存 | `--region` |
| `yunxiao beacon cvm-type-config list` | 查询 CVM 机型配置 | `--region`, `--instance-family`, `--instance-type` |
| `yunxiao beacon stock-plan evaluate` | 评估库存生成调度计划 | `--region` |

**子组列表**：automation, ceres, crp, cvm-type-config, cvm-type-config-new, erp, export-async, flow, galaxy, host-empty, instance-launch-plan, inventory, new-cmdb, predict-consumption, resource-match-plan, stock-alert-metrics, stock-metrics, stock-plan, stock-pool-level, stock-predict-metrics, tcres, ticket

---

## 2. data360（数据360 — 元数据查询与分析）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao data360 region region` | 查询地域列表 | — |
| `yunxiao data360 zone zone` | 查询可用区列表 | `--region` |
| `yunxiao data360 zone detail` | 查询可用区详情 | `--region` |
| `yunxiao data360 instance instance` | 查询实例列表 | `--region`, `--instance-id` |
| `yunxiao data360 instance detail` | 查询实例详情 | `--instance-id` |
| `yunxiao data360 instance-type instance-type` | 查询实例类型 | `--instance-type`, `--instance-family` |
| `yunxiao data360 instance-type get` | 获取单个实例类型 | `--instance-type` |
| `yunxiao data360 instance-family instance-family` | 查询实例族 | `--instance-family` |
| `yunxiao data360 host host-type` | 查询地域的机型列表 | `--region` |
| `yunxiao data360 vm list` | 查询虚拟机列表 | `--region`, `--uuid` |

**子组列表**：auth, ccdb, cmdb, customer, cvm-type-whitelist, device-class, disaster-recover-group, ecm, export-async, host, host-quota, host-type, image, instance, instance-family, instance-type, instance-type-family, logic-pool, metadata, octopus-worker, qcloud-region, query-user-white-list-instance-family, query-user-white-list-keys, quota, region, reserved-package, staff, stock, tencent-region, tencent-zone, user360, vm, vs, zone, zone-instance-type

---

## 3. rubik（魔方 — 资源规划与预留管理）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao rubik order my-created` | 查询我创建的预约单 | `--region`, `--status` |
| `yunxiao rubik order my-approval` | 查询我审批的预约单 | `--region` |
| `yunxiao rubik order order` | 查看预约单详情 | `--order-id` |
| `yunxiao rubik order create` | 创建预约单 ⚠️ | `--json-body` |
| `yunxiao rubik order summary` | 预约单统计 | `--region` |
| `yunxiao rubik grid grid` | 查询预扣块 | `--region`, `--zone`, `--grid-id`(JSON数组), `--host-ip`, `--limit` |
| `yunxiao rubik grid reserve` | 创建预扣块 ⚠️ | `--json-body` |
| `yunxiao rubik grid group-by-zone-instance-type` | 预扣块按机型聚合 | `--region` |
| `yunxiao rubik instance list` | 查询实例列表 | `--region` |
| `yunxiao rubik reservation-form list` | 查询预留表单 | `--region`, `--app-ids`(JSON数组), `--instance-family`(JSON数组), `--status`(JSON数组), `--page-size`, `--page-number` |
| `yunxiao rubik reservation-form grid` | 查预扣单关联的 grid 块 | `--reservation-form-id`(JSON数组), `--page-size`, `--page-number` |
| `yunxiao rubik reservation-form result` | 查预扣单结果汇总 | `--reservation-form-id`(JSON数组) |
| `yunxiao rubik reservation-form summary` | 预扣单统计 | `--status`, `--region` |
| `yunxiao rubik reservation-form purchased-rate-group-by-app-id` | 客户履约率 | `--status`(JSON数组) |

**子组列表**：approver-config, export-async, grid, grid-task, instance, metadata, migrate-grid-job, order, over-stock, reservation-form, scheduler

---

## 4. compass（指南针 — 友商对比与购买推荐）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao compass instance list` | 友商实例对比 | `--region` |
| `yunxiao compass operation-metrics list` | 运营指标 | `--region` |
| `yunxiao compass instance-family list` | 实例族列表 | — |
| `yunxiao compass instance-type-price list` | 实例类型定价 | `--instance-type` |
| `yunxiao compass buy-flow-promise-info list` | 购买流程承诺 | — |
| `yunxiao compass device-arrived-info list` | 设备到货信息 | — |
| `yunxiao compass aliyun list` | 阿里云对比 | — |
| `yunxiao compass poc list` | POC 查询 | — |

**子组列表**：aliyun, buy-flow-promise-info, device-arrived-info, instance, instance-family, instance-type-price, metadata, operation-metrics, poc

---

## 5. honeycomb（蜂巢 — 宿主机生命周期管理）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao honeycomb host host` | 查询宿主机 | `--region`, `--ip`(JSON数组,批量查), `--asset`(固资号), `--app-mask`(JSON数组如`[8]`), `--limit`, `--offset`, `--has-total-count` |
| `yunxiao honeycomb host sum` | 统计宿主机(按可用区和机型) | `--region` |
| `yunxiao honeycomb host instance` | 查询宿主机关联实例 | `--region`, `--host-ip` |
| `yunxiao honeycomb host grid` | 查询宿主机关联块 | `--region` |
| `yunxiao honeycomb component list` | 部件列表 | `--region`, `--host-ip` |
| `yunxiao honeycomb action list` | 操作列表 | `--region` |
| `yunxiao honeycomb action create` | 执行操作 ⚠️ | `--json-body` |
| `yunxiao honeycomb action-audit list` | 操作审计 | `--region`, `--host-ip` |
| `yunxiao honeycomb fault-reserve list` | 故障保留 | `--region` |
| `yunxiao honeycomb device-failure-rate list` | 设备故障率 | `--region` |

**子组列表**：action, action-audit, auth, cdh, component, component-type, device-failure-rate, event, export-async, fault-reserve, host, host-ignore-tag, host-tag, host-task, metadata, octopus-worker, user-pool-strategy

---

## 6. insight（洞察 — 大数据聚合分析）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao insight purchase-failed-alarm records` | 购买失败记录 | — |
| `yunxiao insight purchase-failed-alarm analysis-by-region` | 按地域统计购买失败 | — |
| `yunxiao insight purchase-failed-alarm analysis-by-error-code` | 按错误码统计购买失败 | — |
| `yunxiao insight sold-out-alarm config-list` | 售罄告警配置列表 | — |
| `yunxiao insight event-hub event-list` | 查询订阅事件 | — |
| `yunxiao insight vstation-event list` | VStation 事件 | — |
| `yunxiao insight vstation-error-code list` | VStation 错误码 | — |
| `yunxiao insight user-activity list` | 用户活动 | — |
| `yunxiao insight host-summary list` | 宿主机摘要 | — |
| `yunxiao insight query-purchase-failed-resource-cause list` | 购买失败资源原因 | — |

**子组列表**：api-error, event-hub, host-summary, purchase-failed-alarm, query-purchase-failed-resource-cause, sold-out-alarm, tsa-alarm, user-activity, vstation-error-code, vstation-event

---

## 7. themis（忒弥斯 — 认证与访问控制）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao themis service-account list` | 查询服务账号 | — |
| `yunxiao themis service-account service-account` | 添加/修改服务账号 ⚠️ | `--json-body` |
| `yunxiao themis service-account delete` | 删除服务账号 🔴 | `--json-body` |
| `yunxiao themis permission list` | 权限列表 | — |
| `yunxiao themis policy list` | 策略列表 | — |
| `yunxiao themis user list` | 用户列表 | — |

**子组列表**：auth, authenticate, ioa-login, login-user, permission, policy, policy-apply, service-account, sign-out, swagger-mock-login, user, user-permission

---

## 8. tool（常用工具）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao tool api-error list` | 查询 API 错误 | — |
| `yunxiao tool host list` | 查询工具宿主机 | `--region` |
| `yunxiao tool region-alias list` | 地域别名 | — |
| `yunxiao tool myoa list` | MyOA 工具 | — |
| `yunxiao tool download list` | 下载列表 | — |
| `yunxiao tool jasypt list` | 加解密工具 | — |
| `yunxiao tool verify-data-source list` | 数据源验证 | — |
| `yunxiao tool verify-sql-query list` | SQL 查询验证 | — |

**子组列表**：add-whitelist, api-error, check-non-under-security-control, check-under-security-control, device-class-by-host-type, device-class-by-instance-family, download, fault-reserve-alarm-query, fault-reserve-resource-analysis, gins-instance-family, host, host-type-by-device-class, host-type-by-instance-family, instance-family-by-device-class, jasypt, myoa, region-alias, tcres, test, verify-data-source, verify-sql-query, verify-sql-query-all-regions, vpc

---

## 9. octopus（八爪鱼 — 分布式调度）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao octopus task list` | 任务列表 | — |
| `yunxiao octopus scheduler list` | 调度器列表 | — |
| `yunxiao octopus execution list` | 执行列表 | — |
| `yunxiao octopus controller list` | 控制器列表 | — |

**子组列表**：controller, execution, move-task-names, scheduler, task, test

---

## 10. pricing（定价看板）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao pricing pricing-baseline list` | 定价基线 | — |
| `yunxiao pricing pricing-baseline-query list` | 基线查询 | — |
| `yunxiao pricing query-aws-price-data list` | AWS 价格对比 | — |
| `yunxiao pricing check-pricing-data list` | 检查定价数据 | — |

**子组列表**：add-pricing-data, check-pricing-data, competitor-instance-type-list, fetch-combination-pricing-data, pricing-baseline, pricing-baseline-add, pricing-baseline-query, produce-standard-file-data, query-aws-price-data ...

---

## 11. flow（如流 — MyOA 审批流）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao flow flow list` | 审批流列表 | `--status` |
| `yunxiao flow flow create` | 创建审批流 ⚠️ | `--json-body` |
| `yunxiao flow template list` | 模板列表 | — |
| `yunxiao flow callback list` | 回调列表 | — |

**子组列表**：callback, flow, metadata, template

---

## 12. quota（配额管理）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao quota quota-instance list` | 配额实例 | — |
| `yunxiao quota quota-key list` | 配额 Key | — |
| `yunxiao quota quota-crp list` | 配额 CRP | — |
| `yunxiao quota quota-apply list` | 配额申请 | — |

**子组列表**：metadata, quota-apply, quota-crp, quota-instance, quota-key

---

## 13. vstation（VStation 运维工具）

| 命令 | 用途 | 常用参数 |
|------|------|---------|
| `yunxiao vstation protected-inventory query` | 保护库存查询 | `--region` |
| `yunxiao vstation protected-inventory create` | 新增保护水位配置 ⚠️ | `--json-body` |
| `yunxiao vstation protected-inventory modify` | 修改保护水位配置 ⚠️ | `--json-body` |
| `yunxiao vstation protected-inventory batch-create` | 批量新增配置 ⚠️ | `--json-body` |
| `yunxiao vstation protected-inventory batch-modify` | 批量修改配置 ⚠️ | `--json-body` |

**子组列表**：protected-inventory

---

## 通用配置命令

| 命令 | 用途 |
|------|------|
| `yunxiao --version` | 显示版本号 |
| `yunxiao --help` | 显示帮助 |
| `yunxiao config init` | 交互式初始化配置 |
| `yunxiao config show` | 显示当前配置及来源 |
| `yunxiao config set <key> <value>` | 设置配置值 |
