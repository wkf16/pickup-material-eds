# 路线图与项目状态

> **当前日期**:2026-05-03
> **当前 Phase**:Phase 1 进行中(驱动 + 链路验证)
> **下一动作**:见 §"Next actions" 末尾

## 设计哲学(2026-05-03 重排)

WebUI 本身就是这个项目最重要的实验工具。**先把工具做出来,再用工具做实验**,比"先用裸脚本跑实验、然后回头改进工具"更顺序自然。所以 Phase 重新切分如下:

| Phase | 核心交付 | 一句话 |
|---|---|---|
| **0** | 项目骨架 + 文档 | 写下来才能想清楚 |
| **1** | 驱动 + 链路验证 | 让两台仪器能从 Lab Linux 说话 |
| **2** | WebUI MVP | 把仪器包成网页前端 |
| **3** | 实验执行(用 WebUI) | 跑实验 01 + 录 ML 数据集 |
| **4** | ML 训练 + 推理集成 | 把模型嵌回 WebUI |

(原 Phase 1 把"实验 01"当作主项,2026-05-03 拆开:实验文档保留在 `docs/exp-01-bandwidth-test.md`,但执行移到 Phase 3——见 `docs/decisions.md` D-11。)

---

## Phase 概览

| Phase | 目标 | 状态 | 阻塞点 |
|---|---|---|---|
| **Phase 0** | 项目骨架 + 文档基础 | ✅ 完成 | — |
| **Phase 1** | NI-DAQmx 驱动 + 端到端链路验证 | 🟡 进行中 | distrobox 容器待装 |
| **Phase 2** | WebUI MVP(实时显示 + 6514 控制 + 录制) | ⚪ 未启动 | Phase 1 |
| **Phase 3** | 用 WebUI 跑实验 01 + ML 数据集采集 | ⚪ 未启动 | Phase 2 |
| **Phase 4** | ML 训练 + 推理集成回 WebUI | ⚪ 未启动 | Phase 3 |

---

## Phase 0:项目骨架 ✅(已完成 2026-05-03)

- [x] 创建 `~/projects/pickup-material-eds/` 目录结构
- [x] `README.md` 项目概述
- [x] `.gitignore`
- [x] `docs/architecture.md` 系统架构
- [x] `docs/roadmap.md` 本文档
- [x] `docs/decisions.md` 关键决策记录
- [x] `docs/exp-01-bandwidth-test.md` 实验 01 完整方案
- [x] `scripts/{gen_chirp,capture_freqresp,analyze_bode}.py` 单文件工具
- [x] `git init` + 首次 commit(2026-05-03)

---

## Phase 1:驱动 + 端到端链路验证 🟡

**目标**:Lab Linux 上 NI-DAQmx 装好,Python 能读 USB-6002 数据,6514 能 SCPI 通信,**两路数据从硬件流到 Python 都验证一次**。这一阶段不写 WebUI,只确保"裸的仪器层 ready"。

### 1.1 网络
- [x] 装 Tailscale(用户已自行完成,见 [`memory/lab_machine.md`](../../.claude/projects/-Users-okonfu/memory/lab_machine.md))
- [x] `ssh a203@203-precision3660` 工作(off-campus 也能连)
- [ ] **关闭休眠**(让 Lab 节点 24/7 在 Tailscale 在线;`decisions.md` D-05)

### 1.2 DAQ 侧:NI-DAQmx 安装
- [ ] 在 Lab Linux 上装 distrobox + Ubuntu 24.04 容器(`decisions.md` D-04)
- [ ] 容器内装 NI-DAQmx Linux runtime
- [ ] 容器内装 `nidaqmx` Python 包 + numpy / scipy / soundfile
- [ ] 容器内 USB passthrough 验证(`lsusb` 看到 NI / `nilsdev` 列出设备)
- [ ] 跑最小 enumerate 测试:
  ```python
  import nidaqmx
  print(nidaqmx.system.System.local().devices)
  # 应该能看到 USB-6002 / Dev1
  ```

### 1.3 DAQ 侧:性能边界实测
- [ ] **Smoke test 1**:1 秒满速 50 kS/s 单通道采集,看读出 50000 个点,无异常
- [ ] **Smoke test 2**:60 秒**连续**流采,主机缓冲 200 ms,**统计有无 buffer overrun**
- [ ] **Smoke test 3**:差分模式 vs 单端模式,环境噪声差距记录
- [ ] **Smoke test 4**(可选):AO 单通道 5 kS/s 输出 1 kHz 正弦,环回到 AI 验证
- [ ] 数据落盘到 `data/phase1_smoketests/`,FFT 看一眼

### 1.4 6514 侧:验证已通的链路依然通
- [x] RS-232 物理接线(已验证,IDN 拿到 S/N 4691930)
- [x] 用 `scripts/capture_freqresp.py` 配置 + 一次有限采集(在 Mac 端验证过命令)
- [ ] 在 Lab Linux 上重跑同样脚本(确认 ttyUSB0 + nidaqmx 配合)
- [ ] 对照表:V/I/R/Q 四个模式各发 SCPI 切换 + 验证 `FUNC?` 回读

### 1.5 端到端验证
- [ ] 接一个简单信号源(电池 + 分压器,~100 mV DC)到 6514 输入
- [ ] 6514 V 模式 2V 量程 → 2V AO → USB-6002 → Python
- [ ] 看到稳定 100 mV ± 噪声,符合预期
- [ ] **如果到这一步通过了:Phase 1 完成**

---

## Phase 2:WebUI MVP ⚪

**目标**:在 Lab Linux 上部署一个最小可用 Web 实验台。把 Phase 1 验证过的能力**包成 HTTP/WebSocket 接口**,加一个浏览器端可见的界面。

### 2.1 后端核心(`src/pickup_eds/`)
- [ ] `instruments/electrometer.py` ── 6514 SCPI 异步包装(基于 `pyserial-asyncio`)
- [ ] `instruments/daq.py` ── USB-6002 nidaqmx 流采包装(后台 task,推 ring buffer)
- [ ] `core/scope.py` ── 触发逻辑 + 显示降采样(50 kS/s → ~1 kS/s 给浏览器)
- [ ] `core/recorder.py` ── 录制状态机(start/stop/label/duration)
- [ ] `core/storage.py` ── Parquet 落盘 + SQLite 元数据
- [ ] `api/main.py` ── FastAPI app + lifespan 管理硬件单例
- [ ] `api/ws.py` ── WebSocket `/ws/stream`、`/ws/state`
- [ ] `api/control.py` ── REST `/api/control/{function,range,zero-check,zero-correct}`
- [ ] `api/recording.py` ── REST `/api/recording/{start,stop}`
- [ ] `api/data.py` ── REST `/api/data/{list,download,preview}`

### 2.2 前端单页(`src/pickup_eds/web/`)
- [ ] `index.html` ── 三栏布局:控制 / 时域波形 / FFT 频谱
- [ ] `scope.js` ── uPlot 实时绘图,WebSocket 客户端
- [ ] `controls.js` ── Alpine.js 仪器控制 + 录制按钮
- [ ] `style.css` ── 极简样式

### 2.3 部署最小化
- [ ] `pyproject.toml` ── 列依赖
- [ ] `uvicorn` 命令直接起服务,bind 0.0.0.0:8000
- [ ] (Tailscale 已就位,内网+外网都能访问)

### 2.4 验证(就用这套测的 Step 0 当 Phase 2 验收)
- [ ] 浏览器打开 `http://203-precision3660:8000`,见实时波形跳动
- [ ] 点 "Function = VOLT, Range = 2V" → 6514 真的切了
- [ ] 点 "Record 5s, label = baseline" → 磁盘出现 `data/recordings/baseline_<ts>.parquet`
- [ ] WebSocket 拉断重连不崩
- [ ] 后端单进程 RAM < 200 MB,CPU < 30% 持续

---

## Phase 3:用 WebUI 跑实验 + 录数据集 ⚪

**目标**:把 `docs/exp-01-bandwidth-test.md` 里描述的实验,**通过 Phase 2 的 WebUI 完成**——并以此为契机录一份正式的 ML 数据集。

### 3.1 实验 01:材料带宽测试(详见 `docs/exp-01-bandwidth-test.md`)
- [ ] 凑物料:喇叭、双面胶、铜箔、夹具、BNC 线
- [ ] Step 0:噪声基线(用 WebUI 录,标签 `baseline_short`)
- [ ] Step 1:1 kHz 单音 go/no-go
- [ ] Step 2:扫频 Bode(机械直驱,贴喇叭)
- [ ] Step 3:扫频 Bode(空气耦合,悬空)
- [ ] Step 4:语音段录制(可选)
- [ ] 在 jupyter 里出 Bode 图 + 写 `docs/exp-01-results.md`

### 3.2 ML 数据集录制(基于实验 01 结论决定方案)
- [ ] 任务定义:几类、什么类、单类样本数(待 Q-02/Q-03 确认)
- [ ] WebUI 加 "批量录制" 模式:循环 N 次,每次提示用户,自动落盘
- [ ] 录第一批训练集
- [ ] 录测试集

### 3.3 打磨 / 部署
- [ ] 触发模式(单次/连续/边沿)
- [ ] 实时频谱面板
- [ ] 历史数据回放界面
- [ ] ttyd 终端嵌入
- [ ] systemd 服务 + reboot 自启
- [ ] HTTP Basic Auth(若开放给师兄/导师)

---

## Phase 4:ML 训练 + 推理集成 ⚪

- [ ] jupyter 里训练 ResNet-SE(用 Phase 3 数据集)
- [ ] 模型导出 ONNX 或 TorchScript
- [ ] 后端 `/api/inference/predict` 端点,加载模型 + 实时分类
- [ ] 前端显示当前预测类别 + 置信度
- [ ] 简单 demo(对着传感器说话 → 屏幕显示识别结果)

---

# 横切问题清单(跨 Phase 的开放问题)

| 编号 | 问题 | 状态 |
|---|---|---|
| Q-01 | 这个材料是空气麦还是接触式振动?(影响后续设计) | 等 Phase 3 实验 01 |
| Q-02 | ML 任务是 silent speech 短语分类还是别的? | 待用户与导师确认 |
| Q-03 | 录数据时类别集合多大?(5 类 vs 18 类) | 同上 |
| Q-04 | 6514 模拟输出实际带宽? | 等 Phase 3 Bode 实验 |
| Q-05 | 是否要加自制简化前级(INA128 板)做 A/B 验证? | Phase 4 之后,可选副线 |

---

# Next actions(按优先级排序)

1. **关 Lab Linux 休眠** ── 让 Tailscale 节点稳定在线(`decisions.md` D-05)
2. **装 distrobox + Ubuntu 24.04 容器**
3. **容器内装 NI-DAQmx + nidaqmx Python**
4. **跑 Phase 1.3 四个 smoke test**,记录性能边界
5. **写 Phase 2 后端骨架**(`instruments/daq.py` + `instruments/electrometer.py` 优先)
6. **写 Phase 2 WebSocket + uPlot 前端原型**(端到端跑通最重要,UI 后面再美化)
7. **Phase 3:用 WebUI 跑实验 01,凑物料并执行**

---

# 决策日志参见 `decisions.md`,实验细节参见各 `exp-*.md`
