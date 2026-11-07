# scripts —— 工具索引

> 所有脚本都可以 `--help`（或 `-h`）看用法。默认**只读、幂等、不写绝对路径**。
> Python 脚本要求 3.8+，只用标准库；Shell 脚本要求 bash 4+。

## 0 先跑环境检查

```bash
bash scripts/device/env-check.sh
```

它会检查 `python3 / cpp / dtc / fget / sha256sum / losetup / xz`、串口设备与权限，
并告诉你缺什么。

## 1 工具表

| 脚本 | 作用 | 运行位置 | 依赖 |
|---|---|---|---|
| `dtb/fdt.py` | FDT 读写库（被下面三个工具 import） | 任意 | 标准库 |
| `dtb/dtb_inspect.py` | 反编译 / 节点树 / grep / 接线表 / 符号表 | 任意 | 标准库 |
| `dtb/dtb_semdiff.py` | 两份 dtb 的**语义级**差异（phandle 解析后再比） | 任意 | 标准库 |
| `dtb/dtb_edit.py` | 改 dtb：搬节点 / 改属性 / 删节点 / 补长度 | 任意 | 标准库 |
| `dtb/dts2dtb.sh` | `cpp` 展开 + `dtc -@` 编译 + 自检 | WSL/Linux | cpp、dtc、fdtget |
| `serial/serial-console.ps1` | 独占串口：收字节落盘 + 命令文件注入 | Windows | .NET SerialPort |
| `serial/capture-boot.ps1` | 纯监听抓启动日志，固定时长退出 | Windows | .NET SerialPort |
| `net/tftp_serve.py` | 只读 TFTP 服务端（RRQ only） | 任意 | 标准库 |
| `net/tftp_get.py` | TFTP 客户端 + sha256 校验 | 任意 | 标准库 |
| `net/make_payload.py` | 内核 + dtb（+ initrd）拼单文件 + 生成 U-Boot 命令 | 任意 | 标准库 |
| `device/env-check.sh` | 环境自检 | WSL/Linux | bash |
| `device/deploy-dtb.sh` | 设备端投放 dtb（备份 → 装 → 改 fdtfile → 回读 → sync） | 设备端 root | bash |
| `device/probe-boot.sh` | 冷启动后一次性采集（Markdown 报告） | 设备端 root | bash |
| `device/probe-matrix.sh` | 外设验收矩阵（PASS/FAIL/SKIP） | 设备端 root | bash |
| `image/image-set-dtb.sh` | 把 dtb 塞进镜像 boot 分区（loop 挂载） | Linux/WSL root | losetup、mount |
| `image/release-build.sh` | 打包发布四件套（img/xz/sha256/README） | Linux/WSL | xz、dd、sha256sum |

## 2 典型流程

**开发机（Windows）**

```powershell
# 看厂端 dtb
python scripts\dtb\dtb_inspect.py live.dtb --tree
python scripts\dtb\dtb_inspect.py live.dtb --dts live.dts
python scripts\dtb\dtb_inspect.py live.dtb --wiring eth

# 抓启动日志（先开脚本，再上电）
pwsh -File scripts\serial\capture-boot.ps1 -Port COM11 -Baud 1500000 -Seconds 60 -Log boot.log

# 起 TFTP，给 U-Boot 取文件
python scripts\net\tftp_serve.py --root .\tftp-root --bind 192.168.1.10
```

**WSL / Linux**

```bash
# 编 dtb
bash scripts/dtb/dts2dtb.sh board_v2.dts --kernel /root/linux --out board_v2.dtb

# 语义 diff
python3 scripts/dtb/dtb_semdiff.py board_v1.dtb board_v2.dtb --out diff.md

# 装配镜像
sudo bash scripts/image/image-set-dtb.sh armbian.img board_v2.dtb --name board_v2

# 打包
bash scripts/image/release-build.sh armbian-board.img --name board-v1
```

**设备端**

```bash
sudo bash scripts/device/deploy-dtb.sh board_v2.dtb
sudo bash scripts/device/probe-boot.sh /tmp/probe-$(date +%Y%m%d-%H%M)
sudo bash scripts/device/probe-matrix.sh --all
```

## 3 平台策略

- **Windows 是一等公民**：串口与防火墙天然是 PowerShell；其余工具用 Python（跨平台）。
- **Linux 用户**：`.ps1` 脚本没有 bash 版本。让 agent 按同样逻辑翻一份即可——
  串口可以用 `python -m serial` 或 `stty` + `cat`，逻辑很短。
- 我们没有维护双份 shell，是为了避免"两份实现不一致"这种更贵的问题。

## 4 约定

1. 默认只读；会写盘的脚本必须有 `--dry-run` 或显式确认。
2. 不写绝对路径；路径来自参数或当前目录。
3. 输出 UTF-8；Windows 控制台编码问题在脚本里处理。
4. 失败要给出"下一步查什么"，而不只是报错。
5. 脚本不内嵌凭据；需要密码时从环境变量或交互输入取。

## 5 自测

```bash
# Python 语法
python -m py_compile scripts/dtb/*.py scripts/net/*.py

# 入口
python scripts/dtb/dtb_inspect.py --help
python scripts/dtb/dtb_semdiff.py --help
python scripts/dtb/dtb_edit.py --help
python scripts/net/tftp_get.py --help

# Shell 语法
bash -n scripts/dtb/dts2dtb.sh
bash -n scripts/device/*.sh
bash -n scripts/image/*.sh
```

拿一份任意 dtb 做冒烟：

```bash
python scripts/dtb/dtb_inspect.py board.dtb --tree
python scripts/dtb/dtb_semdiff.py board.dtb board.dtb   # 应报 0 处差异、退出码 0
```
