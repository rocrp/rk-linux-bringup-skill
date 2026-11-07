#!/usr/bin/env bash
# env-check.sh —— 检查这台机器能不能跑本 skill 的脚本，并给出缺什么
#
# 用法：
#   ./env-check.sh
#   ./env-check.sh --serial /dev/ttyUSB0     # 额外检查串口设备
#
# 退出码：0 全部必需项通过；1 有缺项。

set -uo pipefail

SERIAL=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --serial) SERIAL="${2:-}"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

FAIL=0
ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$*"; }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAIL=1; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$*"; }

echo "== 基础工具 =="
for t in python3 cpp dtc fdtget sha256sum; do
  if command -v "$t" >/dev/null 2>&1; then
    ok "$t ($("$t" --version 2>&1 | head -1 | cut -c1-50))"
  else
    case "$t" in
      python3|cpp|dtc) bad "$t 未安装" ;;
      *) warn "$t 未安装（部分脚本会跳过相关自检）" ;;
    esac
  fi
done

echo "== Python 版本 =="
if command -v python3 >/dev/null 2>&1; then
  PYV=$(python3 -c 'import sys;print("%d.%d"%sys.version_info[:2])')
  case "$PYV" in
    3.8|3.9|3.1*) ok "python $PYV" ;;
    *) warn "python $PYV（脚本要求 3.8+）" ;;
  esac
fi

echo "== 内核源码树 =="
K="${KERNEL:-}"
if [ -n "$K" ]; then
  [ -d "$K/arch/arm64/boot/dts" ] && ok "KERNEL=$K" || bad "KERNEL=$K 不是 arm64 源码树"
else
  warn "未设置 KERNEL（dts2dtb.sh 需要 --kernel）"
fi

echo "== 镜像/权限工具 =="
for t in losetup mount umount e2fsck sgdisk xz; do
  command -v "$t" >/dev/null 2>&1 && ok "$t" || warn "$t 未安装（镜像装配/打包会用到）"
done
if [ "$(id -u)" = "0" ]; then ok "当前是 root"; else warn "非 root：镜像装配与写盘需要 sudo"; fi

echo "== 串口 =="
if [ -n "$SERIAL" ]; then
  if [ -e "$SERIAL" ]; then
    ok "$SERIAL 存在"
    [ -r "$SERIAL" ] && [ -w "$SERIAL" ] && ok "可读写" || bad "不可读写（检查 dialout 组）"
  else
    bad "$SERIAL 不存在"
  fi
else
  ls /dev/ttyUSB* /dev/ttyACM* 2>/dev/null | sed 's/^/  发现 /' || warn "未发现串口设备（Windows 用 COMx）"
fi

echo "== 开发机 vs WSL =="
if grep -qi microsoft /proc/version 2>/dev/null; then
  ok "WSL 环境（注意 /mnt/* 是 9p，工作区放 /root 或 /work）"
else
  ok "Linux 环境"
fi

echo
if [ "$FAIL" -eq 0 ]; then echo "结论：必需项通过"; else echo "结论：有缺项，见上方 FAIL"; fi
exit "$FAIL"
