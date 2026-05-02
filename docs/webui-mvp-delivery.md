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
python -m uvicorn pickup_eds.api.main:app --host 0.0.0.0 --port 8000
```

打开:

- `http://127.0.0.1:8000`

## 4. 远端部署

默认部署到文档里提到的实验机别名:

```bash
cd /Users/okonfu/Projects/pickup-material-eds-webui-wt
bash scripts/deploy_webui.sh
```

脚本会做三件事:

1. `rsync` 代码到 `/home/a203/pickup-material-eds-webui`
2. 在远端创建 `.venv` 并 `pip install -e .`
3. 用 `nohup uvicorn ... --host 0.0.0.0 --port 8000` 拉起服务

若要改目标:

```bash
bash scripts/deploy_webui.sh a203@10.24.32.98 /home/a203/pickup-material-eds-webui
```

## 5. 内网访问地址

部署成功后，预期访问地址是:

- `http://203-precision3660:8000`
- 或 `http://10.24.32.98:8000`

实际可达性取决于:

- 远端机器在线
- 8000 端口没有被本机防火墙拦住
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

## 7. 下一步最短路径

- 在 Windows VM 起好后，把 `simulator.py` 的信号生成替换为 `nidaqmx` 采样块。
- 把 `set_function` / `set_range` / `set_zero_*` 改成真实 `6514` SCPI 调用。
- 用真实采样跑一次 `Record 5s`，确认落盘文件可被 `GET /api/data/{id}/download` 取回。
