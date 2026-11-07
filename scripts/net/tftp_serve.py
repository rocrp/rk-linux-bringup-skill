#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tftp_serve.py —— 只读 TFTP 服务端（只处理 RRQ，拒绝写入与路径穿越）。

用途：在没有现成 TFTP 服务、或不想装第三方软件时，给板子的 U-Boot 提供内核/dtb/initramfs。

用法:
    python tftp_serve.py --root ./tftp-root
    python tftp_serve.py --root ./tftp-root --bind 192.168.1.10 --port 69
    python tftp_serve.py --root ./tftp-root --once          # 传完一个文件就退出
    python tftp_serve.py --root ./tftp-root --log tftp.log

行为:
  * 只接受 RRQ；WRQ 一律回 ERROR 2；
  * 拒绝绝对路径与 ".." 越界；
  * 支持 blksize / tsize / timeout 选项协商；
  * 每次传输打印文件名、大小、耗时、速率、sha256。

依赖：仅标准库。绑定 69 端口在 Windows 上不需要管理员，但入站需要防火墙放行 UDP/69。
"""
import argparse
import hashlib
import os
import socket
import struct
import sys
import time

OP_RRQ, OP_WRQ, OP_DATA, OP_ACK, OP_ERROR, OP_OACK = 1, 2, 3, 4, 5, 6
DEFAULT_BLKSIZE = 512
MAX_BLKSIZE = 65464


def log(msg, fh=None):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    if fh:
        fh.write(line + "\n")
        fh.flush()


def parse_request(data):
    """返回 (opcode, filename, mode, options dict)。"""
    opcode = struct.unpack(">H", data[:2])[0]
    rest = data[2:]
    parts = rest.split(b"\0")
    if len(parts) < 2:
        raise ValueError("请求格式不对")
    filename = parts[0].decode("utf-8", "replace")
    mode = parts[1].decode("ascii", "replace").lower()
    opts = {}
    for i in range(2, len(parts) - 1, 2):
        k = parts[i].decode("ascii", "replace").lower()
        v = parts[i + 1].decode("ascii", "replace")
        if k:
            opts[k] = v
    return opcode, filename, mode, opts


def safe_path(root, filename):
    name = filename.replace("\\", "/").lstrip("/")
    if ".." in name.split("/"):
        return None
    path = os.path.abspath(os.path.join(root, name))
    root_abs = os.path.abspath(root)
    if os.path.commonpath([path, root_abs]) != root_abs:
        return None
    return path


def send_error(sock, addr, code, msg):
    sock.sendto(struct.pack(">HH", OP_ERROR, code) + msg.encode() + b"\0", addr)


def serve_one(root, data, addr, sock, logfh, args):
    try:
        opcode, filename, mode, opts = parse_request(data)
    except ValueError as e:
        send_error(sock, addr, 4, str(e))
        return False

    if opcode == OP_WRQ:
        send_error(sock, addr, 2, "read-only server")
        return True
    if opcode != OP_RRQ:
        send_error(sock, addr, 4, "unsupported opcode")
        return True
    if mode != "octet":
        send_error(sock, addr, 4, "only octet mode")
        return True

    path = safe_path(root, filename)
    if path is None:
        send_error(sock, addr, 2, "access violation")
        return True
    if not os.path.isfile(path):
        send_error(sock, addr, 1, "file not found")
        return True

    blksize = DEFAULT_BLKSIZE
    timeout = args.timeout
    if "blksize" in opts:
        try:
            blksize = max(8, min(MAX_BLKSIZE, int(opts["blksize"])))
        except ValueError:
            send_error(sock, addr, 8, "bad blksize")
            return True
    if "timeout" in opts:
        try:
            timeout = max(1, min(30, int(opts["timeout"])))
        except ValueError:
            pass

    size = os.path.getsize(path)
    oack = {}
    if opts:
        if "blksize" in opts:
            oack["blksize"] = str(blksize)
        if "timeout" in opts:
            oack["timeout"] = str(timeout)
        if "tsize" in opts:
            oack["tsize"] = str(size)

    # 每个传输用独立 socket（标准做法：服务器从新的 TID 发数据）。
    tsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    tsock.bind((args.bind, 0))
    tsock.settimeout(timeout)
    try:
        start = time.time()
        digest = hashlib.sha256()
        sent = 0

        if oack:
            pkt = struct.pack(">H", OP_OACK)
            for k, v in oack.items():
                pkt += k.encode() + b"\0" + v.encode() + b"\0"
            tsock.sendto(pkt, addr)
            # 等 ACK 0
            try:
                ack, peer = tsock.recvfrom(1024)
            except socket.timeout:
                return True
            if struct.unpack(">HH", ack[:4])[1] != 0:
                return True

        block = 1
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(blksize)
                pkt = struct.pack(">HH", OP_DATA, block & 0xFFFF) + chunk
                for attempt in range(args.retries + 1):
                    tsock.sendto(pkt, addr)
                    try:
                        ack, peer = tsock.recvfrom(1024)
                        op, num = struct.unpack(">HH", ack[:4])
                        if op == OP_ACK and num == (block & 0xFFFF):
                            break
                    except socket.timeout:
                        if attempt == args.retries:
                            log("  %s: 超时放弃（block %d）" % (filename, block), logfh)
                            return True
                digest.update(chunk)
                sent += len(chunk)
                if len(chunk) < blksize:
                    break
                block += 1
                if sent % (blksize * 64) == 0:
                    log("  %s: %d / %d B (%.0f%%)"
                        % (filename, sent, size, 100.0 * sent / max(size, 1)), logfh)
        dt = max(time.time() - start, 1e-6)
        log("完成 %s  %d B  %.2fs  %.1f KB/s  sha256=%s"
            % (filename, sent, dt, sent / 1024.0 / dt, digest.hexdigest()[:16]), logfh)
        return True
    finally:
        tsock.close()


def main():
    ap = argparse.ArgumentParser(description="只读 TFTP 服务端（RRQ only）")
    ap.add_argument("--root", required=True, help="TFTP 根目录")
    ap.add_argument("--bind", default="0.0.0.0", help="监听地址（默认 0.0.0.0）")
    ap.add_argument("--port", type=int, default=69, help="端口（默认 69）")
    ap.add_argument("--log", help="把服务日志追加到该文件")
    ap.add_argument("--timeout", type=int, default=3, help="重传超时秒数（默认 3）")
    ap.add_argument("--retries", type=int, default=5, help="重传次数（默认 5）")
    ap.add_argument("--once", action="store_true", help="成功传完一个文件后退出")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        ap.error("根目录不存在：%s" % args.root)

    logfh = open(args.log, "a", encoding="utf-8") if args.log else None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((args.bind, args.port))
    except OSError as e:
        print("绑定 %s:%d 失败：%s" % (args.bind, args.port, e), file=sys.stderr)
        print("提示：Windows 上 69 端口一般不需要管理员；端口被占时换 --port，"
              "或用防火墙放行 UDP/69。", file=sys.stderr)
        return 2

    log("TFTP 只读服务：%s:%d，根目录 %s" % (args.bind, args.port, os.path.abspath(args.root)), logfh)
    try:
        while True:
            data, addr = sock.recvfrom(65536)
            done = serve_one(args.root, data, addr, sock, logfh, args)
            if args.once and done:
                break
    except KeyboardInterrupt:
        log("收到中断，退出", logfh)
    finally:
        sock.close()
        if logfh:
            logfh.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
