#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dtb_inspect.py —— 只读查看/反编译 dtb（开发机没有 dtc 时用）。

用法:
    python dtb_inspect.py board.dtb                  # 头信息 + 节点统计
    python dtb_inspect.py board.dtb --tree           # 节点树（path + compatible + status）
    python dtb_inspect.py board.dtb --dts board.dts  # 反编译成可读 dts
    python dtb_inspect.py board.dtb --grep pmic      # 查节点/属性
    python dtb_inspect.py board.dtb --wiring         # 接线表（phandle -> gpio + 引脚名）
    python dtb_inspect.py board.dtb --wiring eth     # 接线表（只看匹配行）
    python dtb_inspect.py board.dtb --symbols        # 列出 /__symbols__

只读，不修改输入文件。退出码：0 成功，2 文件/格式错误。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fdt  # noqa: E402


def cmd_tree(root, out):
    out.write("### nodes (%d)\n" % sum(1 for _ in root.walk()))
    for n in root.walk():
        comp = n.get_strlist("compatible")
        status = n.get_str("status")
        line = n.path or "/"
        if comp:
            line += "  [" + ", ".join(comp) + "]"
        if status:
            line += "  status=%s" % status
        out.write(line + "\n")


def cmd_grep(root, pat, out):
    pat_l = pat.lower()
    hits = 0
    for n in root.walk():
        if pat_l in n.path.lower() \
                or any(pat_l in c.lower() for c in n.get_strlist("compatible")) \
                or any(pat_l in k.lower() for k, _ in n.props):
            out.write("== %s\n" % (n.path or "/"))
            for k, v in n.props:
                out.write("   %s%s;\n" % (k, fdt.fmt_prop(k, v)))
            hits += 1
    out.write("--- %d node(s) matched %r\n" % (hits, pat))


def cmd_wiring(root, needle, out):
    ph, labels = fdt.build_phandles(root)
    for n in root.walk():
        for name, val in n.props:
            if not val or len(val) % 4 or len(val) > 16:
                continue
            cells = list(__import__("struct").unpack(">%dI" % (len(val) // 4), val))
            if cells[0] not in ph:
                continue
            if not (name.endswith(("-gpios", "-gpio", "-supply", "-pwrseq", "_irq", "_gpio", "_gpios"))
                    or name in ("interrupt-parent", "rockchip,grf", "rockchip,pmu", "mmc-pwrseq")):
                continue
            if needle and needle.lower() not in n.path.lower() and needle.lower() not in name.lower():
                continue
            tgt = ph[cells[0]]
            tname = labels.get(tgt.path, tgt.path)
            extra = ""
            comp = tgt.get_str("compatible") or ""
            if len(cells) >= 2 and "gpio" in comp:
                extra = "   -> %s pin=%d (%s)" % (tname, cells[1], fdt.pin_name(cells[1]))
            out.write("%-42s %-22s %s%s\n" % (
                n.path, name, " ".join("0x%x" % c for c in cells), extra))


def cmd_symbols(root, out):
    n = None
    for x in root.walk():
        if x.path == "/__symbols__":
            n = x
            break
    if n is None:
        out.write("（没有 /__symbols__；用 dtc -@ 编译才会生成）\n")
        return
    for k, v in sorted(n.props):
        out.write("%-32s %s\n" % (k, v.split(b"\0")[0].decode("utf-8", "replace")))


def main():
    ap = argparse.ArgumentParser(description="只读查看/反编译 dtb")
    ap.add_argument("dtb", help="输入 .dtb")
    ap.add_argument("--dts", metavar="FILE", help="反编译到该文件")
    ap.add_argument("--tree", action="store_true", help="节点树")
    ap.add_argument("--grep", metavar="PAT", help="按关键字查节点")
    ap.add_argument("--wiring", nargs="?", const="", metavar="PAT", help="接线表（phandle/GPIO）")
    ap.add_argument("--symbols", action="store_true", help="列出 /__symbols__")
    args = ap.parse_args()

    if not os.path.isfile(args.dtb):
        ap.error("找不到文件：%s" % args.dtb)
    with open(args.dtb, "rb") as f:
        data = f.read()
    try:
        root, rsv, version, boot_cpuid = fdt.parse(data)
    except ValueError as e:
        ap.error(str(e))

    print("// %s  size=%d version=%d boot_cpuid=%d nodes=%d memreserve=%d"
          % (args.dtb, len(data), version, boot_cpuid,
             sum(1 for _ in root.walk()), len(rsv)), file=sys.stderr)
    print("// root compatible: %s" % ", ".join(root.get_strlist("compatible")), file=sys.stderr)

    if args.dts:
        with open(args.dts, "w", encoding="utf-8") as fh:
            fdt.write_dts(root, rsv, fh,
                          header_comment="// decompiled from %s by dtb_inspect.py\n"
                                         % os.path.basename(args.dtb))
        print("// wrote %s" % args.dts, file=sys.stderr)

    if not any([args.tree, args.grep, args.wiring is not None, args.symbols, args.dts]):
        print("root: %s" % (root.path or "/"))
        print("children: %d" % len(root.children))
        return 0

    if args.tree:
        cmd_tree(root, sys.stdout)
    if args.grep:
        cmd_grep(root, args.grep, sys.stdout)
    if args.wiring is not None:
        cmd_wiring(root, args.wiring, sys.stdout)
    if args.symbols:
        cmd_symbols(root, sys.stdout)
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    sys.exit(main())
