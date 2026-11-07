# 06 外设点亮手册

> 顺序按**依赖链**排，不按功能清单：前一项错了，后一项没有意义。
>
> ```
> 电源/PMIC → 存储 → 调试串口 → 网络 → USB → 显示 → 无线/音频/RTC/按键/LED
> ```

**通用纪律**：一次只开一类；每类都写"节点从哪来 / 关键属性 / 怎么验 / 常见坑"；
验收判据绑物理量或数据通路，不绑"设备节点存在"。

## 1 电源 / PMIC / regulator

**为什么最先**：没有电源，后面全不 probe；电源写错还可能伤硬件。

**节点从哪来**：厂端 dtb 的 PMIC 节点（i2c 总线号、地址、中断脚、regulator 列表）；
同 SoC 公版 dts 的 regulator 段做写法参考。

**关键属性**

- PMIC 挂在哪条 i2c、地址多少、中断脚是哪个 GPIO（极性与触发方式）；
- 每一路 regulator 的 `regulator-min/max-microvolt`、`regulator-always-on`、`vin-supply`；
- 电源使能脚（`*-gpios`、`enable-gpios`）的 bank/引脚/极性；
- `system-power-controller`（老写法 `rockchip,system-power-controller` 已废弃）。

**怎么验**

```sh
dmesg | grep -iE 'rk80[89]|regulator'
cat /sys/class/regulator/*/name
cat /sys/kernel/debug/regulator/regulator_summary
cat /sys/kernel/debug/gpio
```

判据：所有 regulator 注册成功、关键轨电压正确、没有 deferred probe。

**常见坑**

- 照抄参考板的 i2c 总线号/中断脚 → PMIC 不 probe 或整片 LDO 不注册。
- 没用的控制器没关，它的默认 pinmux 抢走了 PMIC 中断脚 → 一条一条开，不用的先 `disabled`。
- 电源使能脚极性写反 → 口子没电，甚至短路。
- **红线**：涉及电源使能/复位的改动，必须人肉复核后再投放。

## 2 存储（eMMC / SD）

**节点从哪来**：厂端 dtb 的 `sdhci` / `sdmmc` / `sdmmc1` 节点；`dmesg` 里的总线宽度与时序。

**关键属性**

- `bus-width`（4/8）、`max-frequency`、`non-removable`（eMMC）；
- pinctrl（`emmc_bus8`、`emmc_datastrobe` 等）；
- `vmmc-supply` / `vqmmc-supply`；
- SD：`cd-gpios` 或 `broken-cd`（**二选一**）、`no-1-8-v`（板子只有 3.3 V 时）。

**怎么验**

```sh
lsblk
dmesg | grep -iE 'mmc|sdhci'
dd if=/dev/mmcblkX of=/dev/null bs=1M count=1024
```

判据：认盘、容量对、顺序读无 I/O error、无 CRC/timeout。

**常见坑**

- 声明了板子做不到的速率/电压：固定 3.0 V 的 `vqmmc` 却写 `sd-uhs-sdr104` → CMD11 超时或无块设备。
- 卡检测两个都开（控制器 CDETECT + `cd-gpios`）→ 整卡不识别。
- eMMC 没有分区表被当成驱动故障：先读 LBA0 与磁盘末尾，可能本来就是 Rockchip 私有布局。
- 写操作留到 P5；P3/P4 只读。

## 3 调试串口

**节点从哪来**：厂端 `dmesg` 的 `ttyS*`/`ttyFIQ*` 与 dtb 的 uart 节点；`chosen/stdout-path`。

**关键属性**

- `&uartX { status = "okay"; }`；
- `chosen { stdout-path = "serialX:<baud>n8"; }`；
- `earlycon=uart8250,mmio32,<base>[,<baud>,<clock>]` 放 bootargs，不进 dts。

**怎么验**：`login:` 出现、能登录、`cat /proc/device-tree/model` 正确。

**常见坑**

- `console=` 有多个时，**最后一个**才决定 `/dev/console`；顺序写反就没有输出。
- `loglevel=1` 只放行紧急消息，看起来像"内核没起来"。
- 1.5 Mbaud 下 `earlycon` 必须显式给时钟，否则 divisor 算成 0。
- 厂端用 FIQ debugger 独占的串口，主线会变成普通 `ttyS*`，不要照抄厂端节点。

## 4 以太网

**节点从哪来**：厂端 dtb 的 `ethernet@<addr>`（注意是 `gmac0` 还是 `gmac1`）、PHY 地址、复位脚。

**关键属性**

- `phy-mode`（`rgmii` / `rgmii-id` / `rmii`）、`clock_in_out`；
- `snps,reset-gpio` + `snps,reset-delays-us`（写在**控制器**节点）；
- `tx_delay` / `rx_delay`（能不写就不写，先交给 PHY）；
- `assigned-clock-parents`（父时钟可能不止一个）。

**怎么验**

```sh
ip -br a
ethtool eth0 | grep -E 'Speed|Duplex|Link'
# 大流量往返校验：40 MiB 随机数据 scp 过去再 scp 回来，比 md5
```

判据：1000 Mb/s（或硬件上限）、双向大流量 MD5 一致、`dmesg` 无 PHY 错误。

**常见坑**

- `NO-CARRIER` 先查物理层（网线、对端灯、`ethtool` 的 Link detected），**不要一上来改 delay**。
- 用 `rgmii` + 厂端 delay 值，大流量丢包 → 先试 `rgmii-id` 不写 delay。
- PHY 复位写在 PHY 子节点，换 bootloader 后认不到 PHY（驱动要在枚举 PHY 前拉复位）。
- 只写一个 `assigned-clock-parents`，mux 继承 bootloader 残留值 → TX 超时循环。

## 5 USB

**节点从哪来**：厂端 dtb 的 4~6 个控制器（EHCI/OHCI 两对 + xHCI）+ `usb2phy` + combphy。

**关键属性**

- `&usb_host0_ehci` / `&usb_host0_ohci` / `&usb_host0_xhci` …；
- `&usb2phy0` / `&usb2phy1` 的端口与 `phy-supply`；
- 供电使能：`vcc5v0_host`、`vcc5v0_otg` 的 GPIO 与极性；
- EHCI/OHCI 的 `companion` 配对。

**怎么验**

```sh
lsusb -t          # USB2 设备应是 480M，不是 12M；USB3 应是 5000M
lsblk             # 插 U 盘后应出现块设备
```

硬件侧：万用表量 VBUS（常见 5 V 左右）。

**常见坑**

- **根 hub 全枚举 ≠ 供电正常**：hub 枚举不需要 VBUS，口子可能 0 V。
- 使能脚 bank/极性抄错 → 两个口都没电。
- 只看 `lsusb` 不看速率：设备掉到 12M 往往是 PHY/供电/配对问题。
- MaskROM 用过的那个口，刷完后必须仍能枚举。

## 6 HDMI / 显示

**节点从哪来**：厂端 dtb 的 `hdmi`、`vop`、`vop_mmu`、`vp0`、`hdmi-connector`；同 SoC 公版做写法参考。

**关键属性**

- `&hdmi { status = "okay"; }`、`&vop`、`&vop_mmu`、`&vp0`；
- `hdmi-connector` 与 `ddc-i2c-bus`（如果板子有 DDC）；
- pinctrl 一般用 dtsi 默认，厂端 BSP 的私有 `scl/sda-gpios`、`phy-table` 不要抄。

**怎么验**

```sh
cat /sys/class/drm/card*-HDMI-A-1/status     # connected
modetest -c                                   # 或 xrandr
cat /sys/class/graphics/fb0/name               # rockchipdrmfb
```

外加**目视/采集卡画面**。

**常见坑**

- `connected` 但 EDID 为 0 字节：固定模式输出，不是真识别。
- 黑屏不等于没启动：DRM 是模块且无 simpledrm 时，framebuffer 只在 initramfs 阶段存在。
- 厂端多路显示（副屏/桥接芯片）主线可能没驱动，写进"不做清单"。
- 背光/面板时序属于屏参，不是所有板子都需要。

## 7 音频

**节点从哪来**：codec 在哪（PMIC 内置还是独立芯片）、接哪路 i2s、MCLK 从哪来。

**关键属性**

- `simple-audio-card`（`simple-audio-card,cpu` / `codec` / `dai-link`）；
- `&i2s1_8ch` 或 `&i2s0_8ch` 的 `status`、pinctrl（含 `*_mclk`）；
- PMIC 内的 codec 由 MFD 自动注册，**不要另建 codec 子节点**；
- HDMI 音频：`&hdmi_sound` + 对应的 i2s。

**怎么验**

```sh
aplay -l
speaker-test -t sine -c 2      # 或生成 wav 再 aplay
amixer contents | grep -E 'values='   # 看 mixer 默认值
```

判据：声卡列出、**真的出声（人确认）**、MCLK 频率对、`dmesg` 无 I2C 冲突。

**常见坑**

- 声卡在、但没声音：先查 mixer 默认值（很多 codec 默认静音或衰减很大），再怀疑驱动。
- 厂端的 `hp-volume`、`mic-in-differential`、私有 codec 子节点不要照抄。
- 耳机检测、PA 使能属于可选项，主线没驱动就写"不做"。

## 8 WiFi（SDIO）

**节点从哪来**：SDIO 设备 ID（`/sys/bus/sdio/devices/*/device`）、厂端 dtb 的 `sdmmc1` 节点、
`WL_REG_ON` 复位脚（三源互证：厂端 dtb、同芯片板 dts、运行时 gpio dump）。

**关键属性**

- `&sdmmc1`：`bus-width=4`、`non-removable`、`cap-sdio-irq`、`keep-power-in-suspend`；
- `mmc-pwrseq = <&sdio_pwrseq>`；pwrseq 的 `reset-gpios`、`post-power-on-delay-ms`、`clock`；
- **不要**声明板子做不到的 `sd-uhs-sdr104`（3.3 V 固定 IO 时主线会发 CMD11）。

**怎么验**

```sh
dmesg | grep -iE 'sdio|rtw|brcm'
ip link                # wlan0
nmcli device wifi list # 能扫到 AP
```

**常见坑**

- 复位脚极性反/指错脚（厂端 dtb 也可能错，以运行时 gpio 为准）。
- 内核版本低于芯片驱动要求 → 要么换底料内核，要么等，不要硬改。
- 固件文件名不对/缺失 → 驱动加载了但不出 `wlan0`。
- SDIO 能识别但扫描不到 AP：先查天线、regdomain、rfkill。

## 9 蓝牙（UART）

**节点从哪来**：厂端 dtb 的 uart 节点（注意带 flow control 的那一路）、四个 GPIO
（`BT,reset`、`BT,wake`、`BT,wake_host`、`uart_rts`）、芯片型号。

**关键属性**

- serdev 子节点（`bluetooth`）挂在对应 `&uartX` 下；
- `enable-gpios` / `device-wake-gpios` / `host-wake-gpios`（按主线 binding 命名）；
- 固件：`*_fw.bin` + **`*_config.bin`（很多芯片必需）**；
- 内核 config：`BT_HCIUART`、`BT_HCIUART_H4/H5`、`BT_HCIUART_3WIRE`、`BT_HCIUART_RTL`。

**怎么验**

```sh
hciconfig -a
bluetoothctl list
dmesg | grep -iE 'hci|bluetooth'
```

**常见坑**

- 挂错 UART（厂端日志只注册了某一路，不代表 BT 就在那一路）。
- `hci_h5` 不是独立模块，编在 `hci_uart.ko` 里；找不到模块别慌，看 `dmesg` 的 "Three-wire (H5) registered"。
- 缺 `config.bin` → probe 直接失败。
- WiFi/BT 共存是公认弱项，别承诺"双通稳定"。

## 10 温度 / 看门狗

**节点从哪来**：SoC dtsi 自带的 `tsadc`、`wdt`；多数情况只需 `status = "okay"`。

**怎么验**

```sh
cat /sys/class/thermal/thermal_zone*/type
cat /sys/class/thermal/thermal_zone*/temp
```

判据：空载温度合理；满载不撞 critical；看门狗由服务或驱动持有 `/dev/watchdog`。

**常见坑**：自己写 `thermal-zones` 反而覆盖了 dtsi 的正确配置；`CONFIG_WATCHDOG_SYSFS` 没开时
`/sys/class/watchdog` 不存在，不代表看门狗没工作。

## 11 RTC

**先确认物理条件**：有没有备份电池/超级电容。没有就不要 enable——断电必丢时间，靠 NTP 即可。

**关键属性**：PMIC 内置 RTC 由 MFD 注册；独立 RTC 芯片走 i2c。`CONFIG_RTC_DRV_*` 要开。

**怎么验**：`hwclock -r`；**断电 30 s 再上电**看时间是否保留（这是唯一有意义的判据）。

## 12 按键 / LED

**节点从哪来**：厂端 dtb 的 `gpio-keys` / `adc-keys` / `leds`；丝印与实测。

**关键属性**

- 每颗灯 = 一个 GPIO + 极性 + `default-state`；
- 按键：GPIO 键用 `gpio-keys`；ADC 键用 `adc-keys` + `io-channels` + 键值表。

**怎么验**：`ls /sys/class/leds/` + 目视；`evtest` 出键值。

**常见坑**：厂端遗留的 LED 节点会被误当成本板的灯（多色灯只焊了一颗）；ADC 键的通道/键值
必须实测，不能抄参考板。

## 13 收尾：M-B 清单

每类外设一行，状态只允许四种：

- ✅ 通过（有验收证据）
- 🟡 部分（说明缺什么）
- ⚠️ 待后续（说明阻塞条件）
- ➖ 不适用/不做（写理由）

G4 要求：核心集全 ✅；按需项逐项有结论；发布版 dts 冻结。
