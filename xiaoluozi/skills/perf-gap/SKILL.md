---
name: perf-gap
description: 云主机相对物理机吞吐下降约 20%–40% 时，按只读材料做分层排障。库存、配额和一般 vstation 报错不用。
---

# 云主机与物理机性能差距

目标是标准化复现、分层定位、用单变量实验验证根因，并写出可审计的 RCA 草稿。不要证明「虚拟化有多少开销」。应用线程、CPU 型号、内存拓扑、云盘、网络、资源争用和测试方法都可能造成 20%–40% 的差距。

只根据用户贴来的成绩、配置和采集输出回答。不要发起 SSH，不要跑压测，不要改绑核、NUMA、Huge Pages、QEMU 或实例规格。实验和修复写成待审批计划，明确隔离环境或可回滚测试实例。客户生产实例上不改。

## 材料不够

用户只说慢了、没有统一口径的多轮成绩，或没有两侧环境时，按这个结构回答，并且写明「现在不能认定根因」：

1. 指标口径。吞吐下降率是 `1 - 云主机吞吐 / 物理机吞吐`。P95、P99 单独比，不和吞吐下降率混用。
2. 公平性。两侧要同一业务版本、数据集、请求比例、压测工具和参数，同一预热和持续时间。至少 3 轮，保留原始结果。波动大时先查测试，不归因。
3. 采集清单。给出下面的 `collect_perf.sh`，说明在物理机和云主机的压测前、中、后各跑一次。需要看某个进程时设置 `PID`。脚本只读，不压测，不改配置，不要求 root。
4. 还缺的业务材料。业务类型、核心指标、两侧成绩、并发、持续时间。数据库或 Web 还要连接数、缓存命中率、连接池、请求分布、数据集、后台任务和外部依赖延迟。

示例只说明口径：物理机 10000 TPS、云主机 7000 TPS，下降率 30%。这只说明业务结果有差距。

## 材料够了

先写差距是否稳定，再按优先级列证据和缺口。每一项都写已有证据、还缺什么、反证是什么。

P0 先看资源限制和宿主机异常：实例规格和资源保障、vCPU 对应的 QEMU 线程与调度等待、测试窗口的宿主机争用、CPU 频率和降频、配额与 QoS、测试期间的迁移或维护。QEMU 线程的 R、S 状态只是线索，不能单独证明调度瓶颈。

P1 再看 QEMU/KVM 和 CPU 路径：版本、Guest CPU 型号和指令集、vCPU 与 I/O 线程亲和性、VM Exit 的原因和单位请求次数、virtio/vhost。VM Exit 多不等于慢，要和正常对照比。

P2 按业务选查，不要把每一项都查一遍：NUMA、内存压力、云盘延迟、网络队列和重传、同规格宿主机差异。

判定：

- 多轮差异大：先查测试方法和环境。
- 单线程和多线程都差：比 CPU 型号、频率和指令集。
- 单线程接近、多线程拉开：查调度、争用、NUMA。
- Guest CPU 忙但吞吐低：查执行效率、锁和调度，不要只看 Guest。
- CPU 有余、P99 升高：查锁、I/O、网络、队列和外部依赖。
- CPU 基准接近、业务下降：拆应用、缓存、存储和网络。
- 同规格实例之间差：做实例对照和宿主机核查。
- 改一个因素后稳定变好：回滚再测，确认因果关系。

没有宿主机数据时，不能因为 Guest 里看不出问题就认定是虚拟化层。

## 实验

只选最可能的 1–3 个假设。顺序是：E0 原样重复，E1 同规格健康实例，E2 单线程对比多线程，E3 CPU 亲和性，E4 NUMA 放置，E5 virtio/vhost 或队列，E6 规格或资源保障。E3–E6 要变更审批和回滚，不在客户生产实例上做。

每个实验写：实验 ID、假设、唯一变量、保持不变的项、记录的 TPS 和 P95/P99、预先定下的改善幅度、回滚后如何再测。

同时满足这五条才写「已确认根因」：现象可重复，机制有证据，改目标因素会变好且回滚后复现，业务吞吐和延迟都有收益，没有不可接受的副作用。只看到成绩变好、说不清原因时，写「有效优化，根因尚未完全确认」。

## RCA 草稿

包含问题描述、量化证据、根因和排除项、修复与回归、知识沉淀。结案只用这五种：已确认并修复；已优化，根因部分确认；已定位，待修复；暂未复现；证据不足。

若已影响客户生产 SLA，或大范围实例异常，写明应按生产事故升级，不要当成普通性能咨询。

## collect_perf.sh

把下面这份只读脚本交给需要采集的人。`mpstat`、`iostat`、`pidstat` 需要 sysstat，`numactl` 需要对应包。缺命令就跳过。10 秒快照只是线索，不能代替整段压测监控。

```bash
#!/usr/bin/env bash
# collect_perf.sh
# Usage:
#   bash collect_perf.sh
#   PID=1234 bash collect_perf.sh
#
# Read-only system collection; does not launch a benchmark.
# Run on both physical and cloud hosts during the same test phase.

set -u

OUT="perf-$(hostname)-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$OUT"
exec > >(tee "$OUT/summary.txt") 2>&1

run() {
    local name="$1"
    shift
    echo
    echo "===== $name ====="
    if command -v "$1" >/dev/null 2>&1; then
        "$@" 2>&1 || echo "[WARN] command failed: $name"
    else
        echo "[SKIP] command not found: $1"
    fi
}

echo "collection_start=$(date -Is)"
echo "hostname=$(hostname)"
echo "kernel=$(uname -r)"
echo "pid=${PID:-not_specified}"

run os-release cat /etc/os-release
run cpu-topology lscpu
run memory free -h
run numa numactl -H
run vmstat vmstat 1 10
run mpstat mpstat -P ALL 1 10
run iostat iostat -xz 1 10

echo
echo "===== CPU and memory pressure ====="
for f in /proc/pressure/cpu \
         /proc/pressure/memory \
         /proc/pressure/io; do
    if [ -r "$f" ]; then
        echo "--- $f"
        cat "$f"
    fi
done

echo
echo "===== Network interfaces ====="
ip -s link 2>&1 || true
ip route 2>&1 || true

echo
echo "===== Disk space ====="
df -hT 2>&1 || true

if [ -n "${PID:-}" ] && [[ "$PID" =~ ^[0-9]+$ ]] \
   && [ -d "/proc/$PID" ]; then
    echo
    echo "===== Target process ====="
    cat "/proc/$PID/status" 2>/dev/null || true
    cat "/proc/$PID/io" 2>/dev/null || true
    cat "/proc/$PID/sched" 2>/dev/null || true
    run target-pidstat pidstat -p "$PID" -u -r -d 1 10
fi

echo
echo "collection_end=$(date -Is)"
echo "Output directory: $OUT"
```
