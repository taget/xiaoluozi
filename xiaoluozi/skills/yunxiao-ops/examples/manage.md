# 管理操作场景示例

> 以下示例展示了使用 `yunxiao` CLI 进行创建、更新、删除等写操作的真实场景。
> ⚠️ 写操作必须遵循安全规范，参见 SKILL.md 第四节。
> ⚠️ `--format`/`--quiet`/`--verbose` 等全局选项必须放在 service 名称**之前**。
> 💡 JSON 是默认输出格式，Agent 调用时无需显式加 `--format json`。

---

## 场景 1：创建资源预扣单

**用户问**：\"帮我在广州三区预扣 10 台 S5.LARGE8\"

**Agent 执行流程：**

```bash
# Step 1 [查询确认]: Verify the instance type exists and has stock
yunxiao --quiet beacon stock-metrics list --region ap-guangzhou --instance-family S5

# Step 2 [查询确认]: Check zone availability
yunxiao --quiet data360 zone zone --region ap-guangzhou

# Step 3 [获取用户信息]: Extract current user from WorkBuddy logs
CURRENT_USER=$(grep -i "用户.*登录" \
  ~/Library/Application\ Support/WorkBuddy/logs/*/Claw--*/exthost/Tencent-Cloud.coding-copilot/WorkBuddy.*.log \
  2>/dev/null | tail -1 | grep -oP '用户 \K\S+(?= 登录)')
echo "Current user: $CURRENT_USER"
```

**Agent 向用户确认**：\"确认要在 ap-guangzhou-3 预扣 10 台 S5.LARGE8？以下是将要执行的命令：...\"

> ⚠️ `reservation-form create` 必填字段：`zone`、`instanceType`、`applyCount`、`creator`、`uin`、`destroyTime`、`reason`
> ⚠️ `destroyTime` 必须使用 `date` 命令动态生成，禁止手动拼写（参见 SKILL.md 3.4 时间参数格式约束）

```bash
# Step 4 [写操作 - 需确认]: Create the reservation form
yunxiao rubik reservation-form create --json-body "{
  \"zone\": \"ap-guangzhou-3\",
  \"instanceType\": \"S5.LARGE8\",
  \"applyCount\": 10,
  \"creator\": \"${CURRENT_USER}\",
  \"uin\": \"3205597606\",
  \"destroyTime\": \"$(date -v+7d '+%Y-%m-%d %H:%M:%S')\",
  \"reason\": \"广州三区 S5.LARGE8 预扣 10 台\"
}"

# Step 5 [结果验证]: Verify the reservation form was created
yunxiao --format table rubik reservation-form list
```

---

## 场景 2：管理审批流

**用户问**：\"提交一个配额申请审批\"

```bash
# Step 1 [查询]: List available flow templates (use --help to find exact action)
yunxiao flow template --help
yunxiao flow template list

# Step 2 [查询]: Check current quota
yunxiao quota quota-instance list
```

**Agent 向用户确认**：展示模板选项和当前配额，确认申请参数。

```bash
# Step 3 [写操作 - 需确认]: Submit the flow (use --help to find create action)
yunxiao flow flow --help
yunxiao flow flow create --json-body '{
  "templateId": "xxx",
  "title": "配额申请 - S5 机型扩容",
  "params": {...}
}'

# Step 4 [结果验证]: Check flow status
yunxiao --format table flow flow list
```

---

## 场景 3：管理服务账号

**用户问**：\"创建一个新的服务账号\"

```bash
# Step 1 [查询]: List existing service accounts
yunxiao --format table themis service-account list
```

**Agent 向用户确认**：确认账号名称和权限范围。

```bash
# Step 2 [写操作 - 需确认]: Create service account (action is "service-account", not "create")
yunxiao themis service-account service-account --json-body '{
  "name": "new-service-account",
  "description": "..."
}'

# Step 3 [结果验证]: Verify creation
yunxiao --format table themis service-account list
```

---

## 场景 4：配置管理

**用户问**：\"切换到测试环境的 API 地址\"

```bash
# Step 1: Show current config
yunxiao config show

# Step 2 [写操作]: Update API URL
yunxiao config set api_url "http://test-api.yunxiao.vstation.woa.com"

# Step 3: Verify the change
yunxiao config show
```

---

## 场景 5：更新预留网格

**用户问**：\"调整广州三区 S5 的预留量\"

```bash
# Step 1 [查询]: Get current grid info
yunxiao --quiet rubik grid grid --region ap-guangzhou

# Step 2 [查询]: Check available stock
yunxiao --quiet beacon stock-metrics list --region ap-guangzhou --instance-family S5
```

**Agent 向用户确认**：展示当前预留量和库存余量，确认调整目标。

```bash
# Step 3 [写操作 - 需确认]: Create new grid reservation (reserve, not update)
yunxiao rubik grid reserve --json-body '{
  "region": "ap-guangzhou",
  "zone": "ap-guangzhou-3",
  "instanceType": "S5.LARGE8",
  "count": 20
}'

# Step 4 [结果验证]: Verify the change
yunxiao --quiet rubik grid grid --region ap-guangzhou
```

---

## 场景 6：宿主机操作

**用户问**：\"对指定宿主机执行上架操作\"

```bash
# Step 1 [查询]: Get host details
yunxiao --quiet honeycomb host host --region ap-guangzhou

# Step 2 [查询]: Check host current status
yunxiao honeycomb host host --host-ip 10.0.0.1 --region ap-guangzhou
```

**Agent 向用户确认**：展示宿主机当前状态，确认操作目标。

```bash
# Step 3 [写操作 - 需确认]: Execute host action
yunxiao honeycomb action create --json-body '{
  "region": "ap-guangzhou",
  "hostIp": "10.0.0.1",
  "actionType": "SHELVE"
}'

# Step 4 [结果验证]: Verify the action result
yunxiao --format table honeycomb action-audit list --region ap-guangzhou
```

---

## 写操作黄金规则 ⚠️

1. **查询 → 确认 → 执行 → 验证** 四步走
2. 展示完整命令给用户审核
3. 写操作失败后**不要自动重试**，先分析错误原因
4. 批量操作逐条确认
5. 删除操作展示将被删除的资源详情
