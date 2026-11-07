#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tftp_get.py —— 只读 TFTP 客户端（自测服务端 / 从板子取文件 / 校验用）。

用法:
    python tftp_get.py 192.168.1.10 Image -o ./Image
    python tftp_get.py 192.168.1.10 board.dtb --blksize 1468 --sha256 <预期值>
    python tftp_get.py 192.168.1.10 Image --port 6969

退出码: 0 成功；1 传输失败；2 参数错误；3 sha256 不符。

依赖：仅标准库。
"""
import argparse
import hashlib
import os
import socket
import struct
import sys
import time

OP_RRQ, OP_DATA, OP_ACK, OP_ERROR, OP_OACK = 1, 3, 4, 5, 6


def main():
    ap = argparse.ArgumentParser(description="只读 TFTP 客户端")
    ap.add_argument("server", help="服务器地址")
    ap.add_argument("file", help="远端文件名")
    ap.add_argument("-o", "--out", help="保存路径（默认与远端同名）")
    ap.add_argument("--port", type=int, default=69, help="服务器端口（默认 69）")
    ap.add_argument("--blksize", type=int, default=0, help="协商块大小（0=不协商）")
    ap.add_argument("--timeout", type=int, default=3)
    ap.add_argument("--retries", type=int, default=5)
    ap.add_argument("--sha256", help="预期 sha256（不符则退出码 3）")
    args = ap.parse_args()

    out = args.out or os.path.basename(args.file)
    opts = b""
    if args.blksize:
        opts += b"blksize\0" + str(args.blksize).encode() + b"\0"
    opts += b"timeout\0" + str(args.timeout).encode() + b"\0"

    pkt = struct.pack(">H", OP_RRQ) + args.file.encode() + b"\0octet\0" + opts
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(args.timeout)
    try:
        sock.sendto(pkt, (args.server, args.port))
    except OSError as e:
        print("发送请求失败：%s" % e, file=sys.stderr)
        return 2

    blksize = 512
    start = time.time()
    data_total = bytearray()
    expected_block = 1
    server_addr = None

    try:
        while True:
            try:
                resp, addr = sock.recvfrom(65536)
            except socket.timeout:
                print("等待数据超时", file=sys.stderr)
                return 1

            op = struct.unpack(">H", resp[:2])[0]
            if op == OP_ERROR:
                code = struct.unpack(">H", resp[2:4])[0]
                print("服务器返回 ERROR %d: %s" % (code, resp[4:].rstrip(b"\0").decode("utf-8", "replace")),
                      file=sys.stderr)
                return 1
            if op == OP_OACK:
                server_addr = addr
                parts = resp[2:].split(b"\0")
                for i in range(0, len(parts) - 1, 2):
                    k = parts[i].decode("ascii", "replace").lower()
                    v = parts[i + 1].decode("ascii", "replace")
                    if k == "blksize":
                        blksize = int(v)
                    elif k == "tsize":
                        print("远端大小：%s B" % v, file=sys.stderr)
                sock.sendto(struct.pack(">HH", OP_ACK, 0), addr)
                continue
            if op != OP_DATA:
                print("收到未知 opcode %d" % op, file=sys.stderr)
                return 1

            server_addr = addr
            block = struct.unpack(">H", resp[2:4])[0]
            chunk = resp[4:]
            if block == expected_block:
                data_total += chunk
                sock.sendto(struct.pack(">HH", OP_ACK, block), addr)
                if len(chunk) < blksize:
                    break
                expected_block = (expected_block + 1) & 0xFFFF
            else:
                # 重复包/乱序：重发上一个 ACK
                sock.sendto(struct.pack(">HH", OP_ACK, (expected_block - 1) & 0xFFFF), addr)

        with open(out, "wb") as fh:
            fh.write(data_total)
    except KeyboardInterrupt:
        print("中断", file=sys.stderr)
        return 1
    finally:
        sock.close()

    dt = max(time.time() - start, 1e-6)
    sha = hashlib.sha256(data_total).hexdigest()
    print("完成：%s  %d B  %.2fs  %.1f KB/s" % (out, len(data_total), dt, len(data_total) / 1024.0 / dt))
    print("sha256=%s" % sha)
    if args.sha256 and args.sha256.lower() != sha.lower():
        print("!! sha256 不符（预期 %s）" % args.sha256, file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
