#!/usr/bin/env bash
# image-set-dtb.sh —— 在 PC 上把 dtb 塞进镜像的 boot 分区（不启动板子）
#
# 用途：出厂镜像自带的 dtb 未必能起本板，首启就可能进不去；先在 PC 上装配好再写盘。
#
# 用法（Linux/WSL root）：
#   sudo ./image-set-dtb.sh armbian.img board_v3.dtb --name board_v3
#   sudo ./image-set-dtb.sh armbian.img board_v3.dtb --name board_v3 --no-resize
#   sudo ./image-set-dtb.sh armbian.img board_v3.dtb --dry-run
#
# 做的事：
#   1. losetup --partscan 挂镜像；
#   2. 挂 boot 分区到临时目录；
#   3. 复制 dtb 到 dtb/rockchip/；
#   4. 改 armbianEnv.txt 的 fdtfile；
#   5. 按需关闭首启自动扩容（写 .no_rootfs_resize=no）；
#   6. 卸载、整镜像 sha256、打印"相对底料改了什么"。
#
# 退出码：0 成功；1 校验/操作失败；2 参数错误。

set -euo pipefail

IMG=""
DTB=""
NAME=""
BOOT_PART=1
SOC_DIR="rockchip"
NO_RESIZE=0
DRY=0

usage() { sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --boot-part) BOOT_PART="${2:-1}"; shift 2 ;;
    --soc-dir) SOC_DIR="${2:-rockchip}"; shift 2 ;;
    --no-resize) NO_RESIZE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -*) echo "未知参数：$1" >&2; exit 2 ;;
    *) if [ -z "$IMG" ]; then IMG="$1"; elif [ -z "$DTB" ]; then DTB="$1"; else
         echo "多余参数：$1" >&2; exit 2; fi; shift ;;
  esac
done

[ -n "$IMG" ] && [ -n "$DTB" ] || { usage; exit 2; }
[ -f "$IMG" ] || { echo "找不到镜像 $IMG" >&2; exit 2; }
[ -f "$DTB" ] || { echo "找不到 dtb $DTB" >&2; exit 2; }
[ "$(id -u)" = "0" ] || { echo "需要 root（sudo）" >&2; exit 2; }
[ -n "$NAME" ] || NAME="$(basename "$DTB" .dtb)"

echo "== image-set-dtb =="
echo "  镜像: $IMG"
echo "  dtb : $DTB -> $SOC_DIR/$NAME.dtb"
echo "  分区: p$BOOT_PART"
[ "$DRY" = "1" ] && echo "  （dry-run）"

BEFORE_SHA="$(sha256sum "$IMG" | cut -d' ' -f1)"
echo "  写前 sha256: $BEFORE_SHA"

if [ "$DRY" = "1" ]; then
  echo "将执行：losetup → mount p$BOOT_PART → 复制 dtb → 改 fdtfile → 卸载 → sha256"
  exit 0
fi

LOOP="$(losetup --partscan --find --show "$IMG")"
MNT="$(mktemp -d)"
cleanup() {
  umount "$MNT" 2>/dev/null || true
  losetup -d "$LOOP" 2>/dev/null || true
  rmdir "$MNT" 2>/dev/null || true
}
trap cleanup EXIT

echo "[1/5] 挂载 ${LOOP}p${BOOT_PART}"
mount "${LOOP}p${BOOT_PART}" "$MNT"

[ -f "$MNT/armbianEnv.txt" ] || {
  echo "!! 分区里没有 armbianEnv.txt；确认 --boot-part 与发行版" >&2; exit 1; }

echo "[2/5] 复制 dtb"
mkdir -p "$MNT/dtb/$SOC_DIR"
cp -f "$DTB" "$MNT/dtb/$SOC_DIR/$NAME.dtb"

echo "[3/5] 更新 fdtfile"
if grep -q '^fdtfile=' "$MNT/armbianEnv.txt"; then
  sed -i "s|^fdtfile=.*|fdtfile=$SOC_DIR/$NAME.dtb|" "$MNT/armbianEnv.txt"
else
  printf 'fdtfile=%s\n' "$SOC_DIR/$NAME.dtb" >> "$MNT/armbianEnv.txt"
fi
grep '^fdtfile=' "$MNT/armbianEnv.txt"

if [ "$NO_RESIZE" = "1" ]; then
  echo "[3.5] 关闭首启自动扩容（写 .no_rootfs_resize=no）"
  # 不同实现语义不同：有的看内容、有的看存在。写 no 对"看内容"的实现是关闭。
  printf 'no\n' > "$MNT/.no_rootfs_resize" 2>/dev/null || true
  echo "  已写 $MNT/.no_rootfs_resize = no"
  echo "  ⚠ 请确认你的镜像用的是哪种实现（读脚本，不要读文档）"
fi

echo "[4/5] 卸载"
sync
umount "$MNT"
losetup -d "$LOOP"
trap - EXIT
rmdir "$MNT" 2>/dev/null || true

echo "[5/5] 校验"
AFTER_SHA="$(sha256sum "$IMG" | cut -d' ' -f1)"
echo "  写后 sha256: $AFTER_SHA"
echo "  相对底料：$([ "$BEFORE_SHA" = "$AFTER_SHA" ] && echo '未变（异常）' || echo '已改变')"
echo
echo "完成。写盘前请确认："
echo "  - 回读 /boot/dtb/$SOC_DIR/$NAME.dtb 的 sha256 与源一致；"
echo "  - armbianEnv.txt 的 fdtfile 路径正确（相对 /boot/dtb/）；"
echo "  - 备份可读、loader 可用、回滚步骤在手。"
