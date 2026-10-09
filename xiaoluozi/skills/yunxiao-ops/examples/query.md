# 查询操作场景示例

> 以下示例展示了使用 `yunxiao` CLI 进行各种查询操作的真实场景。
> ⚠️ `--format`/`--quiet`/`--verbose` 等全局选项必须放在 service 名称**之前**。
> 💡 JSON 是默认输出格式，Agent 调用时无需显式加 `--format json`。

---

## 场景 1：查询某地域的库存水位

**用户问**：\"广州地域 S5 机型的库存情况怎么样？\"

```bash
# Step 1: Query stock metrics for S5 in ap-guangzhou
yunxiao beacon stock-metrics list --region ap-guangzhou --instance-family S5

# Step 2: If need more detail, check the CVM type config
yunxiao beacon cvm-type-config list --region ap-guangzhou --instance-family S5

# Step 3: For zone-level breakdown (ceres inventory)
yunxiao --quiet beacon ceres zone-instance-type-infos --region ap-guangzhou
```

**Agent 解读要点**：
- 关注 `data` 字段中的库存相关数值
- 如果多个可用区，帮用户对比各区余量
- 使用 `beacon stock-metrics inventory` 可获取更详细的库存看板数据

---

## 场景 2：查询元数据——地域和可用区

**用户问**：\"当前有哪些地域可用？每个地域有几个可用区？\"

```bash
# Step 1: List all regions
yunxiao --quiet data360 region region

# Step 2: List zones for a specific region
yunxiao --quiet data360 zone zone --region ap-guangzhou

# Step 3: Cross-reference with tencent regions
yunxiao --quiet data360 tencent-region list
```

---

## 场景 3：查询实例类型信息

**用户问**：\"S5.LARGE8 这个机型的具体配置是什么？\"

```bash
# Query instance type details
yunxiao data360 instance-type instance-type --instance-type S5.LARGE8

# Or get a single instance type
yunxiao data360 instance-type get --instance-type S5.LARGE8

# Query the instance family info
yunxiao data360 instance-family instance-family --instance-family S5
```

---

## 场景 4：查询资源预留订单

**用户问**：\"看看最近的预留订单情况\"

```bash
# List orders I created
yunxiao --format table rubik order my-created

# Filter by status (check --help for available filters)
yunxiao --format table rubik order my-created --status APPROVED

# Check grid allocations
yunxiao rubik grid grid --region ap-guangzhou

# View order summary
yunxiao rubik order summary
```

---

## 场景 5：查询宿主机信息

**用户问**：\"广州地域有多少宿主机？状态分别是什么？\"

```bash
# Query hosts in a region
yunxiao --quiet honeycomb host host --region ap-guangzhou

# Check host statistics by zone and type
yunxiao --format table honeycomb host sum --region ap-guangzhou

# Query host component info
yunxiao honeycomb component list --region ap-guangzhou
```

---

## 场景 6：查询购买失败告警

**用户问**：\"最近有没有购买失败的告警？\"

```bash
# Query purchase failed alarms
yunxiao insight purchase-failed-alarm records

# Check sold-out alarm configs
yunxiao --format table insight sold-out-alarm config-list

# Get event hub records
yunxiao insight event-hub event-list
```

---

## 场景 7：查询运营指标

**用户问**：\"看一下最近的运营指标数据\"

```bash
# Query operation metrics
yunxiao compass operation-metrics list

# Compare with competitor instances
yunxiao --format table compass instance list

# Check instance family info from compass perspective
yunxiao compass instance-family list
```

---

## 场景 8：查询权限和服务账号

**用户问**：\"看看有哪些服务账号？\"

```bash
# List service accounts
yunxiao --format table themis service-account list

# Check permissions
yunxiao themis permission list

# Query policies
yunxiao --format table themis policy list
```

---

## 场景 9：查询配额信息

**用户问**：\"当前配额使用情况如何？\"

```bash
# List quota instances
yunxiao quota quota-instance list

# Check quota keys
yunxiao quota quota-key list

# Query quota CRP
yunxiao quota quota-crp list
```

---

## 场景 10：组合查询——全面了解一个地域

**用户问**：\"给我一个广州地域的全面摘要\"

```bash
# 1. Region and zone info
yunxiao --quiet data360 region region
yunxiao --quiet data360 zone zone --region ap-guangzhou

# 2. Stock levels
yunxiao --quiet beacon stock-metrics list --region ap-guangzhou

# 3. Host overview
yunxiao --quiet honeycomb host host --region ap-guangzhou

# 4. Recent alarms
yunxiao --quiet insight purchase-failed-alarm records
yunxiao --quiet insight sold-out-alarm config-list

# 5. Active orders
yunxiao --quiet rubik order my-created --region ap-guangzhou
```

**Agent 汇总技巧**：
- 将多个命令的 JSON 输出合并
- 按维度（库存/宿主机/告警/订单）分类汇总
- 用表格形式展示给用户
- 标注异常数据（如库存低于水位线的机型）

---

## 场景 11：查询预扣单对应的宿主机固资

**用户问**："查出 AppID 1395508128 广州 MA9.16XLARGE512 带置放群组最新预扣 13 台的对应固资"

**Agent 执行流程：**

```bash
# Step 1: 查该客户的 MA9 预扣单（注意用 --app-ids 复数）
yunxiao --quiet rubik reservation-form list \
  --app-ids '[1395508128]' \
  --instance-family '["MA9"]' \
  --page-size 100 --page-number 1
# 关注返回字段: id, status, count, createdCount, disasterRecoverGroupIdList(置放群组)
# 找到目标预扣单（如 ID 367378, PARTIAL_CREATED, 有置放群组 ps-q62469dx）

# Step 2: 查预扣单关联的 grid 块
yunxiao --quiet rubik reservation-form grid \
  --reservation-form-id '[367378]' \
  --page-size 100 --page-number 1
# 按 gridTaskId + createDate 分组，找到最新批次（如 13 个块）
# 提取所有 gridId 列表

# Step 3: 用 gridId 批量查块详情，获取宿主机 IP
yunxiao --quiet rubik grid grid \
  --grid-id '[11613186,11613187,11613188,11613189,11613190,11613191,11613192,11613193,11613194,11613195,11613196,11613197,11613198]' \
  --region ap-guangzhou --limit 20
# 从返回结果提取不重复的 hostIp 列表

# Step 4: 用 IP 批量查宿主机固资号
yunxiao --quiet honeycomb host host \
  --ip '["30.111.106.198","30.111.105.17","30.111.106.133","28.77.13.134","28.77.12.155","30.111.105.18","28.77.13.90"]' \
  --region ap-guangzhou --limit 20
# 返回字段: ip, asset(固资号), rackId, type(母机型号), cpuTotal, memTotal
```

**Agent 汇总技巧：**
- 建立 gridId → hostIp → asset(固资号) 的映射关系
- 一台母机可能对应多个 grid 块（如 MA9.16XLARGE512 每台母机切2个块）
- 输出表格：序号 | GridID | 宿主机 IP | 固资号 | 机架
- 去重后单独列出宿主机固资清单

---

## 场景 12：查询定价信息

**用户问**：\"查一下 S5 机型的定价基线\"

```bash
# Query pricing baseline
yunxiao pricing pricing-baseline list

# Check AWS comparison price data
yunxiao pricing query-aws-price-data list
```

---

## 场景 13：发现可用命令

**用户问**：\"beacon 服务下有哪些可以查询的东西？\"

```bash
# Discover subgroups
yunxiao beacon --help

# Discover actions under a subgroup
yunxiao beacon stock-metrics --help

# Get parameter details for a command
yunxiao beacon stock-metrics list --help
```

**Agent 行为**：先用 `--help` 发现命令结构，再根据用户需求选择合适的命令。
