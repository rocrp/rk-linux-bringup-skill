#!/usr/bin/env bash
# deploy-dtb.sh —— 在设备端安全地投放一颗新 dtb（备份 → 装 → 改 fdtfile → 回读 → sync）
#
# 用法（设备端 root）：
#   sudo ./deploy-dtb.sh board_v3.dtb
#   sudo ./deploy-dtb.sh board_v3.dtb --name rk356x-myboard_v3
#   sudo ./deploy-dtb.sh board_v3.dtb --dry-run
#
# 行为：
#   1. 备份 /boot/armbianEnv.txt 与在役 dtb（带时间戳）；
#   2. 复制新 dtb 到 /boot/dtb/<soc>/；
#   3. 把 armbianEnv.txt 的 fdtfile 指到新文件；
#   4. 回读 sha256，与源文件比对；
#   5. sync（rootfs 可能是 commit=600，不 sync 掉电会丢）。
#
# 退出码：0 成功；1 校验失败；2 参数/环境错误。

set -euo pipefail

DTB=""
NAME=""
ENV_FILE="/boot/armbianEnv.txt"
DTB_DIR=""
DRY=0

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --env) ENV_FILE="${2:-}"; shift 2 ;;
    --dtbdir) DTB_DIR="${2:-}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -*) echo "未知参数：$1" >&2; exit 2 ;;
    *) DTB="$1"; shift ;;
  esac
done

[ -n "$DTB" ] || { echo "缺少 dtb 文件" >&2; exit 2; }
[ -f "$DTB" ] || { echo "找不到 $DTB" >&2; exit 2; }
[ "$(id -u)" = "0" ] || { echo "需要 root（sudo）" >&2; exit 2; }
[ -f "$ENV_FILE" ] || { echo "找不到 $ENV_FILE（不是 Armbian 布局？用 --env 指定）" >&2; exit 2; }

[ -n "$NAME" ] || NAME="$(basename "$DTB" .dtb)"
[ -n "$DTB_DIR" ] || DTB_DIR="$(dirname "$ENV_FILE")/dtb/rockchip"

# 从 dts 里读 soc 目录不可靠，这里允许用户用 --dtbdir 覆盖；默认 rockchip。
[ -d "$DTB_DIR" ] || { echo "找不到 dtb 目录 $DTB_DIR（用 --dtbdir 指定）" >&2; exit 2; }

STAMP="$(date +%Y%m%d-%H%M%S)"
CUR_NAME="$(sed -n 's/^fdtfile=//p' "$ENV_FILE" | head -1)"
CUR_DTB=""
[ -n "$CUR_NAME" ] && CUR_DTB="$(dirname "$ENV_FILE")/dtb/${CUR_NAME#dtb/}"

echo "== deploy-dtb ==" 
echo "  新 dtb : $DTB"
echo "  目标名 : $NAME"
echo "  env    : $ENV_FILE"
echo "  dtb 目录: $DTB_DIR"
echo "  当前 fdtfile: ${CUR_NAME:-（空）}"
[ "$DRY" = "1" ] && echo "  （dry-run，不改任何文件）"

if [ "$DRY" = "1" ]; then
  echo "将执行：备份 env 与在役 dtb → 复制 → 改 fdtfile → 回读 sha256 → sync"
  exit 0
fi

echo "[1/5] 备份"
cp -a "$ENV_FILE" "$ENV_FILE.bak-$STAMP"
echo "  $ENV_FILE.bak-$STAMP"
if [ -n "$CUR_DTB" ] && [ -f "$CUR_DTB" ]; then
  cp -a "$CUR_DTB" "$CUR_DTB.bak-$STAMP"
  echo "  $CUR_DTB.bak-$STAMP"
fi

echo "[2/5] 复制 dtb"
cp -f "$DTB" "$DTB_DIR/$NAME.dtb"

echo "[3/5] 更新 fdtfile"
FDT_PATH="rockchip/$NAME.dtb"
if grep -q '^fdtfile=' "$ENV_FILE"; then
  sed -i "s|^fdtfile=.*|fdtfile=$FDT_PATH|" "$ENV_FILE"
else
  printf 'fdtfile=%s\n' "$FDT_PATH" >> "$ENV_FILE"
fi
grep '^fdtfile=' "$ENV_FILE"

echo "[4/5] 回读校验"
SRC_SHA="$(sha256sum "$DTB" | cut -d' ' -f1)"
DST_SHA="$(sha256sum "$DTB_DIR/$NAME.dtb" | cut -d' ' -f1)"
echo "  src=$SRC_SHA"
echo "  dst=$DST_SHA"
if [ "$SRC_SHA" != "$DST_SHA" ]; then
  echo "!! 校验失败，回滚" >&2
  cp -a "$ENV_FILE.bak-$STAMP" "$ENV_FILE"
  [ -n "$CUR_DTB" ] && [ -f "$CUR_DTB.bak-$STAMP" ] && cp -a "$CUR_DTB.bak-$STAMP" "$CUR_DTB"
  sync
  exit 1
fi

echo "[5/5] sync"
sync

echo
echo "完成。下一步："
echo "  1. 断电冷启动（不是 reboot）；"
echo "  2. 启动后确认：cat /proc/device-tree/model 与 dtb 版本一致；"
echo "  3. 需要回滚时：把 $ENV_FILE.bak-$STAMP 恢复，并重启。"
