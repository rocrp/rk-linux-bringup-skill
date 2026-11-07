# 07 镜像：装配、写盘、回滚

> 目标：把"我的卡/我的内存里能跑"变成"谁刷都能跑"，并且随时能退回去。

## 1 两条构建路线

| 路线 | 做法 | 适用 | 风险 |
|---|---|---|---|
| **A 改造底料镜像** | 取现成镜像 → 换 dtb + 改 `fdtfile` → 重新算 sha256 | 大多数情况，最省事 | 要能证明"只改了几处" |
| **B 自建流水线** | 重建 rootfs/分区表、缩体积、固化默认值 | 需要定制 | 分区/GUID、首启逻辑、缺件 |

先走 A；确有必要再上 B。

## 2 选底料

1. **先定内核版本门槛**，再选机型（不要反过来）。
2. 选与目标板最像的：同 SoC、同存储、同显示接口、同网口、同无线方案。
3. 确认 `/boot` 布局：`dtb/<soc>/*.dtb` + `armbianEnv.txt` 的 `fdtfile=` 机制存在。
4. 记录身份：文件名、发布日期、压缩包与解压镜像两条 sha256、内核 `uname -r`、机型。

## 3 从镜像里取东西

```bash
# 解压
gunzip -k image.img.gz

# 看分区
sgdisk -p image.img        # 或 fdisk -l

# 挂 boot 分区（只读优先）
sudo losetup --partscan --find --show image.img
sudo mount -o ro /dev/loopXp1 /mnt/boot
ls /mnt/boot
```

要取的文件：

- `Image` / `vmlinuz-*`
- `uInitrd-*`（或 `initrd.img-*`）
- `dtb/<soc>/*.dtb`（作为同族参考）
- `armbianEnv.txt`、`boot.cmd`/`boot.scr`
- `config-*`（核对你需要的驱动是否 `=y`/`=m`）

## 4 装配：只改该改的

```bash
sudo mount /dev/loopXp1 /mnt/boot
sudo cp board_vN.dtb /mnt/boot/dtb/<soc>/
sudo sed -i 's|^fdtfile=.*|fdtfile=<soc>/board_vN.dtb|' /mnt/boot/armbianEnv.txt
# 按需：关掉首启自动扩容（见 §6）
sudo umount /mnt/boot
sudo losetup -d /dev/loopX
sha256sum image.img
```

**必须记录"相对底料改了几处"**，并用逐块哈希或 `cmp` 证明只改了这些地方。

## 5 写盘

### 5.1 写前复核（缺一项都不许写）

- [ ] 备份可读：sha256 对、抽查分区能读
- [ ] userdata 里该保的数据已取出
- [ ] loader 可用，能进 MaskROM
- [ ] 电源足够，写盘期间不断电、不插拔
- [ ] 发布版 dtb + sha256 + `fdtfile` 路径确认
- [ ] 镜像身份（文件名/sha256/内核版本）记录在案
- [ ] 回滚步骤写在纸上，随时可用

### 5.2 写

```bash
sudo rkdeveloptool list                 # 确认 Maskrom
sudo rkdeveloptool db <loader>.bin      # 送 loader
sudo rkdeveloptool wl 0x0 image.img     # 整盘写（命令名以工具版本为准）
```

GUI 也可以，但"按地址写"必须确认 `addr=0`，且中途不要拔线。

### 5.3 写后校验

- 首选：首启后在板端 `dd` 回读 + `sha256sum` 对比；
- 不要用某些 GUI 的"导出镜像"做校验（可能只读到固定大小，越界填 0xCC）。

## 6 首启的三个通用雷

1. **首启扩容会改分区表**：有的实现是删掉再建分区，分区 GUID 变了，而 `rootdev=PARTUUID=...`
   写死了旧值 → 首启能进、第二次启动掉 initramfs。
   → 给扩容脚本打"扩容后写回原 GUID"的补丁，或改用不依赖 GUID 的 `root=` 写法。
2. **`root=` 的写法必须与 initramfs 状态匹配**：内核早期只认 `PARTUUID=`/`PARTLABEL=`/设备名，
   `UUID=` 依赖 initramfs 的 `/dev/disk/by-uuid`。initramfs 一坏，`UUID=` 必挂。
3. **"关掉首启扩容"的开关可能看内容而不是看文件存在**：有的实现读 `/root/.no_rootfs_resize`
   的内容（`yes` 才扩），有的只看文件存在。**读脚本，不要读文档。**

## 7 回滚

| 介质 | 回滚方式 |
|---|---|
| TF 卡 | 拔卡 |
| TFTP 内存直启 | 断电重来，目标存储未写 |
| 只有 eMMC | `write 0 <系统区备份>.img`；若已扩容，userdata 与 backup GPT 可能已被覆盖，回滚后 Android 会重建 `/data` |

**回滚演练要放在扩容之前**。扩容之后，"原厂 data 原貌"就不存在了。

## 8 冷启动与稳定性

- **断电冷启动 ≥3 次**，每次断电 ≥10 s。软重启不算。
- 关键外设复测：网络吞吐、存储读写、USB 枚举、显示、音频。
- 稳定观察：至少 20 分钟无掉盘/断网/新增 `dmesg -l err`；想更稳就拉长到数小时。
- 记录：每次启动的时间和结果、`dmesg -l err` 条数、温度、频率。

## 9 产物四件套

```
<name>.img          整盘镜像
<name>.img.xz       压缩版
<name>.img.sha256   校验
README.md           设备信息、验证矩阵、已知限制、刷写步骤
```

再加一份 `SHA256SUMS` 覆盖全部文件。

## 10 常见坑

- 镜像里 dtb 没进 `/boot/dtb` 或路径写错 → 首启起不来。
- `fdtfile` 写成了绝对路径（应相对 `/boot/dtb/`）。
- 内核升级会重建 `/boot/dtb`，自建 dtb 被冲掉 → 加 `/etc/kernel/postinst.d/` 钩子把 dtb 补回。
- 设备端 rootfs 是 `commit=600`，写完不 `sync` 就断电会丢文件。
- 磁盘工具版本差异：旧 `e2fsck` 不认新特性，看起来像文件系统坏了。
- WSL 里把分区挂到 `/mnt` 会遮住 WSL 自己的 `/mnt`，换个子目录。
- 用 `cp` 覆盖镜像内文件时，目标必须已分配且大小一致；否则要重建镜像。
