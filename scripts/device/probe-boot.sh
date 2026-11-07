#!/usr/bin/env bash
# probe-boot.sh —— 设备端冷启动后的一次性采集（只读，输出 Markdown + 原始文件）
#
# 用法（设备端 root）：
#   sudo ./probe-boot.sh /tmp/probe-$(date +%Y%m%d-%H%M)
#
# 采集内容：内核/机型/cmdline、在役 dtb 与 sha256、dmesg err、regulator、gpio、
#           网络与链路、存储、USB、温度、failed units。
#
# 退出码：0 采集完成（不代表全部通过）；2 参数错误。

set -uo pipefail

OUT="${1:-}"
[ -n "$OUT" ] || { echo "用法：$0 <输出目录>" >&2; exit 2; }
mkdir -p "$OUT" || exit 2

MD="$OUT/report.md"
: > "$MD"

sec() { printf '\n## %s\n\n' "$1" >> "$MD"; }
run() {  # run <标题> <命令...>
  local title="$1"; shift
  printf '### %s\n\n```text\n' "$title" >> "$MD"
  "$@" >> "$MD" 2>&1 || echo "(命令失败：$*)" >> "$MD"
  printf '```\n\n' >> "$MD"
}

{
  echo "# 启动采集报告"
  echo
  echo "- 时间：$(date -Is)"
  echo "- 主机：$(hostname 2>/dev/null)"
} >> "$MD"

sec "1 基本"
run "uname" uname -a
run "cmdline" cat /proc/cmdline
run "model" cat /proc/device-tree/model
run "compatible" cat /proc/device-tree/compatible
run "uptime" uptime

sec "2 在役 dtb"
{
  echo '```text'
  FDTFILE=$(sed -n 's/^fdtfile=//p' /boot/armbianEnv.txt 2>/dev/null | head -1)
  echo "fdtfile=$FDTFILE"
  if [ -n "$FDTFILE" ]; then
    P="/boot/dtb/${FDTFILE#dtb/}"
    echo "path=$P"
    [ -f "$P" ] && sha256sum "$P" || echo "（文件不存在）"
  fi
  echo '```'
} >> "$MD"

sec "3 内核错误"
run "dmesg -l err" dmesg -l err
run "failed units" systemctl --failed --no-pager

sec "4 电源"
run "regulator summary" cat /sys/kernel/debug/regulator/regulator_summary
run "regulator names" sh -c 'for f in /sys/class/regulator/*/name; do cat "$f"; done'

sec "5 GPIO"
run "gpio" cat /sys/kernel/debug/gpio

sec "6 网络"
run "ip" ip -br a
for i in $(ls /sys/class/net 2>/dev/null | grep -v '^lo$'); do
  run "ethtool $i" ethtool "$i"
done

sec "7 存储"
run "lsblk" lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINTS
run "mmc" sh -c 'dmesg | grep -iE "mmc|sdhci" | tail -40'

sec "8 USB"
run "lsusb -t" lsusb -t

sec "9 温度"
run "thermal" sh -c 'for z in /sys/class/thermal/thermal_zone*; do echo "$z $(cat $z/type 2>/dev/null) $(cat $z/temp 2>/dev/null)"; done'

sec "10 结论提示"
{
  echo "> 本报告只采集事实，不做判定。判据见 references/06-peripherals.md。"
  echo
  echo "- \`dmesg -l err\` 的条数：$(dmesg -l err 2>/dev/null | wc -l)"
  echo "- failed units：$(systemctl --failed --no-pager --plain 2>/dev/null | tail -n +2 | wc -l)"
} >> "$MD"

echo "已写入 $MD"
echo "提示：把它和上一次的采集对比，判据是"零新增"，不是"零条"。"
