#!/usr/bin/env bash
# probe-matrix.sh —— 外设验收矩阵（设备端，只读；输出 PASS/FAIL/SKIP 表）
#
# 用法（设备端 root）：
#   sudo ./probe-matrix.sh                 # 核心项
#   sudo ./probe-matrix.sh --all           # 含可选外设（WiFi/音频/HDMI）
#   sudo ./probe-matrix.sh --out /tmp/matrix.md
#
# 判据只做"最低限度可判定"的检查；需要人听/看/量的项标 SKIP，由人到 references 里逐项验收。
#
# 退出码：0 全部已测项 PASS；1 有 FAIL；2 参数错误。

set -uo pipefail

ALL=0
OUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --all) ALL=1; shift ;;
    --out) OUT="${2:-}"; shift 2 ;;
    *) echo "未知参数：$1" >&2; exit 2 ;;
  esac
done

FAIL=0
ROWS=()

add() { ROWS+=("$1|$2|$3|$4"); [ "$2" = "FAIL" ] && FAIL=1; }

check() {  # check <名称> <判据命令> <通过说明> [可选=1]
  local name="$1" cmd="$2" note="$3" optional="${4:-0}"
  if [ "$optional" = "1" ] && [ "$ALL" != "1" ]; then
    add "$name" "SKIP" "$note（--all 才测）" ""; return
  fi
  if bash -c "$cmd" >/dev/null 2>&1; then
    add "$name" "PASS" "$note" ""
  else
    add "$name" "FAIL" "$note" ""
  fi
}

# ---- 核心项 ----
check "串口控制台" "test -c /dev/ttyS0 || test -c /dev/ttyS2 || test -c /dev/ttyFIQ0" "存在可用串口设备" 
check "PMIC 注册" "dmesg | grep -qiE 'rk80[89]|rk81[0-9]'" "dmesg 出现 PMIC 驱动"
check "regulator" "ls /sys/class/regulator/regulator.* >/dev/null 2>&1" "至少一路 regulator"
check "eMMC/SD" "lsblk -o NAME,TYPE | grep -q disk" "识别到块设备"
check "根文件系统" "test -n \"\$(findmnt -n -o SOURCE /)\"" "根分区已挂载"
check "网口存在" "ls /sys/class/net | grep -qvE '^(lo|wlan|docker)'" "至少一个有线网口"
check "网口链路" "for i in \$(ls /sys/class/net); do [ -f /sys/class/net/\$i/carrier ] && [ \"\$(cat /sys/class/net/\$i/carrier)\" = 1 ] && exit 0; done; exit 1" "至少一个口 carrier=1"
check "USB 控制器" "lsusb >/dev/null 2>&1" "lsusb 可用"
check "温度可读" "cat /sys/class/thermal/thermal_zone0/temp >/dev/null 2>&1" "thermal zone 存在"
check "dmesg 无新增错误" "test \"\$(dmesg -l err 2>/dev/null | wc -l)\" -le \"\${ERR_BASELINE:-999}\"" "err 条数 ≤ 基线（ERR_BASELINE）"

# ---- 可选 ----
check "WiFi" "ip link | grep -qE '^[0-9]+: wlan'" "存在 wlan 接口" 1
check "WiFi 扫描" "command -v nmcli >/dev/null && nmcli -t -f SSID dev wifi list | grep -q ." "能扫到 SSID" 1
check "蓝牙" "command -v hciconfig >/dev/null && hciconfig -a | grep -q 'UP RUNNING'" "hci0 UP RUNNING" 1
check "声卡" "command -v aplay >/dev/null && aplay -l | grep -q '^card'" "aplay 列出声卡" 1
check "HDMI 连接" "ls /sys/class/drm/card*-HDMI-A-1/status >/dev/null 2>&1 && grep -q connected /sys/class/drm/card*-HDMI-A-1/status" "HDMI status=connected" 1
check "RTC" "test -e /dev/rtc0 && hwclock -r >/dev/null 2>&1" "/dev/rtc0 可读" 1

# ---- 输出 ----
{
  echo "# 外设验收矩阵"
  echo
  echo "- 时间：$(date -Is)"
  echo "- 主机：$(hostname 2>/dev/null)"
  echo
  echo "| 项 | 判据 | 结果 | 备注 |"
  echo "|---|---|---|---|"
  for r in "${ROWS[@]}"; do
    IFS='|' read -r name res note _ <<< "$r"
    echo "| $name | $res | $note | |"
  done
  echo
  echo "> PASS/FAIL 只代表自动检查；需要听/看/量的项请按 references/06-peripherals.md 人工验收。"
} | tee ${OUT:+"$OUT"}

[ -n "$OUT" ] && echo "已写入 $OUT"
[ "$FAIL" -eq 0 ] && exit 0 || exit 1
