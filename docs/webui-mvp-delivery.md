# WebUI MVP 交付说明

> 分支: `codex/webui-wt`  
> worktree: `../pickup-material-eds-webui-wt`  
> 更新日期: 2026-05-03

## 1. 这次已经落了什么

### 后端

- `FastAPI` 应用入口: `src/pickup_eds/api/main.py`
- 控制接口: `src/pickup_eds/api/control.py`
- 录制接口: `src/pickup_eds/api/recording.py`
- 数据接口: `src/pickup_eds/api/data.py`
- 实时流接口: `src/pickup_eds/api/ws.py`
- 模拟 bench service: `src/pickup_eds/instruments/simulator.py`
- Parquet + SQLite 存储: `src/pickup_eds/core/storage.py`

### 前端

- 单页入口: `src/pickup_eds/web/index.html`
- 交互逻辑: `src/pickup_eds/web/app.js`
- UI 样式: `src/pickup_eds/web/style.css`
- 6514 使用/调试教程卡片: 已内嵌在首页
- COM / SCPI 控制台卡片: 已内嵌在首页

### 部署

- 快速部署脚本: `scripts/deploy_webui.sh`
- 可选 `systemd --user` 单元: `deploy/pickup-eds-webui.service`

## 2. 当前模式

当前不是“真机版”，而是“**接口先稳定，真机后接入**”版。

这样做的目的很直接:

- 页面、REST、WebSocket、录制链路已经可跑。
- 后续只需要把 `simulator.py` 换成 `6514 + nidaqmx` service。
- 前端不会因为真实硬件接入再推倒重来。

### 关于当前文件格式

为了避免本地和远端都卡在 `pyarrow` 编译链上，这个 MVP 当前用的是:

- 波形文件: `.npz`
- 元数据目录: `SQLite`

这不影响前端和 API 契约。等 Windows VM 端固定到 Python 3.12/3.11 后，再把 `storage.py` 切回 `.parquet` 即可。

## 3. 本地运行

```bash
cd /Users/okonfu/Projects/pickup-material-eds-webui-wt
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e .
python -m uvicorn pickup_eds.api.main:app --host 0.0.0.0 --port 80
```

打开:

- `http://127.0.0.1:80`

## 4. 远端部署

默认部署到文档里提到的实验机别名:

```bash
cd /Users/okonfu/Projects/pickup-material-eds-webui-wt
bash scripts/deploy_webui.sh
```

脚本会做三件事:

1. `rsync` 代码到 `/home/a203/pickup-material-eds-webui`
2. 在远端创建 `.venv` 并 `pip install -e .`
3. 用 `nohup uvicorn ... --host 0.0.0.0 --port 80` 拉起服务

若要改目标:

```bash
bash scripts/deploy_webui.sh a203@10.24.32.98 /home/a203/pickup-material-eds-webui
```

## 5. 内网访问地址

部署成功后，预期访问地址是:

- `http://203-precision3660:80`
- 或 `http://10.24.32.98:80`

实际可达性取决于:

- 远端机器在线
- 80 端口没有被本机防火墙拦住
- 当前网络能到达实验机所在内网或 Tailscale 名称

## 6. 真机接入时按这个顺序换

1. 新建真实 `BenchService`
   目标文件建议:
   - `src/pickup_eds/instruments/electrometer.py`
   - `src/pickup_eds/instruments/daq.py`
2. 把 `src/pickup_eds/api/main.py` 里注入对象从 `SimulatedBenchService` 替换为真实实现
3. 保持以下端点不变:
   - `/api/state`
   - `/api/control/*`
   - `/api/recording/*`
   - `/api/data/*`
   - `/ws/stream`
   - `/ws/state`
4. 最后再补 `/ws/snapshot` 的真实触发逻辑

## 7. 当前 WebUI 的性能边界

这里说的是“**当前这版 WebUI 本身**”的边界，不是硬件理论上限。

- 当前默认采样率: `5000 S/s`
- 当前默认显示窗口: `8 s`
- 当前每帧推前端点数: `720`
- 当前流刷新频率: 约 `10 fps`
- 当前频谱窗口: `256` 点客户端 FFT

### 安全工作区

- `5 kS/s` 到 `20 kS/s`: 基本稳，前后端都不会明显卡
- `50 kS/s` 单通道: 后端可以承接，但前端仍然必须只看降采样后的 `<= 1000` 点
- 浏览器显示点数建议: `500` 到 `1000` 点/帧
- WebSocket 刷新建议: `10` 到 `15 fps`

### 不建议的区间

- 直接把全量 `50 kS/s` 原始点推浏览器: 会浪费带宽，也会把前端拖卡
- 单帧显示超过 `2000` 点并且高频刷新: 进入明显掉帧区
- 录制时还同时做大窗口、高分辨率前端频谱: 没必要，收益很低

### 关于“精度”

- 真正影响卡不卡的，不是 16-bit / 24-bit 这个 ADC 名义精度
- 当前前端负载主要由“每帧点数、刷新频率、是否做额外 FFT”决定
- 当前落盘是 `float32`，对波形浏览和 Phase 2 录制已经够用

### 当前建议值

- 真机接入第一版: `5 kS/s` 或 `10 kS/s`
- 稳定后再上到 `20 kS/s`
- 要试 `50 kS/s` 时，保持:
  - 前端显示点数 `<= 1000`
  - 刷新率 `<= 10 fps`
  - 录制与显示解耦，不把全分辨率直接推浏览器

## 8. 下一步最短路径

- 在 Windows VM 起好后，把 `simulator.py` 的信号生成替换为 `nidaqmx` 采样块。
- 把 `set_function` / `set_range` / `set_zero_*` 改成真实 `6514` SCPI 调用。
- 用真实采样跑一次 `Record 5s`，确认落盘文件可被 `GET /api/data/{id}/download` 取回。
