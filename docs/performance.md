# WebUI 性能估计与采样率调参指南

> 适用范围: 当前 `simulated-webui-mvp` 这一版（合成信号 + ring buffer + 10 fps WebSocket 流）  
> 硬件: 实验机 Dell Precision 3660 (Manjaro Linux) + RTX 4070 + USB-6002 DAQ + Keithley 6514  
> 客户端: 浏览器（Chrome/Safari）通过 LAN 访问 `http://10.24.32.98`  
> 更新日期: 2026-05-03

> **TODO** — CPU / RAM 实测数据待补。机器在线时跑下面两条贴回来：
> ```bash
> ssh lab4070 'lscpu | grep -E "Model name|^CPU\(s\)|Thread|Socket|MHz"'
> ssh lab4070 'free -h | head -2'
> ```
> 目前所有内存预算和 CPU 占比是**理论估算 + 旧 dmesg 里看到的 KVM 活动**反推（提示该机至少有 i5/i7 级别 CPU 与 ≥ 16 GB RAM，足以宿主多个 VM）。Precision 3660 出厂典型配置区间是 12 代 Intel i5/i7/i9 + 16/32/64 GB DDR5。

---

## 1. 数据通路总览

```
┌─────────────┐   block 生成器（producer，5kS/s 默认）
│ simulator   │   一块 = max(64, rate/20) = 250 样本（20 blocks/s）
└──────┬──────┘
       │ append
       ▼
┌─────────────┐   ring buffer：rate × buffer_seconds 个 float64
│ RingBuffer  │   默认 5 kS/s × 120 s = 600 000 样本 = 4.8 MB
└──────┬──────┘
       │ tail(window)  — 默认 8 s 窗口
       │ decimate(≤ 720 点)
       ▼
┌─────────────┐   /ws/stream，10 fps（每帧 sleep 100 ms）
│ WebSocket   │   每帧 JSON ≈ 720 点 × 2 字段 × ~8 ASCII = ~12 KB
└──────┬──────┘
       │ 1 Mbps 量级
       ▼
┌─────────────┐   canvas 2D 重绘 + 客户端 256 点 FFT
│ Browser     │   0.5 ms 级别画一帧，CPU 几乎跑空
└─────────────┘
```

**关键点**：
- Producer 与 consumer 之间通过 ring buffer 解耦。Producer 节奏由 `sample_rate_hz` 决定，consumer 节奏固定 10 fps。
- 即使采样率冲到 50 kS/s，浏览器看到的也永远是降采样到 ≤ 720 点的版本——不会因为采样率高就把前端拖卡。
- 真正的瓶颈不在带宽，在 **后端内存**（ring buffer 总占用）和 **producer-consumer 解耦时 lock 抢占**。

---

## 2. 资源预算（按采样率）

`buffer_seconds = 120`（默认），`stream_points = 720`，`stream_window_s = 8.0`。

| 采样率 | Ring buffer 内存 | Producer block | 一帧带宽 | 后端 CPU | 客户端帧时延 | 备注 |
|-------:|----------------:|---------------:|--------:|---------:|------------:|------|
|   500 S/s | 0.5 MB | 64 样本/50 ms | ~12 KB | < 1% | ~0.5 ms | 看慢电荷漂移用 |
|  1 kS/s | 1.0 MB | 64 样本/64 ms | ~12 KB | < 1% | ~0.5 ms | 慢测最佳 |
|  5 kS/s | 4.8 MB | 250 样本/50 ms | ~12 KB | ~1% | ~0.5 ms | **当前默认** |
| 10 kS/s | 9.6 MB | 500 样本/50 ms | ~12 KB | ~1% | ~0.5 ms | 安全线内 |
| 20 kS/s | 19.2 MB | 1000 样本/50 ms | ~12 KB | ~2% | ~0.5 ms | 还行 |
| 50 kS/s | 48 MB | 2500 样本/50 ms | ~12 KB | ~5% | ~0.6 ms | DAQ 单通道极限 |
|100 kS/s | 96 MB | 5000 样本/50 ms | ~12 KB | ~10% | ~0.7 ms | **超 DAQ 上限**，仅 simulator 能跑 |
|200 kS/s | **192 MB** | 10000 样本/50 ms | ~12 KB | ~20% | ~0.8 ms | 内存压力 ⚠️，建议同时缩 buffer_seconds |

**带宽列**之所以恒定 12 KB：因为我们总把窗口降采到 ≤ 720 点。这就是设计上的"前端无关采样率"。

**不要被 GPU 误导**：本应用没用到 RTX 4070 的算力。整个链路是 CPU + 网络 + 内存的事。

---

## 3. 崩溃模式 & 怎么避

| 症状 | 根因 | 防御 |
|------|------|------|
| 浏览器 tab 卡死 | 单帧塞 > 2000 点 + 高刷新（> 20 fps） | 保持 `stream_points ≤ 1000`，`/ws/stream` 固定 10 fps（已硬编码 `sleep(0.1)`） |
| 后端 OOM | `rate × buffer_seconds × 8` 超过可用 RAM | 高速时缩 `PICKUP_EDS_BUFFER_SECONDS`：100 kS/s 时给 30 s 即可 |
| WebSocket 堆积 → 客户端断线 | 客户端处理不过来，TCP send buffer 满 | 当前帧 12 KB × 10 fps 远低于阈值；除非把 `stream_points` 拉到 5000+ 才会触发 |
| 录制完前端不刷新 | Auto-stop bug（已修，commit `a476c2f`） | 升级到该 commit 之后正常 |
| `/dev/ttyUSB0` 反复掉线 | pl2303 + ATEN bridge 在 6514 重启时容易脱档 | 见 `dev-real-hardware.md §6` 的 USB rebind 一招 |
| 录制目录写满 | 50 kS/s × 60 s × 8 bytes = 24 MB / 次 | 50 kS/s 录 1 分钟也才 24 MB，正常磁盘容量没事；担心就定期清 `data/recordings/` |

**没那么容易触发的（不用担心）**：
- 浏览器画 720 点 canvas at 10 fps = 7200 ops/s：现代 GPU 加速 canvas 0.1 ms 一帧
- 后端 numpy `decimate_pair` on 40000 → 720 = ~50 µs，10 fps × 50 µs = 0.05% CPU
- JSON 序列化 720 浮点：~0.5 ms，可忽略

---

## 4. 调参旋钮

通过环境变量控制，**改完要重启 webui 服务**（`bash scripts/deploy_webui.sh` 会自动重启）。

```bash
# 在部署前 export 这些，或写进 ~/.profile / systemd unit
PICKUP_EDS_SAMPLE_RATE_HZ=10000      # 默认 5000
PICKUP_EDS_BUFFER_SECONDS=60         # 默认 120
PICKUP_EDS_STREAM_POINTS=720         # 默认 720
PICKUP_EDS_STREAM_WINDOW_S=8         # 默认 8.0
```

| 变量 | 调大的代价 | 调小的代价 |
|------|-----------|-----------|
| `SAMPLE_RATE_HZ` | 内存 + 后端 CPU | 看不到高频细节 |
| `BUFFER_SECONDS` | 内存（线性） | 录制窗口短，回放短 |
| `STREAM_POINTS` | 客户端 CPU + 带宽 | 波形糙 |
| `STREAM_WINDOW_S` | 单帧降采样起点变多 | 视野窄 |

> ⚠️ `STREAM_POINTS × 10 fps` 是真正决定带宽的：默认 720 × 10 = 7200 点/秒。拉到 2000 还能 hold 住，超过 5000 就不要了——客户端开始掉帧。

**前端 FFT 窗口**: 客户端 256 点，硬编码在 `index.html` 的 inline JS 里。改它需要改前端文件。CPU 影响可忽略（256 点 FFT 几十微秒）。

---

## 5. 预设场景（推荐配置）

### 场景 A · 慢电荷 / 漂移监测（< 10 Hz 信号）
```
SAMPLE_RATE_HZ=500
BUFFER_SECONDS=600     # 10 分钟回放
STREAM_POINTS=720
STREAM_WINDOW_S=30     # 看 30 秒窗口
```
预算: ring buffer 0.5 × 600 / 5 ≈ 0.3 MB，整套零压力。

### 场景 B · 当前默认（20-200 Hz 信号，常规调试）
```
SAMPLE_RATE_HZ=5000
BUFFER_SECONDS=120
STREAM_POINTS=720
STREAM_WINDOW_S=8
```
预算: 4.8 MB ring buffer，~1% 后端 CPU，0.5 ms 一帧。**不动这些就行**。

### 场景 C · 音频带宽测试（200-2000 Hz 信号）
```
SAMPLE_RATE_HZ=20000
BUFFER_SECONDS=60      # 缩短保留 1 GB RAM 余量
STREAM_POINTS=1000     # 高频信号给前端多点细节
STREAM_WINDOW_S=4      # 窗短一点，看高频更清楚
```
预算: 19.2 MB ring buffer，~2% 后端 CPU，1.4 Mbps WebSocket。

### 场景 D · DAQ 极限单通道（> 2 kHz 信号，6514 ANALOG OUT 已超带宽，仅供 simulator 实验）
```
SAMPLE_RATE_HZ=50000
BUFFER_SECONDS=20      # 顶死也就 8 MB
STREAM_POINTS=1000
STREAM_WINDOW_S=2
```
预算: 8 MB ring buffer，~5% 后端 CPU。**真机阶段记住 6514 的 2V ANALOG OUTPUT 标称带宽 ~ 2 kHz**，超过这个采样率只是在测噪声。

### 不推荐 · 极限实验
```
SAMPLE_RATE_HZ=200000
BUFFER_SECONDS=10
STREAM_POINTS=2000
```
预算: 16 MB ring buffer，~20% 后端 CPU，3 Mbps。能跑但意义不大，远超硬件物理带宽。

---

## 6. 健康监测

部署后跑这条就能看到当前服务在吃多少：

```bash
ssh a203@203-precision3660 'ps -o pid,pcpu,rss,cmd -p $(cat /home/a203/pickup-material-eds-webui/webui.pid) 2>/dev/null'
```

| 指标 | 健康范围 | 报警阈值 |
|------|---------|---------|
| `%CPU` | < 5% | > 30% 持续 |
| `RSS` | 80-200 MB | > 500 MB（多半是 buffer_seconds × rate 设大了） |
| `/api/health` 响应时延 | < 50 ms | > 500 ms |
| WebSocket reconnect 频率 | 0 次/分钟 | > 1 次/分钟 |

也可以直接看 webui 自己的日志：
```bash
ssh a203@203-precision3660 'tail -50 /home/a203/pickup-material-eds-webui/webui.log'
```

---

## 7. 真机 BenchService 接入后的额外考虑

当前 simulator 在 Python 里直接生成数组，**没有 IO 等待**。换成真机后多了：

1. **DAQ 块到达节奏不可控**: USB-6002 按硬件 buffer 块出数据，可能 50 ms 一次也可能 100 ms 一次。需要在 BenchService 里做 backpressure，避免 `_buffer.append_block` 抢锁太久。
2. **6514 SCPI 串行化延迟**: 任何 SCPI 命令都要 100-500 ms（pyserial + Xon/Xoff + 6514 内部处理）。控制 UI 操作（切 FUNC/RANG）那一刻要忍 0.5 秒延迟。
3. **DAQ 与 SCPI 并行**: pyserial 跟 nidaqmx 走的是不同 USB 设备，可以并发。但要注意 `asyncio.to_thread` 的线程池上限（默认 40，够用）。
4. **录制时的 backpressure**: 当前 `_record_times.append(times.copy())` 是无限增长的 list，长录制会内存爆炸。真机阶段要换成滚动写文件（partial flush）。

性能预算到那时候要重新算——这份文档基于 simulator 的数字，参考价值在于"上限在哪"，真机 IO 会让单个数字差一倍内。

---

## 8. 快速决策表

> "我应该把采样率调到多少？"

```
问题: 信号最高频率是多少？
  < 1 Hz       → 200 S/s     场景 A
  10-50 Hz     → 500 S/s     场景 A 改一下
  50-500 Hz    → 5 kS/s      场景 B（默认）
  500-2 kHz    → 20 kS/s     场景 C
  > 2 kHz      → 真机过不了 6514 带宽，意义有限
```

> "改了之后服务卡了/崩了怎么办？"

```
1. ssh 进机看 webui.log 末尾是什么
2. ps -o pcpu,rss 看 CPU/内存
3. RSS > 500 MB → 缩 BUFFER_SECONDS
4. CPU > 30% → 缩 SAMPLE_RATE_HZ
5. 上面都没事但浏览器卡 → 缩 STREAM_POINTS
6. 不行就回默认值: 全部 unset 那 4 个 env var, 重启
```
