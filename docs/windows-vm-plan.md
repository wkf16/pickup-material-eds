# Windows VM 方案

> **状态**:已采用  
> **更新日期**:2026-05-03（VM 已创建，等待 Windows 安装）

## 1. 结论

Phase 1 不再走 `distrobox + Ubuntu 24.04 + NI-DAQmx Linux`。新的执行路径是:

- `Manjaro` 只当 **KVM/libvirt 宿主机**
- `Windows VM` 负责 **USB-6002 + 6514 USB-Serial** 的驱动和应用
- `capture_freqresp.py`、后续 `FastAPI` 后端都运行在 Windows VM 里

这条路线是为了避开 USB-6002 在 Linux 上的实际支持/驱动风险。决策依据见 `docs/decisions.md` 的 `D-12`。

## 2. 选哪个 Windows

### 选择

**Windows 10 Enterprise LTSC 2021 x64**

### 为什么是它

- `NI-DAQmx` 官方主支持面向 Windows,而不是 USB DAQ on Linux
- 比 Windows 11 更轻,对实验机更克制
- LTSC 本身就是为**少变更、长期运行、专用设备**场景准备的

### 说明

“**最轻且支持**”这里是一个**工程判断**:

- “支持”来自 NI 官方 `NI-DAQmx and Microsoft Windows Compatibility`
- “更轻”来自 Microsoft 对 LTSC 的定位:长期服务、面向专用设备、少 feature churn

如果后续发现某个 `NI-DAQmx` 版本对 LTSC 有专门限制,则降级到 **Windows 10 22H2 x64 Pro/Enterprise**。

## 3. 宿主机当前状态(2026-05-03 实测)

### 已完成

- `KVM` 硬件虚拟化: `PASS`
- `/dev/kvm` 可访问: `PASS`
- `qemu-desktop`, `libvirt`, `virt-install`, `edk2-ovmf`, `swtpm` 已安装
- `libvirtd` 已启动并设为开机自启
- `libvirt default` NAT 网络已启动并设为自启（需用 `sudo virsh`，见注 1）
- USB 设备已识别:
  - `3923:76c4` (`usb_1_9`) = `NI USB-6002`
  - `067b:23a3` (`usb_1_8`) = `6514` 对应的 USB-Serial
- 休眠/挂起全部 mask（`sleep`, `suspend`, `hibernate`, `hybrid-sleep`）
- **ISO 传输完成**:`/var/lib/libvirt/images/en-us_windows_10_enterprise_ltsc_2021_x64_dvd_d289cf96.iso`
- **VM 已创建并启动**:`pickup-win10-ltsc`，SPICE on `localhost:5900`

> 注 1：`virsh net-list --all` 不带 sudo 看不到网络（连到 `qemu:///session`），
> 要用 `sudo virsh net-list --all` 或 `virsh --connect qemu:///system net-list --all`。

### 仍待做

- **连接 SPICE 控制台，完成 Windows 安装**（见 §9）
- 在 VM 内装 `NI-DAQmx + Python`

## 4. ISO 获取策略（已完成）

以后**大文件一律本地下好再传远端**。

已执行流程（2026-05-03）:

1. 本机下载：`~/Downloads/en-us_windows_10_enterprise_ltsc_2021_x64_dvd_d289cf96.iso`
2. rsync 传到宿主机（`rsync --progress -h <iso> lab4070:/home/a203/isos/`）
3. 再移到 `/var/lib/libvirt/images/`（避免 libvirt-qemu 用户权限问题）

> **注意**：ISO 必须放在 `/var/lib/libvirt/images/` 或 `libvirt-qemu` 可读的目录，
> 否则 QEMU 进程会报 `Permission denied`。`/home/a203` 对 `libvirt-qemu` 不可见。

3. 在实验机上用该 ISO 创建 VM

## 5. VM 创建参数

### 推荐规格

- vCPU: `4`
- RAM: `8 GiB`
- Disk: `80 GiB qcow2`
- Firmware: `UEFI`
- TPM: `2.0`
- Network: libvirt `default`
- USB passthrough:
  - `3923:76c4` (`USB-6002`)
  - `067b:23a3` (`6514 USB-Serial`)

### 辅助脚本

仓库内提供:

```bash
scripts/create_windows_vm.sh
```

示例:

```bash
bash scripts/create_windows_vm.sh \
  --name pickup-win10-ltsc \
  --iso /home/a203/isos/Win10_LTSC_2021_x64.iso
```

## 6. VM 内安装目标

Windows VM 起来后,按这个顺序做:

1. 安装 `NI-DAQmx`
2. 在 NI MAX 或 Python 里确认 `USB-6002` 被枚举
3. 安装 Python 3.12
4. 安装依赖:

```powershell
py -m pip install pyserial nidaqmx numpy scipy soundfile matplotlib
```

5. 运行最小枚举:

```python
import nidaqmx
print(nidaqmx.system.System.local().devices)
```

6. 再运行 `scripts/capture_freqresp.py`

## 7. Phase 1 验收标准

- `6514` 在 Windows VM 内 `*IDN?` 正常
- `USB-6002` 在 `nidaqmx.system.System.local().devices` 里出现
- 1 秒 `50 kS/s` 单通道采集成功
- 60 秒连续流采无 overrun
- `6514 2V AO -> USB-6002` 的端到端链路跑通

## 8. 备注

- 若后续要把 WebUI 部署在 Linux 宿主机,可以再评估 guest-host IPC
- 但最简单的 Phase 2 路线,仍然是**Web 后端直接跑在 Windows VM 里**

## 9. 连接 SPICE 控制台（Windows 安装用）

VM 已在运行，SPICE 显示器绑定在宿主机 `localhost:5900`。

### 方法 A：SSH 隧道 + remote-viewer（推荐，Mac/Linux 通用）

本机执行:

```bash
ssh -L 5900:localhost:5900 lab4070 -N &
remote-viewer spice://localhost:5900
# 或
open -a "Virt Viewer" spice://localhost:5900
```

若没有 `remote-viewer`，Mac 上安装：`brew install virt-viewer`

### 方法 B：virt-manager（宿主机 X11 forward）

```bash
ssh -X lab4070 virt-manager
```

### VM 管理常用命令

```bash
# 查 VM 状态
sudo virsh list --all

# 重启 VM
sudo virsh reboot pickup-win10-ltsc

# 强关
sudo virsh destroy pickup-win10-ltsc

# 查 SPICE 端口
sudo virsh domdisplay pickup-win10-ltsc

# 查 VM 获取的 NAT IP（Windows 装好后）
sudo virsh domifaddr pickup-win10-ltsc
```

## 10. VM 重启后的恢复步骤（每次都要做）

**症状**：VM 重启后 USB 设备在 Windows 里显示 `Status: Unknown, Present: False`（phantom），就算宿主端 `lsusb` 仍然看到。NI services 也部分没起来，`nidaqmx.system.System.local().devices.device_names` 返回空。

**原因（猜测）**：qemu-xhci + Windows USB stack 在重启时丢状态；NI 启动顺序里 `nidevldu`（PnP→MAX 桥梁）有时不自启。

**恢复步骤**（lab4070 上执行，假设 VM IP = 192.168.122.8，凭据 Admin/Lab2026!）：

```bash
# 1) USB 重新接到 VM 上（PL2303 + USB-6002）
echo 203 | sudo -S virsh detach-device pickup-win10-ltsc /tmp/usb_pl.xml --live
sleep 2
echo 203 | sudo -S virsh attach-device pickup-win10-ltsc /tmp/usb_pl.xml --live
echo 203 | sudo -S virsh detach-device pickup-win10-ltsc /tmp/usb_ni.xml --live
sleep 2
echo 203 | sudo -S virsh attach-device pickup-win10-ltsc /tmp/usb_ni.xml --live

# 2) 通过 WinRM 起 NI 服务（用 /home/a203/winrm-venv 里的 pywinrm，NTLM auth）
# /tmp/usb_pl.xml 内容：vendor 0x067b / product 0x23a3
# /tmp/usb_ni.xml 内容：vendor 0x3923 / product 0x76c4
```

**Windows 端 PowerShell（通过 WinRM 跑）**：
```powershell
$svcs = 'niauth','niSvcLoc','NIDomainService','mxssvr','nimDNSResponder',
        'nisds','NITaggerService','niroco','NINetworkDiscovery','nipxicmsvc','nidevldu'
foreach ($s in $svcs) { Start-Service $s -ErrorAction SilentlyContinue }
```

**如果 `nipalk` 服务不存在或不能启动**（这种情况下 USB-6002 firmware 上传不了，会停在 `3923:76f9` USB Firmware Updater 模式而不是 `3923:76c4` 工作模式）：
```powershell
# 这个 MSI 是从 ni-pal_25.5.0.49270-0+f118_windows_x64.nipkg 里 unpack 出来的
msiexec /i "C:\setup\nipal_pkg\data\palSetup64.msi" /quiet REINSTALL=ALL REINSTALLMODE=vomus /log C:\setup\palSetup64.log
# 然后重启 VM
```

**验证**：
```python
# Python 3.12 in Windows VM
import nidaqmx, serial
print(list(nidaqmx.system.System.local().devices.device_names))  # 应该 ['Dev1']
with serial.Serial('COM3', 9600, timeout=2) as p:
    p.write(b'*IDN?\r\n'); import time; time.sleep(0.4)
    print(p.read(p.in_waiting).decode())  # KEITHLEY ...,MODEL 6514,4691930,...
```

**TODO**：把这套恢复脚本封装成 systemd unit（lab）+ Windows scheduled task at logon（VM），让重启自动恢复。

