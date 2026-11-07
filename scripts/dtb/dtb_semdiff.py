#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dtb_semdiff.py —— 两份 dtb 的语义级差异（phandle 先解析成节点路径再比较）。

为什么需要"语义级"：
  直接按字节/数字比，每个含 phandle 的属性都会被报成差异（只是编号变了）。
  本工具把 `<&cru 7>` 规范化成 `cells:&/clock-controller@... 0x7`，
  "只换编号"不再算差异，剩下的才是真差异。

用法:
    python dtb_semdiff.py a.dtb b.dtb
    python dtb_semdiff.py a.dtb b.dtb --out report.md
    python dtb_semdiff.py a.dtb b.dtb --only /i2c@fe5c0000 --only /vcc-sd
    python dtb_semdiff.py a.dtb b.dtb --hide /cpus
    python dtb_semdiff.py a.dtb b.dtb --max-rows 0        # 不限行数

只读。退出码：0 无差异，1 有语义差异，2 参数/文件错误。
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fdt  # noqa: E402

DEFAULT_HIDE = ("/__symbols__",)


def load(path):
    with open(path, "rb") as fh:
        data = fh.read()
    root, rsv, version, boot_cpuid = fdt.parse(data)
    return data, root, rsv, version, boot_cpuid


def main():
    ap = argparse.ArgumentParser(description="两份 dtb 的语义级差异")
    ap.add_argument("a", help="DTB A")
    ap.add_argument("b", help="DTB B")
    ap.add_argument("--out", help="Markdown 报告写入该文件")
    ap.add_argument("--only", action="append", default=[], metavar="PATH",
                    help="只比较这些子树（可重复）")
    ap.add_argument("--hide", action="append", default=[], metavar="PATH",
                    help="屏蔽这些子树（可重复；默认屏蔽 /__symbols__）")
    ap.add_argument("--max-rows", type=int, default=400, help="表格最多行数（0=不限）")
    ns = ap.parse_args()

    for p in (ns.a, ns.b):
        if not os.path.isfile(p):
            ap.error("找不到文件：%s" % p)

    da, ra, rsva, vera, boota = load(ns.a)
    db, rb, rsvb, verb, bootb = load(ns.b)
    fa = {n.path: n for n in ra.walk()}
    fb = {n.path: n for n in rb.walk()}
    pha, _ = fdt.build_phandles(ra)
    phb, _ = fdt.build_phandles(rb)

    hide = list(DEFAULT_HIDE) + list(ns.hide)
    only = list(ns.only)

    def keep(path):
        if fdt.under(path, hide):
            return False
        if only and not fdt.under(path, only):
            return False
        return True

    only_a = sorted(p for p in set(fa) - set(fb) if keep(p))
    only_b = sorted(p for p in set(fb) - set(fa) if keep(p))

    diffs, renumber = [], []
    for path in sorted(set(fa) & set(fb)):
        if not keep(path):
            continue
        pa = dict(fa[path].props)
        pb = dict(fb[path].props)
        for key in sorted(set(pa) | set(pb)):
            if key in ("phandle", "linux,phandle"):
                continue
            va, vb = pa.get(key), pb.get(key)
            ca, cb = fdt.canon_prop(key, va, pha), fdt.canon_prop(key, vb, phb)
            if ca == cb:
                continue
            la, lb = fdt.canon_lenient(va, pha), fdt.canon_lenient(vb, phb)
            if la is not None and la == lb:
                renumber.append((path, key, la))
            else:
                diffs.append((path, key, ca, cb))

    out = []
    w = out.append
    w("# DTB 语义级差异：A vs B")
    w("")
    w("| 项 | A | B |")
    w("|---|---|---|")
    w("| 文件 | `%s` | `%s` |" % (os.path.basename(ns.a), os.path.basename(ns.b)))
    w("| 字节数 | %d | %d |" % (len(da), len(db)))
    w("| 节点数 | %d | %d |" % (len(fa), len(fb)))
    w("| FDT version | %d | %d |" % (vera, verb))
    w("| boot_cpuid | %d | %d |" % (boota, bootb))
    w("")
    w("## 1 节点增删")
    w("")
    w("- 只在 A 中（%d）：%s" % (len(only_a), ", ".join("`%s`" % p for p in only_a) or "无"))
    w("- 只在 B 中（%d）：%s" % (len(only_b), ", ".join("`%s`" % p for p in only_b) or "无"))
    w("")
    w("## 2 语义级属性差异 —— %d 处" % len(diffs))
    w("")
    w("> phandle 已规范化：只换编号不算差异。")
    w("")
    rows = diffs if not ns.max_rows else diffs[:ns.max_rows]
    if rows:
        w("| 节点 | 属性 | A | B |")
        w("|---|---|---|---|")
        for path, key, ca, cb in rows:
            w("| `%s` | `%s` | %s | %s |" % (
                path, key,
                ("（不存在）" if ca is None else ca).replace("|", "\\|"),
                ("（不存在）" if cb is None else cb).replace("|", "\\|")))
        if len(diffs) > len(rows):
            w("")
            w("（其余 %d 行略，调大 --max-rows）" % (len(diffs) - len(rows)))
    else:
        w("**无差异**")
    w("")
    w("## 3 仅 phandle 编号不同 —— %d 处" % len(renumber))
    w("")
    if renumber:
        w("| 节点 | 属性 | 共同形态 |")
        w("|---|---|---|")
        for path, key, la in renumber[:ns.max_rows or len(renumber)]:
            w("| `%s` | `%s` | `%s` |" % (path, key, la.replace("|", "\\|")))
    else:
        w("无。")
    w("")

    text = "\n".join(out)
    if ns.out:
        with open(ns.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    print(text)
    if ns.out:
        print("\n[已写入] %s" % os.path.abspath(ns.out))
    return 1 if diffs else 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    sys.exit(main())
