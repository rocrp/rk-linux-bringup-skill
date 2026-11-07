#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""make_payload.py —— 把内核 + dtb（+ initramfs）拼成单个文件，并生成 U-Boot 命令。

为什么需要：有些厂端 U-Boot 每次上电只允许**一次**网络传输（下完一个文件后所有网络命令静默），
还可能有"不收裸 initrd"的怪癖。把三样东西拼成一个文件、一次取走，能绕开这两类问题。

用法:
    python make_payload.py --image Image --dtb board_v1.dtb
    python make_payload.py --image Image --dtb board_v1.dtb --initrd initrd.cpio.gz -o payload.bin
    python make_payload.py --image Image --dtb board.dtb --kaddr 0x00280000 --gap 0x200000

输出:
    payload 文件（默认 payload.bin）
    boot-cmds.txt（可直接粘贴到 U-Boot 的命令）

布局: [Image][padding gap][dtb][padding gap][initrd]
地址: kernel=kaddr, fdt=kaddr+len(Image)+gap, initrd=fdt+len(dtb)+gap

注意:
  * --initrd 必须是 **U-Boot 能直接传给内核**的格式（通常 gzip cpio）；
    如果你的 initrd 是 uImage+xz（很多发行版镜像里的 uInitrd），先用内核工具转换。
  * 地址必须落在 U-Boot 的 RAM 范围内，且不与其他区域重叠；先用 printenv 看默认值。

依赖：仅标准库。
"""
import argparse
import hashlib
import os
import sys


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser(description="拼单文件 payload + 生成 U-Boot 命令")
    ap.add_argument("--image", required=True, help="内核 Image")
    ap.add_argument("--dtb", required=True, help="板级 dtb")
    ap.add_argument("--initrd", help="initramfs（可选，gzip cpio）")
    ap.add_argument("-o", "--out", default="payload.bin", help="输出文件（默认 payload.bin）")
    ap.add_argument("--kaddr", default="0x00280000", help="内核加载地址（默认 0x00280000）")
    ap.add_argument("--gap", default="0x200000", help="各段之间的空隙（默认 2 MiB）")
    ap.add_argument("--bootargs",
                    default="console=ttyS2,1500000 earlycon=uart8250,mmio32,0xfe660000 rdinit=/bin/sh",
                    help="bootargs")
    ap.add_argument("--cmds", default="boot-cmds.txt", help="生成的命令文件")
    args = ap.parse_args()

    for p in (args.image, args.dtb):
        if not os.path.isfile(p):
            ap.error("找不到文件：%s" % p)
    if args.initrd and not os.path.isfile(args.initrd):
        ap.error("找不到 initrd：%s" % args.initrd)

    kaddr = int(args.kaddr, 0)
    gap = int(args.gap, 0)
    image = open(args.image, "rb").read()
    dtb = open(args.dtb, "rb").read()
    initrd = open(args.initrd, "rb").read() if args.initrd else b""

    fdt_addr = kaddr + len(image) + gap
    initrd_addr = fdt_addr + len(dtb) + gap

    blob = bytearray()
    blob += image
    blob += b"\0" * gap
    blob += dtb
    if initrd:
        blob += b"\0" * gap
        blob += initrd

    with open(args.out, "wb") as fh:
        fh.write(blob)

    lines = []
    lines.append("# 由 make_payload.py 生成")
    lines.append("# payload: %s  %d B  sha256=%s" % (args.out, len(blob), sha256(args.out)))
    lines.append("# 用法：先把 payload 放到 TFTP 根，再在 U-Boot 里执行下面的命令")
    lines.append("")
    lines.append("setenv ipaddr <板子IP>")
    lines.append("setenv serverip <开发机IP>")
    lines.append("ping ${serverip}")
    lines.append("tftp ${loadaddr} %s" % os.path.basename(args.out))
    lines.append("setenv bootargs %s" % args.bootargs)
    if initrd:
        lines.append("booti 0x%08x 0x%08x:0x%x 0x%08x"
                     % (kaddr, initrd_addr, len(initrd), fdt_addr))
    else:
        lines.append("booti 0x%08x - 0x%08x" % (kaddr, fdt_addr))
    lines.append("")
    lines.append("# 地址说明：")
    lines.append("#   kernel 0x%08x (len %d)" % (kaddr, len(image)))
    lines.append("#   fdt    0x%08x (len %d)" % (fdt_addr, len(dtb)))
    if initrd:
        lines.append("#   initrd 0x%08x (len %d)" % (initrd_addr, len(initrd)))

    with open(args.cmds, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")

    print("payload : %s (%d B)" % (args.out, len(blob)))
    print("sha256  : %s" % sha256(args.out))
    print("kernel  : 0x%08x (%d B)" % (kaddr, len(image)))
    print("fdt     : 0x%08x (%d B)" % (fdt_addr, len(dtb)))
    if initrd:
        print("initrd  : 0x%08x (%d B)" % (initrd_addr, len(initrd)))
    print("命令    : %s" % args.cmds)
    print()
    print("提示：如果 U-Boot 的 loadaddr 小于 fdt_addr，必须先 tftp 到高地址，"
          "或用 cp.b 把 payload 搬到 kaddr 再 booti。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
