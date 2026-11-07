#!/usr/bin/env bash
# release-build.sh —— 把装配好的镜像打包成发布四件套（img / img.xz / sha256 / README）
#
# 用法：
#   ./release-build.sh myboard-v1.img --name myboard-v1
#   ./release-build.sh myboard-v1.img --name myboard-v1 --no-xz
#   ./release-build.sh myboard-v1.img --name myboard-v1 --base armbian-base.img
#
# 做的事：
#   1. 检查镜像（存在、可读、大小合理）；
#   2. 若给了 --base，按 1 MiB 块比对，打印"相对底料改了哪些块"；
#   3. xz 压缩（可选）；
#   4. 生成 sha256 文件；
#   5. 从模板生成 README（设备信息与验证矩阵留空待填）。
#
# 不做：重新装配分区、缩 rootfs、改 GPT —— 那些用 image-set-dtb.sh 或你自己的流水线。
#
# 退出码：0 成功；1 失败；2 参数错误。

set -euo pipefail

IMG=""
NAME=""
BASE=""
DO_XZ=1

usage() { sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; }

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --name) NAME="${2:-}"; shift 2 ;;
    --base) BASE="${2:-}"; shift 2 ;;
    --no-xz) DO_XZ=0; shift ;;
    -*) echo "未知参数：$1" >&2; exit 2 ;;
    *) IMG="$1"; shift ;;
  esac
done

[ -n "$IMG" ] || { usage; exit 2; }
[ -f "$IMG" ] || { echo "找不到 $IMG" >&2; exit 2; }
[ -n "$NAME" ] || NAME="$(basename "$IMG" .img)"

OUTDIR="$(dirname "$IMG")"
echo "== release-build =="
echo "  镜像: $IMG ($(stat -c %s "$IMG" 2>/dev/null || stat -f %z "$IMG") B)"
echo "  名称: $NAME"

if [ -n "$BASE" ]; then
  [ -f "$BASE" ] || { echo "找不到底料 $BASE" >&2; exit 2; }
  echo "[1/4] 与底料按 1 MiB 块比对"
  SIZE_MIN=$(( $(stat -c %s "$IMG") < $(stat -c %s "$BASE") ? $(stat -c %s "$IMG") : $(stat -c %s "$BASE") ))
  BLOCKS=$(( SIZE_MIN / 1048576 ))
  DIFF=0
  for ((i=0; i<BLOCKS; i++)); do
    A=$(dd if="$IMG" bs=1M skip=$i count=1 2>/dev/null | sha256sum | cut -d' ' -f1)
    B=$(dd if="$BASE" bs=1M skip=$i count=1 2>/dev/null | sha256sum | cut -d' ' -f1)
    [ "$A" != "$B" ] && { echo "  块 $i 不同"; DIFF=$((DIFF+1)); }
  done
  echo "  共 $BLOCKS 块，$DIFF 块不同"
else
  echo "[1/4] 跳过底料比对（未给 --base）"
fi

SHA="$(sha256sum "$IMG" | cut -d' ' -f1)"
echo "[2/4] sha256: $SHA"
printf '%s  %s\n' "$SHA" "$(basename "$IMG")" > "$IMG.sha256"

if [ "$DO_XZ" = "1" ]; then
  echo "[3/4] xz 压缩（-T0 -6，耗时较长，可另开窗口等）"
  if command -v xz >/dev/null 2>&1; then
    xz -T0 -6 -k -f "$IMG"
    XZ="$IMG.xz"
    printf '%s  %s\n' "$(sha256sum "$XZ" | cut -d' ' -f1)" "$(basename "$XZ")" >> "$IMG.sha256"
    echo "  $XZ ($(stat -c %s "$XZ") B)"
  else
    echo "  未安装 xz，跳过" >&2
  fi
else
  echo "[3/4] 跳过 xz"
fi

echo "[4/4] 生成 README"
cat > "$OUTDIR/$NAME-README.md" <<EOF
# $NAME

- 镜像：$(basename "$IMG")
- 大小：$(stat -c %s "$IMG") B
- sha256：$SHA
- 日期：$(date +%F)

## 验证矩阵

| 外设 | 状态 | 验证方式 | 备注 |
|---|---|---|---|
| 串口 | | | |
| 电源/PMIC | | | |
| 存储 | | | |
| 网口 | | | |
| USB | | | |
| 显示 | | | |
| 音频 | | | |
| WiFi | | | |
| 蓝牙 | | | |

## 已知限制

（逐条写，带原因）

## 刷写

（进 MaskROM、送 loader、写盘、冷启动 ≥3）

## 回滚

（备份文件名、sha256、回滚命令）
EOF
echo "  $OUTDIR/$NAME-README.md"

echo "完成。发布前：填 README、脱敏日志、确认 SHA256SUMS 覆盖所有文件。"
