#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dtb_edit.py —— 纯 Python 的 dtb 编辑器（不依赖 dtc / 内核树）。

典型用途：把一份现成 dtb 就地改成"更接近本板"的样子，做一次快速假设验证。
  * --mv      把节点（含子树）搬到另一个父节点下；
  * --enable / --disable  改 status；
  * --set / --rm          增删改属性；
  * --del     删节点（含子树）；
  * --pad-to  补齐到固定字节数（写回镜像固定槽位时用）。

限制：
  * 不展开 #include，不生成 dts；
  * 输出可能比输入大/小几字节（对齐与字符串表差异）；
  * 不做语义校验，写错名字不会报错 —— 改完必须人肉复核。

值语法：s:字符串 / u:1,2,3 / b:hex / 空（布尔）。

示例:
    python dtb_edit.py in.dtb out.dtb --disable /i2c@fe5c0000
    python dtb_edit.py in.dtb out.dtb --set /chosen bootargs "s:console=ttyS2,1500000"
    python dtb_edit.py in.dtb out.dtb --mv /i2c@fe5c0000/pmic@20 /i2c@fe5c0000

退出码：0 成功（自检通过），2 参数/格式错误。
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fdt  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="纯 Python dtb 编辑器")
    ap.add_argument("src", help="输入 .dtb")
    ap.add_argument("dst", help="输出 .dtb")
    ap.add_argument("--mv", nargs=2, action="append", default=[], metavar=("节点", "新父节点"))
    ap.add_argument("--enable", action="append", default=[], metavar="节点")
    ap.add_argument("--disable", action="append", default=[], metavar="节点")
    ap.add_argument("--set", nargs=3, action="append", default=[], metavar=("节点", "属性", "值"))
    ap.add_argument("--rm", nargs=2, action="append", default=[], metavar=("节点", "属性"))
    ap.add_argument("--del", dest="delete", action="append", default=[], metavar="节点")
    ap.add_argument("--pad-to", type=lambda s: int(s, 0), default=None)
    ns = ap.parse_args()

    if not os.path.isfile(ns.src):
        ap.error("找不到文件：%s" % ns.src)
    with open(ns.src, "rb") as fh:
        data = fh.read()
    root, rsv, version, boot_cpuid = fdt.parse(data)
    header = struct.unpack_from(">10I", data, 0)
    print("输入 %s：%d 字节，%d 节点，memreserve %d 条"
          % (ns.src, len(data), sum(1 for _ in root.walk()), len(rsv)))

    for path, parent in ns.mv:
        n = fdt.find_node(root, path)
        p = fdt.find_node(root, parent)
        if n.parent is None:
            raise SystemExit("不能搬根节点")
        old = n.parent.path
        n.parent.children.remove(n)
        n.parent = p
        p.children.append(n)
        print("  搬 %s：%s -> %s" % (path, old or "/", p.path or "/"))
    for path in ns.enable:
        print("  %s status=%s" % (fdt.set_prop(fdt.find_node(root, path), "status", b"okay\0"), path))
    for path in ns.disable:
        print("  %s status=%s" % (fdt.set_prop(fdt.find_node(root, path), "status", b"disabled\0"), path))
    for path, prop, val in ns.set:
        v = fdt.parse_value(val)
        print("  %s %s %s（%d 字节）"
              % (fdt.set_prop(fdt.find_node(root, path), prop, v), path, prop, len(v)))
    for path, prop in ns.rm:
        node = fdt.find_node(root, path)
        print("  删属性 %s/%s（%d 项）" % (path, prop, fdt.rm_prop(node, prop)))
    for path in ns.delete:
        n = fdt.find_node(root, path)
        n.parent.children.remove(n)
        print("  删节点 %s（含子树）" % path)

    blob = fdt.serialize(root, rsv, off_rsvmap=header[4], version=version,
                         last_comp=header[6], boot_cpuid=boot_cpuid, pad_to=ns.pad_to)
    with open(ns.dst, "wb") as fh:
        fh.write(blob)
    print("输出 %s：%d 字节（原 %d，差 %+d）" % (ns.dst, len(blob), len(data), len(blob) - len(data)))

    # 自检：重读写出物，节点集合与每个节点的属性必须与内存树一致。
    root2, _rsv2, ver2, _cpu2 = fdt.parse(blob)
    sig1, sig2 = fdt.tree_sig(root), fdt.tree_sig(root2)
    if sum(1 for _ in root.walk()) != sum(1 for _ in root2.walk()) or set(sig1) != set(sig2):
        raise SystemExit("!! 自检失败：重读的树与内存树不一致")
    diff = [p for p in sig1 if sig1[p] != sig2.get(p)]
    if diff:
        raise SystemExit("!! 自检失败：这些节点属性重读后不同：%s" % diff[:5])
    print("自检通过：重读 %d 节点、属性逐项一致（FDT version=%d）"
          % (sum(1 for _ in root2.walk()), ver2))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:
        pass
    sys.exit(main())
