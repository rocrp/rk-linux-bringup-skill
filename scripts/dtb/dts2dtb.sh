#!/usr/bin/env bash
# dts2dtb.sh —— 用 cpp + dtc 把板级 dts 编成 dtb（不依赖 make，不依赖完整内核构建）
#
# 用途：DTS 迭代的主力工具。展开 #include 后用 dtc 编译，并做基本自检。
# 用法：
#   ./dts2dtb.sh board.dts --kernel /path/to/linux
#   ./dts2dtb.sh board.dts --kernel /path/to/linux --out board.dtb
#   ./dts2dtb.sh board.dts --kernel /path/to/linux --include ./my-includes
#
# 依赖：cpp、dtc、fdtget（设备树工具包）
# 运行位置：Linux / WSL2（Windows 原生没有 dtc）
# 说明：--kernel 指向与目标内核同版本的源码树；代差会静默改变节点。

set -euo pipefail

usage() {
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

DTS=""
KERNEL=""
OUT=""
EXTRA_INC=()

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) usage 0 ;;
    --kernel) KERNEL="${2:-}"; shift 2 ;;
    --out) OUT="${2:-}"; shift 2 ;;
    --include) EXTRA_INC+=("-I${2:-}"); shift 2 ;;
    -*) echo "未知参数：$1" >&2; usage 2 ;;
    *) DTS="$1"; shift ;;
  esac
done

[ -n "$DTS" ] || { echo "缺少 dts 文件" >&2; usage 2; }
[ -f "$DTS" ] || { echo "找不到 $DTS" >&2; exit 2; }
[ -n "$KERNEL" ] || { echo "必须给 --kernel <内核源码目录>" >&2; exit 2; }
[ -d "$KERNEL/arch/arm64/boot/dts" ] || {
  echo "$KERNEL 看起来不是 arm64 内核源码树" >&2; exit 2; }

for t in cpp dtc; do
  command -v "$t" >/dev/null 2>&1 || { echo "缺少工具：$t" >&2; exit 2; }
done

[ -n "$OUT" ] || OUT="${DTS%.dts}.dtb"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

echo "[1/4] cpp 展开：$DTS"
cpp -nostdinc \
  -I "$KERNEL/include" \
  -I "$KERNEL/arch/arm64/boot/dts" \
  -I "$KERNEL/arch/arm64/boot/dts/rockchip" \
  "${EXTRA_INC[@]}" \
  -undef -D__DTS__ -x assembler-with-cpp \
  "$DTS" -o "$TMP/pre.dts"

echo "[2/4] dtc 编译"
# 反编译源常带 lint 警告，先全部收下，最后按"是否新增"判断。
dtc -@ -I dts -O dtb -o "$OUT" "$TMP/pre.dts" 2> "$TMP/dtc.err" || {
  echo "dtc 失败：" >&2; cat "$TMP/dtc.err" >&2; exit 1; }
if [ -s "$TMP/dtc.err" ]; then
  echo "  dtc 警告/提示："
  sed 's/^/    /' "$TMP/dtc.err"
fi

echo "[3/4] 自检"
command -v fdtget >/dev/null 2>&1 && {
  echo "  model      = $(fdtget -t s "$OUT" / model 2>/dev/null || echo '（无）')"
  echo "  compatible = $(fdtget -t s "$OUT" / compatible 2>/dev/null || echo '（无）')"
}
SYMS=$(strings "$OUT" | grep -c '^__symbols__$' || true)
SIZE=$(stat -c %s "$OUT" 2>/dev/null || stat -f %z "$OUT")
echo "  大小       = ${SIZE} 字节"
echo "  __symbols__ = $([ "$SYMS" -gt 0 ] && echo 有 || echo '无（检查是否加了 -@）')"
command -v sha256sum >/dev/null 2>&1 && echo "  sha256     = $(sha256sum "$OUT" | cut -d' ' -f1)"

echo "[4/4] 完成：$OUT"
echo "提示：投放前先备份在役 dtb 与 env；投放后回读 sha256 确认。"
