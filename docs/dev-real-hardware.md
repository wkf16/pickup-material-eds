# 真机接入 — 临时桥 / 完整后端的过渡指南

> 目标读者: 后续要把这套 WebUI 真正接到 Keithley 6514 + USB-6002 的人  
> 当前阶段: **混合模式** — SCPI 控制台直连真机，其余仍用模拟器  
> 更新日期: 2026-05-03

---

## 1. 当前架构（临时形态）

```
┌──────────────────────────────────────────────────────────────────┐
│  Browser (WebUI v3, single-file inline assets)                   │
└──────────────────────────────────────────────────────────────────┘
                       │      ▲
                       │      │ /api/*  /ws/*
                       ▼      │
┌──────────────────────────────────────────────────────────────────┐
│  FastAPI app  (api/main.py)                                      │
│                                                                  │
│  lifespan ─► _maybe_open_real_scpi()                             │
│                 │                                                │
│                 ├─ open ok ──► Real6514Serial ──► /dev/ttyUSB0  │
│                 └─ open err ─► None  (silent fallback)           │
│                                                                  │
│  service = SimulatedBenchService(SETTINGS, real_scpi=...)        │
└──────────────────────────────────────────────────────────────────┘
                       │
   ┌───────────────────┼───────────────────────────┐
   ▼                   ▼                           ▼
 control/range      stream/recording        send_scpi(cmd)
 (simulated)        (simulated)             ├─ real_scpi  → real 6514
                                            └─ else        → _simulate_scpi
```

**关键点**：
- 只有 `POST /api/control/scpi/send` 走真机；其余 REST/WS 端点全是模拟器逻辑。
- 真机 SCPI 响应不会反向同步到 simulator 的 `ControlState`（即在 SCPI 控制台里发 `FUNC "CURR"`，UI 上的 "Function: VOLT" 高亮**不会**自动跟着切换到 CURR）。这一限制故意保留，等真机 BenchService 落地时再做双向同步。
- 这是临时形态，不要在它之上堆复杂功能。下一步是全面替换为真机 BenchService（见 §6）。

---

## 2. 涉及文件

| 文件 | 作用 |
|------|------|
| `src/pickup_eds/instruments/electrometer_serial.py` | 真机串口最小桥（pyserial + asyncio.to_thread） |
| `src/pickup_eds/instruments/simulator.py` | `__init__` 接 `real_scpi` 参数；`send_scpi` 优先走真机 |
| `src/pickup_eds/api/main.py` | lifespan 里尝试打开串口，失败回退；env 变量控制行为 |
| `deploy/99-keithley-6514.rules` | udev 规则，让 `uucp` 组成员免 sudo 访问 ATEN 桥 |
| `pyproject.toml` | 增加 `pyserial>=3.5` 运行时依赖 |

---

## 3. 环境变量

| 变量 | 默认 | 行为 |
|------|------|------|
| `PICKUP_EDS_REAL_SCPI` | `auto` | `auto`: 试着打开串口，失败回退模拟器 |
| | | `1`/`on`/`true`/`yes`: 强制真机；打不开就让 lifespan 失败 |
| | | `0`/`off`/`false`/`no`: 永远不碰串口，强制模拟器 |
| `PICKUP_EDS_SCPI_PORT` | `/dev/ttyUSB0` | 串口设备路径 |

健康端点 `/api/health` 现在会返回当前链路状态:
```json
{"ok": true, "mode": "simulated-webui-mvp",
 "scpi_link": "real" | "simulated",
 "scpi_port": "/dev/ttyUSB0" | null}
```

---

## 4. 实验机一次性配置（Manjaro Dell Precision 3660）

### 4.1 检查 USB-串口桥

```bash
lsusb | grep -i "067b:23a3"      # ATEN Serial Bridge (Prolific)
ls -l /dev/ttyUSB0               # 期望: crw-rw---- root uucp
groups a203                      # 期望: 列表里有 uucp
```

### 4.2 安装 udev 规则（如果 `/dev/ttyUSB0` 不在 `uucp` 组）

```bash
sudo cp deploy/99-keithley-6514.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
# 已插着的话拔插一次让规则生效
```

### 4.3 安装 pyserial（已包含在 `pyproject.toml`，正常 `pip install -e .` 即可）

部署脚本会自动跑 `pip install -e .`，所以下次 `bash scripts/deploy_webui.sh` 后 pyserial 就到位了。

---

## 5. 真机 SCPI 命令兼容性（重要）

模拟器对每条命令都返回 `OK` 之类的伪 echo，**真机不是这样**。不弄清差异会出现"前端按钮按下去都飘红"的假象。

### 5.1 命令分类

SCPI 命令分两类：

| 类型 | 末尾有 `?` | 真机响应 | 失败标志（我们的 UI） |
|------|----------|----------|----------------------|
| **Query** | 是 | ASCII 数据 + `\r` | 空响应 = 失败 |
| **Set** | 否 | **无任何响应**（沉默确认） | 空响应 = **成功**（不要标红） |

代码里 `simulator.py:send_scpi` 已经按这个规则处理（`is_query = "?" in normalized`）。前端不用动。

### 5.2 6514 SCPI 命令树陷阱

6514 的命令树**不维护当前节点上下文**——每条命令必须自带完整 root。常见踩坑：

| 想做的事 | ❌ 不行 | ✅ 正确 |
|---------|--------|--------|
| 查当前量程 | `RANG?`（空响应） | `VOLT:RANG?` / `CURR:RANG?` …按当前 FUNC 用 |
| 查当前功能 | — | `FUNC?`（这条 OK） |
| 拉一个读数 | `READ?` 在 Zero Check ON 时返回空 | 先 `SYST:ZCH OFF` 再 `READ?` |

WebUI 的快速按钮 `VOLT:RANG?` 默认按 VOLT 给。如果你切到 CURR 模式想查量程，得手输 `CURR:RANG?`。下一版完整后端会基于当前 FUNC 自动改写 `RANG?` → `<FUNC>:RANG?`。

### 5.3 实测响应（参考）

刚验证过的真机响应样本（serial=4691930，固件 A13/B01 2011-08-30）：

```
*IDN?         → KEITHLEY INSTRUMENTS INC.,MODEL 6514,4691930,A13   Aug 30 2011 15:09:19/B01  /H
FUNC?         → "VOLT:DC"
VOLT:RANG?    → 2.10
SYST:ZCH?     → 1   (ON) / 0 (OFF)
SYST:ZCH ON   → (空，正常)
SYST:ZCH OFF  → (空，正常)
READ?         → -7.334216E-06,+1.252302E+04,+0.000000E+00
              # 三段: <reading>,<timestamp>,<status_word>
              # 必须 Zero Check OFF 才有数据
```

### 5.4 推荐的"开机标准流程"

UI 上 SCPI 控制台按这个顺序点一遍可以验全链路：

1. `*IDN?` — 拿到固件标识，确认通信
2. `SYST:ZCH OFF` — 退出 Zero Check（READ? 才有数据）
3. `FUNC?` — 看当前功能
4. `VOLT:RANG?` — 看当前量程
5. `READ?` — 拉一笔读数

---

## 6. 故障排查

### 5.1 `/dev/ttyUSB0` 不存在

```bash
sudo dmesg | tail -30
```

常见症状:
- `pl2303 converter detected` → `pl2303 converter now disconnected`，反复 `reset full-speed USB device`：
  - 6514 没开机 / 处于异常状态 → 6514 前面板按 `LOCAL` 或重启
  - 线缆松动 → 拔插 USB
  - 强制重新枚举: `echo 1-8 | sudo tee /sys/bus/usb/drivers/usb/unbind && sleep 1 && echo 1-8 | sudo tee /sys/bus/usb/drivers/usb/bind`
- 完全没 `pl2303` 字样 → 驱动没加载: `sudo modprobe pl2303`

### 5.2 SCPI 控制台返回 `ERR: serial: ...`

- `serial.SerialException: device reports readiness ...` → 6514 在 LOCAL 模式，按下前面板上的 `REM` 退出，或者直接发 `*IDN?` 让仪器进入 REMOTE
- `Resource temporarily unavailable` → 已经有进程占着串口（也可能是另一个 uvicorn 实例），用 `sudo fuser /dev/ttyUSB0` 看占用 PID

### 5.3 健康端点显示 `scpi_link: simulated` 但你以为它该是真机

按顺序确认:
1. `curl http://10.24.32.98/api/health` 看 `scpi_link` 字段
2. 看 webui 服务日志里启动时 `real SCPI link unavailable on /dev/ttyUSB0 (...); falling back to simulator` 的具体原因
3. 重启服务: `bash scripts/deploy_webui.sh`

### 5.4 验证真机响应（绕过 WebUI，直接 pyserial）

```bash
ssh a203@203-precision3660 \
  '/home/a203/pickup-material-eds-webui/.venv/bin/python -c "
import serial, time
s = serial.Serial(\"/dev/ttyUSB0\", 9600, xonxoff=True, timeout=2)
s.write(b\"*IDN?\r\"); time.sleep(0.5)
print(s.read(200).decode().strip())
"'
```

期望返回（带 firmware 时间戳，不是 `-sim`）:
```
KEITHLEY INSTRUMENTS INC.,MODEL 6514,4691930,A13   Aug 30 2011 15:09:19/B01  /H
```

---

## 7. 下一步：完整真机 BenchService

当前临时桥只覆盖 SCPI 控制台。完整真机后端需要:

1. **新建 `src/pickup_eds/instruments/electrometer.py`** — 真机 BenchService
   - 把 SCPI 命令翻译为 control state 变更（双向同步）
   - 维持 `*IDN?` / `FUNC?` / `RANG?` 状态轮询
2. **新建 `src/pickup_eds/instruments/daq.py`** — USB-6002 nidaqmx 采集块
   - 替换 `simulator._generate_signal` 的合成信号
   - 落盘格式不变，用同样的 `RingBuffer`
3. **改 `src/pickup_eds/api/main.py:lifespan`** — 注入真实组合
   - `BenchService(electrometer, daq, settings)` 替换 `SimulatedBenchService`
   - 保持以下端点契约不变（前端不动）:
     - `GET /api/state`
     - `POST /api/control/{function,range,zero-check,zero-correct,scpi/send}`
     - `POST /api/recording/{start,stop}`
     - `GET /api/data/{list,preview,download}`
     - `WS /ws/{stream,state}`
4. **删除 `electrometer_serial.py` 这个临时桥** — 它的功能由完整 BenchService 承接

完成上述后，`/api/health` 应该返回 `mode: real-webui` 之类的标记。

---

## 8. 已知限制

- **没有命令缓存**：每次 SCPI 都直接打到真机，并发请求会被 `asyncio.Lock` 串行化。如果前端短时间狂点按钮，会感觉到延迟。
- **没有重连**：如果 6514 中途断开，串口对象不会自动重开。需要重启服务或用 `_maybe_open_real_scpi` 的逻辑做后台重连任务。
- **响应解析极简**：只做 `\r` 截断 + ASCII 解码，对二进制数据流（如 `READ?` 后跟 `*TRG`）不适用。
- **状态不同步**：见 §1 的关键点。
