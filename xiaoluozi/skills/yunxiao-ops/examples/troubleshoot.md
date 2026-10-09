# 故障排查场景示例

> 以下示例展示了使用 `yunxiao` CLI 进行故障诊断和运维排查的真实场景。
> ⚠️ `--format`/`--quiet`/`--verbose` 等全局选项必须放在 service 名称**之前**。
> 💡 JSON 是默认输出格式，Agent 调用时无需显式加 `--format json`。

---

## 场景 1：购买失败排查

**用户问**：\"用户反馈在广州买 S5 机型失败了，帮我查下原因\"

```bash
# Step 1: Check purchase failed alarms
yunxiao --quiet insight purchase-failed-alarm records

# Step 2: Check resource-level failure cause
yunxiao --quiet insight query-purchase-failed-resource-cause list

# Step 3: Check if stock is depleted
yunxiao beacon stock-metrics list --region ap-guangzhou --instance-family S5

# Step 4: Check stock alert metrics
yunxiao beacon stock-alert-metrics metrics --region ap-guangzhou

# Step 5: Check sold-out alarm configs
yunxiao --quiet insight sold-out-alarm config-list
```

**Agent 分析流程**：
1. 先看购买失败告警记录，确认失败原因码
2. 如果是资源不足，检查库存水位
3. 如果库存为 0，检查是否触发了售罄告警
4. 汇总给用户：失败原因 + 当前库存状态 + 建议措施

---

## 场景 2：库存告警排查

**用户问**：\"收到库存告警了，帮我看看情况\"

```bash
# Step 1: Check stock alert metrics
yunxiao --quiet beacon stock-alert-metrics metrics

# Step 2: Get detailed stock level
yunxiao --quiet beacon stock-metrics list

# Step 3: Check stock pool level (use --help to find exact action)
yunxiao beacon stock-pool-level --help

# Step 4: Check if there are pending stock plans
yunxiao --quiet beacon stock-plan evaluate

# Step 5: Check predict consumption
yunxiao --quiet beacon predict-consumption list
```

**Agent 分析流程**：
1. 确认哪些地域/机型触发了告警
2. 查看当前水位与安全线的差距
3. 检查是否有备货计划正在执行
4. 评估消耗趋势预测
5. 给出建议：是否需要紧急备货或调整水位线

---

## 场景 3：宿主机故障排查

**用户问**：\"广州的一台宿主机 10.0.0.1 出问题了\"

```bash
# Step 1: Get host info
yunxiao honeycomb host host --host-ip 10.0.0.1 --region ap-guangzhou

# Step 2: Check host's recent actions
yunxiao honeycomb action-audit list --region ap-guangzhou --host-ip 10.0.0.1

# Step 3: Check device failure rate
yunxiao honeycomb device-failure-rate list --region ap-guangzhou

# Step 4: Check fault reserve info
yunxiao honeycomb fault-reserve list --region ap-guangzhou

# Step 5: Check host components
yunxiao honeycomb component list --region ap-guangzhou --host-ip 10.0.0.1

# Step 6: Check host tags
yunxiao honeycomb host-tag list --region ap-guangzhou
```

**Agent 分析流程**：
1. 确认宿主机当前状态
2. 回溯最近操作记录
3. 检查硬件部件状态
4. 评估是否需要下架维修
5. 检查是否已有故障保留

---

## 场景 4：VStation 事件排查

**用户问**：\"查一下最近的 VStation 异常事件\"

```bash
# Step 1: Query VStation events
yunxiao --quiet insight vstation-event list

# Step 2: Check VStation error codes
yunxiao --quiet insight vstation-error-code list

# Step 3: Check TSA alarms
yunxiao --quiet insight tsa-alarm list

# Step 4: Check event hub for related events
yunxiao --quiet insight event-hub event-list
```

---

## 场景 5：用户活动分析

**用户问**：\"看看最近用户购买和退还的情况\"

```bash
# Step 1: Query user activity summary
yunxiao --quiet insight user-activity list

# Step 2: Check host summary
yunxiao --quiet insight host-summary list

# Step 3: Cross-check with orders
yunxiao --quiet rubik order my-created
```

---

## 场景 6：API 错误排查

**用户问**：\"调用 API 报错了，错误码是 XXXX\"

```bash
# Step 1: Look up the error code
yunxiao --quiet tool api-error list

# Step 2: Check API error from insight
yunxiao --quiet insight api-error list

# Step 3: Verify connectivity
yunxiao config show
```

**Agent 分析流程**：
1. 根据错误码查找含义
2. 检查是否为已知问题
3. 验证配置是否正确
4. 建议修复方案

---

## 场景 7：跨服务关联排查

**用户问**：\"为什么广州三区的 S5.LARGE8 买不到了？\"

```bash
# 1. Check stock (beacon)
yunxiao --quiet beacon stock-metrics list --region ap-guangzhou --instance-family S5

# 2. Check inventory (beacon)
yunxiao --quiet beacon inventory inventory --region ap-guangzhou

# 3. Check CVM type config - is it enabled for sale?
yunxiao --quiet beacon cvm-type-config list --region ap-guangzhou --instance-type S5.LARGE8

# 4. Check zone-level stock (beacon ceres)
yunxiao --quiet beacon ceres zone-instance-type-infos --region ap-guangzhou

# 5. Check if there are purchase failure records (insight)
yunxiao --quiet insight purchase-failed-alarm records

# 6. Check quota limits (quota)
yunxiao --quiet quota quota-instance list

# 7. Check grid reservation (rubik)
yunxiao --quiet rubik grid grid --region ap-guangzhou

# 8. Check host availability (honeycomb)
yunxiao --quiet honeycomb host host --region ap-guangzhou
```

**Agent 排查逻辑树**：
```
买不到机器？
├── 库存为 0？
│   ├── 是 → 需要备货 (beacon stock-plan)
│   └── 否 → 继续排查
├── 机型未上架/售卖？
│   ├── CVM type config 中 enabled=false？ → 联系管理员
│   └── 继续排查
├── 配额超限？
│   ├── quota-instance 中 used >= limit？ → 申请扩容
│   └── 继续排查
├── 预留占用？
│   ├── grid 中 reserved 占了大部分？ → 协调预留释放
│   └── 继续排查
└── 宿主机不足？
    └── host list 中没有可用宿主机？ → 需要上架新宿主机
```

---

## 排查黄金规则

1. **从告警入手** — 先查 insight 服务的各类告警
2. **从上到下** — 先看全局（地域级），再看细节（可用区/机型级）
3. **跨服务关联** — 一个问题往往涉及多个服务的数据
4. **保留 RequestId** — 如果 API 报错，保留 requestId 方便追踪
5. **用 `--verbose` 调试** — 不确定请求细节时用 `yunxiao --verbose ...` 查看完整请求/响应（注意 `--verbose` 要放在 service 之前）
