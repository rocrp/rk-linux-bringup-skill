# 04 引导与点亮

> 目标：在**不写目标存储**的前提下，让主线内核在板子上跑起来，并建立一条快速迭代 dtb 的回路。

## 1 启动链

```
BootROM → DDR 初始化 → BL31（ATF）→ U-Boot → 内核 → initramfs → rootfs
```

每一段都有特征输出，记下来，后面判断"卡在哪"全靠它：

| 段 | 典型输出 | 卡住的含义 |
|---|---|---|
| BootROM/DDR | DDR 版本串、频率、容量 | DDR 参数/供电问题，通常要换 loader |
| BL31 | `BL31: v...` | 电源域/复位；先试断电冷启动 |
| U-Boot | `U-Boot 20xx.xx`、`Model:` | bootloader 与板不匹配 |
| 内核 | `Booting Linux`、`Machine model:` | dtb 的串口/时钟/内存写错 |
| initramfs | `(initramfs)` 提示符 | rootfs 没挂上 |
| rootfs | `login:` | 成功 |

**关键判据**：`Machine model` 必须等于你自己 dts 里写的 `model`。不等就说明跑的不是你的 dtb。

## 2 三条零写入路线

按板子条件选，优先级从上到下：

### 2.1 TF 卡（有卡槽时首选）

- 把镜像写到 TF 卡，卡启动、eMMC 保持原样。
- 回滚 = 拔卡。
- 迭代 dtb：改卡上 `/boot/dtb/...` + 改 `armbianEnv.txt` 的 `fdtfile` + 重启。

### 2.2 TFTP 内存直启（没有卡槽、但有网口和可打断的 U-Boot）

- 内核、dtb、initramfs 全放内存，**目标存储一个字节都不写**。
- 每改一版 dtb 只重传几十 KB，迭代快。
- 需要：厂端 U-Boot 带 `tftp`/`booti`、开发机能起 TFTP 服务、板与开发机同网段。

典型命令（以现场 `help` 为准）：

```
setenv ipaddr 192.168.1.50
setenv serverip 192.168.1.10
ping ${serverip}
tftp ${kernel_addr_r} Image
tftp ${fdt_addr_r} board_v1.dtb
tftp ${ramdisk_addr_r} initramfs.cpio.gz
setenv bootargs console=ttyS2,1500000 earlycon=uart8250,mmio32,0xfe660000 rdinit=/bin/sh
# booti <kernel> [<initrd>[:<size>]] [<fdt>]；filesize 是上一条 tftp（initramfs）的大小
booti ${kernel_addr_r} ${ramdisk_addr_r}:${filesize} ${fdt_addr_r}
```

坑：

- 三个加载地址之间的间隔必须大于各自文件大小，否则 initramfs 会踩到 dtb。
- 有的 U-Boot 收裸 initrd 会失败，需要 `initrd:size` 语法或把 initrd 转成它认识的格式。
- 有的 U-Boot 每次上电只允许**一次**网络传输，下完一个文件后网络命令全部静默
  → 把内核 + dtb（+ initramfs）拼成**单个文件**，一次取走。`scripts/net/make_payload.py` 做这件事。
- initramfs 必须最后一个 tftp，`${filesize}` 才是它的大小；不用 initrd 时写 `booti <kernel> - <fdt>`。先 `help booti`。

### 2.3 USB rootfs（需要完整用户态、又不想写 eMMC）

- 把 Armbian rootfs 写到 U 盘，TFTP 引导内核 + `root=UUID=...` 指向 U 盘。
- 适合要测 HDMI/音频/WiFi 这类需要用户态的项。
- 性能差，只作过渡；USB 存储要先在 P4 验过。

### 2.4 串口 base64（没有网络时的最后手段）

- 把 100 KB 级的 dtb 用 base64 从串口灌进去。
- 慢，但可靠；40 MiB 的镜像不要走这条路。

## 3 选择树

```
有 TF 卡槽？
├─ 是 → TF 卡启动（最省事，拔卡即回滚）
└─ 否 → U-Boot 能打断、有网口？
        ├─ 是 → TFTP 内存直启
        └─ 否 → 能进 MaskROM 且有备份？
                ├─ 是 → 直接写 eMMC（唯一不可回退，谨慎）
                └─ 否 → 先解决观测与退路，不要继续
```

## 4 底料镜像怎么选

1. **先定内核版本门槛**：外设需要的最低内核版本（WiFi 芯片、显示、音频驱动）。
2. **再选最像的机型**：同 SoC、同存储、同显示接口、同网口。
3. 确认 `/boot` 布局：`dtb/<soc>/*.dtb` + `armbianEnv.txt` 的 `fdtfile=` 机制在。
4. 记录身份：文件名、发布日期、sha256、内核版本、机型。

**能不自编内核就不自编**：先查底料内核的 config，若所需驱动都是 `=y`，直接用它自带的
`Image` + `uInitrd`，只编 dtb。好处是 P3 与 P5 用同一个内核二进制，P3 的 probe 结论可以迁移。

## 5 首版 dtb 的最小集

只开：

- 调试串口（`status = "okay"` + `chosen/stdout-path`）
- 电源（PMIC/regulator）
- 存储（eMMC/SD）
- 网口（如果要用 TFTP/SSH）
- USB（如果要用 U 盘/键鼠）

**其他全部 disabled**。失败面越小越好；每加一类都要能解释"为什么现在加"。

## 6 验收阶梯 L1~L4

| 级别 | 现象 | 意义 |
|---|---|---|
| **L1** | 传输/加载成功（TFTP 取到文件、卡能读） | 介质与引导环境成立 |
| **L2** | 串口出现主线内核 banner，`Machine model` = 自己写的 `model` | 内核 + DTB 基本正确 |
| **L3** | `dmesg` 里 PMIC/存储/网口 probe 成功 | 核心外设被正确识别 |
| **L4** | initramfs shell 里 `ip link`、`/proc/device-tree/model`、`ls /sys/class/drm` 符合预期 | 可进 P4 迭代 |

每级都留：串口原始日志 + dtb sha256 + 内核 `uname -r`。

## 7 失败分流

| 现象 | 最可能原因 | 动作 |
|---|---|---|
| 卡在 `Starting kernel` 后无输出 | dtb 的串口/时钟写错，或 `console=` 不符 | 换回厂端 DTB 同法启动一次作对照 |
| U-Boot 就超时 | 网口不在 U-Boot 的 dts 里 / IP 冲突 / 防火墙 | 先 `ping`；换 U 盘；核对 `serverip` |
| 内核起来但存储/网口没有 | 驱动没编进去，或 dtb 节点/供电/时钟错 | 先核 config，再逐项对厂端 dtb |
| 完全无输出 | 串口线/波特率/针序 | 回观测通道，别先怀疑内核 |
| 起来但挂不上 rootfs | `root=` 写法与 initramfs 状态不匹配 | 见 `07-image.md` 的 rootfs 分流 |

**连续 3 次（≥2 个内核/≥2 种介质）仍停在 L1/L2 → 转 C 入口**，不要无限换 dtb。

## 8 迭代纪律

- 每版 dtb 记 sha256、大小、`__symbols__` 数。
- 每轮只改一类外设；改动写进变更说明。
- 投放后**回读**确认版本真的换了（`/proc/device-tree/model` 或 dtb sha256）。
- 保留上一版可启动的 dtb，随时能退。
