# 02 取证与备份

> 目标：把"未知"变成"有出处的事实"，并建立唯一可回退的备份。
> 原则：**先信板子，再信固件，最后才信文档。**

## 1 取证的四个来源

| 来源 | 能拿到什么 | 可信度 |
|---|---|---|
| 原厂系统的运行时（`/sys`、`dmesg`、debugfs） | 厂端**实际怎么驱动**硬件 | L2，最硬 |
| 厂端 DTB（活 dtb 或 `boot.img` 内嵌） | 板级接线事实：总线地址、GPIO、regulator、时序 | L3 |
| 固件包与分区表 | 分区布局、镜像组成、升级方式 | L3 |
| 规格书/丝印/照片 | 料号、引脚复用、能力上限 | L4，需交叉验证 |

三者冲突时用更高一级裁决；**运行时证据能纠正 DTB 里的残留和错误**。

## 2 原厂 Android 取证

假设能拿到 root shell（串口或 `adb root`）。

### 2.1 板端事实

```sh
uname -a
cat /proc/cmdline
cat /proc/device-tree/model
cat /proc/cpuinfo
cat /proc/partitions
ls -l /dev/block/by-name/          # 不存在就找 /dev/block/platform/*/by-name/
df -h
```

### 2.2 取 DTB（两条路，互补）

```sh
# 路 A：运行中的 FDT（U-Boot 打过补丁的最终版）
cp /sys/firmware/fdt /data/local/tmp/live.dtb

# 路 B：boot 分区里的原始 DTB
dd if=/dev/block/by-name/boot of=/data/local/tmp/boot.img bs=1M
```

两条都拿，**分别反编译后逐项比对**：活 dtb 里会多出 bootloader 运行时补丁（内存、cmdline、
部分 status），原始 dtb 才是出厂接线。

### 2.3 运行时硬件快照

```sh
dmesg > /data/local/tmp/dmesg.txt
cat /sys/kernel/debug/gpio                 # 谁 claim 了哪根脚、方向、电平
cat /sys/kernel/debug/regulator/regulator_summary
ls /sys/class/mmc_host/
cat /sys/kernel/debug/mmc*/ios             # 总线宽度、时钟、时序
lsusb -t
cat /sys/class/net/*/address
getprop | grep -i -E 'hardware|model|board'   # Android
```

`/sys/kernel/debug/gpio` 是最硬的引脚证据：它显示的是**被驱动实际申请**的脚，比 DTB 里写的更可信。

### 2.4 分区与小分区

```sh
dd if=/dev/block/by-name/uboot of=/data/local/tmp/uboot.img
dd if=/dev/block/by-name/trust of=/data/local/tmp/trust.img
# misc / dtbo / vbmeta / logo / baseparameter 等按需
```

### 2.5 把文件传出来

| 通道 | 适用 | 注意 |
|---|---|---|
| 网络（`nc`/`scp`/HTTP） | 首选，量大 | 板端可能没有 `nc`，用 `toybox nc` |
| `adb pull` | 有 adb 时最方便 | 需要 `ro.adb.secure=0` 或已授权 |
| 串口 base64 | 没有网络时 | 只适合 100 KB 级（dtb），不要传 40 MiB 的 boot.img |
| U 盘 | 量大且板端支持 | 需要内核有 usb-storage |

传完**两端各算一次 sha256**，对不上就重传。

## 3 原厂 Linux 取证

命令集与 Android 基本一致，额外注意：

```sh
lsblk -o NAME,SIZE,TYPE,FSTYPE,PARTUUID
cat /etc/fstab
ls /boot
cat /boot/armbianEnv.txt 2>/dev/null || cat /boot/uEnv.txt 2>/dev/null
```

如果原厂就是 Armbian 类系统，`/boot` 里的 `armbianEnv.txt`、`boot.scr`、dtb 目录结构
就是最好的"已知良好参照物"。

## 4 备份

### 4.1 先判断需不需要全盘

| 场景 | 策略 |
|---|---|
| 有 TF 卡槽、可以拔卡回滚 | 备份系统区即可；TF 上的实验不动 eMMC |
| 只有 eMMC、要整盘重写 | **系统区前缀全备**（LBA 0 到 userdata 起点）+ userdata 里挑数据 |
| eMMC 很大、userdata 几乎空 | 不整盘读；只备系统区前缀，省时间省空间 |

**判断依据**：镜像写入范围会不会碰 userdata。如果镜像比"系统区前缀"小，就不必备份 userdata。

### 4.2 备份命令（以 rkdeveloptool 为例）

```bash
sudo rkdeveloptool ld                   # 确认 Maskrom
sudo rkdeveloptool rfi                  # 记 Sectors
sudo rkdeveloptool ppt                  # 记 userdata 的 Start LBA
# rl <BeginSec> <SectorLen> <File>：单位是 512 字节扇区，不是字节
sudo rkdeveloptool rl 0 <StartLBA> emmc-sys-<日期>.img
```

以上是官方 rockchip-linux/rkdeveloptool 的命令。部分分支改用长命令名
（`list` / `read-flash-info` / `list-partitions` / `read`），`read` 的长度可能按字节计。

GUI 工具也可，但**必须填 Start 和 Count**，否则可能得到 0 字节文件。
不同工具版本的 `read` 参数含义不同（字节数 vs 扇区数），先看 `-h`。

### 4.3 校验（比"文件存在"重要）

1. 备份镜像的 sha256；
2. 分区表原文存档（`ppt` 输出）；
3. **二次读取首 64 MiB 与末尾 1 MiB 做 `cmp`**；
4. 抽查几个小分区能否反编译/挂载。

### 4.4 元数据

`metadata.txt` 里记：日期、工具版本、loader 版本、`rfi` 原文、
`ppt` 原文、文件大小、sha256、操作人。

### 4.5 存放

大文件不进版本库；**sha256 与结论必须写进文档**，否则下次找不到底片在哪。

## 5 证据分级与记录

| 级别 | 例子 | 用法 |
|---|---|---|
| L1 | 万用表、示波器、目视画面、MDIO 寄存器 | 最终裁决 |
| L2 | `/sys`、`dmesg`、i2c 寄存器、mmc 时序 | 主要依据 |
| L3 | 厂端 dtb、镜像 config、内核源码 | 板级事实；证伪工具 |
| L4 | 规格书、wiki、社区帖 | 线索 |
| L5 | 传闻 | 只决定要不要试 |

board-profile 的每一行都要有级别和出处。**没有出处的值，默认不可信。**

## 6 常见坑

1. **`/sys/firmware/fdt` 不存在**（部分 Android）→ 走 `boot.img`。
2. **`/dev/block/by-name` 不存在** → 用 `mount`、`/proc/partitions`、`ls /dev/block/mmcblk*` 推断。
3. **活 dtb 与出厂 dtb 不一致** → 正常，差异多是 U-Boot 运行时项；做节点级 diff 分类，不要逐字节比。
4. **备份镜像的 backup GPT 不在文件里** → `sfdisk -d` 可能误报 `label: dos`，不是备份坏了。
5. **GUI 导出只读到固定大小**（有的工具到 32 MiB 就停）→ 不要用它做校验，用 CLI 或板端 `dd`。
6. **串口传大文件** → 不要。100 KB 以上的东西走网络或 U 盘。
7. **取证结束不 `sync`** → 断电后文件可能消失。
