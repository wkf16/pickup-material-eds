# 路线图与项目状态

> **当前日期**:2026-05-02
> **当前 Phase**:Phase 1 进行中(实验骨架 + 实验 01 设计已完成,实测未开)
> **下一动作**:见 §"Next actions" 末尾

## Phase 概览

| Phase | 目标 | 状态 | 阻塞点 |
|---|---|---|---|
| **Phase 0** | 项目骨架 + 文档基础 | ✅ 完成 | — |
| **Phase 1** | 实验 01(带宽测试)+ 单文件采集脚本 | 🟡 设计完成,实测未开 | NI-DAQmx 驱动未装 |
| **Phase 2** | Web 后端 MVP(实时显示 + 6514 控制 + 录制) | ⚪ 未启动 | Phase 1 数据 |
| **Phase 3** | Web 前端打磨 + 实验流程化 + 部署 | ⚪ 未启动 | Phase 2 |
| **Phase 4** | 推理在线集成 + 多类批量录制 | ⚪ 未启动 | Phase 3 + ML 模型 |

---

## Phase 0:项目骨架 ✅(已完成 2026-05-02)

- [x] 创建 `~/projects/pickup-material-eds/` 目录结构
- [x] `README.md` 项目概述
- [x] `.gitignore`
- [x] `docs/architecture.md` 系统架构
- [x] `docs/roadmap.md` 本文档
- [x] `docs/decisions.md` 关键决策记录
- [x] `docs/exp-01-bandwidth-test.md` 实验 01 完整方案
- [x] `scripts/{gen_chirp,capture_freqresp,analyze_bode}.py` 单文件工具
- [ ] `git init` + 首次 commit ← **待办**

## Phase 1:实验 01 — 测 SLTS 材料带宽 🟡

**目标**:量化材料的实际频响,决定后续路径(空气麦?语音分类?接触式振动?)

### 软件准备
- [x] 实验 01 文档(`docs/exp-01-bandwidth-test.md`)
- [x] 三个独立脚本就绪
- [ ] **NI-DAQmx 驱动安装到 Lab Linux** ← **关键阻塞**
  - 推荐路径:distrobox + Ubuntu 24.04 容器(详见 `docs/decisions.md` D-04)
  - 备选:AUR `ni-visa` + 手动 daqmx
- [ ] `nidaqmx` Python 包能 import
- [ ] `python3 -c "import nidaqmx; print(nidaqmx.system.System.local().devices)"` 列出 USB-6002

### 网络
- [ ] **Tailscale 在 Lab Linux 上装好并加入网络**(`docs/decisions.md` D-01)
- [ ] 用 `ssh a203@203-precision3660` 替代 IP 直连
- [ ] 关闭机器休眠(`docs/decisions.md` D-05)

### 硬件物料
- [ ] 3 寸全频喇叭 + 5W 功放(实验室借/拆机)
- [ ] 0.05-0.1 mm 薄双面胶
- [ ] 带导电胶的铜箔胶带
- [ ] 晾衣夹
- [ ] BNC-BNC 同轴线 1 根
- [ ] 鳄鱼夹引线 2 根

### 实验执行
- [ ] Step 0:噪声基线
- [ ] Step 1:1 kHz 单音 go/no-go
- [ ] Step 2:扫频 Bode(机械直驱,贴喇叭)
- [ ] Step 3:扫频 Bode(空气耦合,悬空)
- [ ] Step 4:语音段录制(可选)
- [ ] 出 Bode 图 + 决策(走哪条后续)

### 产出
- [ ] `data/exp01/*.npy` 实验数据
- [ ] `docs/exp-01-results.md` 结论 + 下一步建议

---

## Phase 2:Web 后端 MVP ⚪

**目标**:在 Lab Linux 上部署一个最小可用 Web 实验台,能实时看波形 + 控制 6514 + 录制带类别数据。

### 后端
- [ ] `src/pickup_eds/instruments/electrometer.py` ── 6514 SCPI 异步包装
- [ ] `src/pickup_eds/instruments/daq.py` ── USB-6002 流采包装
- [ ] `src/pickup_eds/core/scope.py` ── 触发逻辑 + 显示降采样
- [ ] `src/pickup_eds/core/recorder.py` ── 录制状态机
- [ ] `src/pickup_eds/core/storage.py` ── Parquet 落盘 + SQLite 元数据
- [ ] `src/pickup_eds/api/main.py` ── FastAPI app
- [ ] `src/pickup_eds/api/ws.py` ── WebSocket 推流
- [ ] `src/pickup_eds/api/{control,recording,data}.py` ── REST 端点

### 前端
- [ ] `web/index.html` ── 单页应用骨架
- [ ] `web/scope.js` ── uPlot 实时绘图
- [ ] `web/controls.js` ── Alpine.js 控制 UI

### 验证
- [ ] 浏览器开 `http://203-precision3660:8000`,看见实时波形跳动
- [ ] 点 "Range 2V" → 6514 真的切档
- [ ] 点 "Record 5s, label=B12" → 磁盘出现 `data/recordings/B12_<ts>.parquet`

---

## Phase 3:打磨 + 部署 ⚪

- [ ] 触发模式(单次/连续/边沿)
- [ ] 实时频谱面板
- [ ] 历史数据回放
- [ ] 批量录制(N 类 × M 次循环)
- [ ] ttyd 终端嵌入
- [ ] systemd 服务 + reboot 自启
- [ ] HTTP Basic Auth
- [ ] 移动端响应式 CSS

---

## Phase 4:推理集成 ⚪

- [ ] 训练 ResNet-SE 模型(在 Phase 1+2 录的数据上)
- [ ] 模型导出 ONNX
- [ ] 后端加载模型 + 实时推理 endpoint
- [ ] 前端显示当前预测类别

---

# 横切问题清单(跨 Phase 的开放问题)

| 编号 | 问题 | 状态 |
|---|---|---|
| Q-01 | 这个材料是空气麦还是接触式振动?(影响 Phase 4 设计) | 等 Phase 1 实验 |
| Q-02 | ML 任务是 silent speech 短语分类还是别的? | 待用户与导师确认 |
| Q-03 | 录数据时类别集合多大?(5 类 vs 18 类) | 同上 |
| Q-04 | 6514 模拟输出实际带宽? | 等 Phase 1 Bode 实验 |
| Q-05 | 是否要加自制简化前级(INA128 板)做 A/B 验证? | Phase 2 之后 |

---

# Next actions(按优先级排序,不带时间承诺)

1. **完成 Phase 0**:`git init` + 首次 commit
2. **解决网络**:Lab Linux 装 Tailscale → Mac 端连接 → 用 hostname 替代 IP
3. **解决 DAQ 驱动**:distrobox 走 Ubuntu 容器,装 NI-DAQmx
4. **跑实验 01 Step 0**:噪声基线(不需要喇叭,先验证整条链路工作)
5. **凑物料**:喇叭、双面胶、铜箔
6. **跑实验 01 Step 1-3**:得到 Bode 图,做决策
7. **写 Phase 2 MVP**:从 `daq.py` + `electrometer.py` 起步,先把数据流跑通到浏览器

---

# 决策日志参见 `decisions.md`,实验细节参见各 `exp-*.md`
