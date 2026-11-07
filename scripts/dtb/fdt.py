#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fdt.py —— 纯 Python 的 FDT(.dtb) 读写库（本 skill 的三个 DTB 工具共用）。

设计目标：
  * 只依赖标准库，Windows / Linux / WSL 都能跑；
  * 读：解析、反编译、节点树、grep、接线表、语义比较；
  * 写：就地改属性/搬节点/删节点，序列化回 dtb（可选补齐到固定长度）。

不做什么：
  * 不是 dts 编译器：不展开 `#include`、不处理宏；
  * 不做语义校验：写错节点名/属性名不会报错，只会让内核忽略它；
  * 反编译出的 dts 是"可读"而非"可编"（属性类型靠启发式判断）。

用法见同目录的 dtb_inspect.py / dtb_semdiff.py / dtb_edit.py。
"""
import struct

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9
PRINTABLE = set(range(0x20, 0x7F))

# phandle 还原/比较的启发式规则（避免"数字恰好等于某个 phandle"的误还原）：
#   first：只有第 0 个 cell 是 phandle（gpios、supply、interrupt-parent…）
#   even ：成对出现，偶数下标是 phandle（clocks、resets、phys…）
#   all  ：每个 cell 都是 phandle（pinctrl-N、pm_qos）
SINGLE_PHANDLE_PROPS = {
    "interrupt-parent", "rockchip,grf", "rockchip,pmu", "rockchip,sgrf",
    "io-domains", "mmc-pwrseq", "pwms", "power-domains",
    "rockchip,grf-clock", "rockchip,pmugrf",
}
PAIRWISE_PHANDLE_PROPS = {
    "clocks", "resets", "phys", "dmas", "iommus", "io-channels",
    "assigned-clocks", "assigned-clock-parents", "interrupts-extended",
}


class Node:
    __slots__ = ("name", "props", "children", "parent")

    def __init__(self, name, parent=None):
        self.name = name
        self.props = []          # [(name, bytes), ...] 保持原顺序
        self.children = []
        self.parent = parent

    @property
    def path(self):
        if self.parent is None:
            return "/"
        base = self.parent.path
        return (base if base.endswith("/") else base + "/") + self.name

    def get(self, key):
        for k, v in self.props:
            if k == key:
                return v
        return None

    def get_str(self, key):
        v = self.get(key)
        return None if v is None else v.split(b"\0")[0].decode("utf-8", "replace")

    def get_strlist(self, key):
        v = self.get(key)
        return [] if v is None else [s.decode("utf-8", "replace") for s in v.split(b"\0") if s]

    def get_cells(self, key):
        v = self.get(key)
        if v is None or len(v) % 4:
            return []
        return list(struct.unpack(">%dI" % (len(v) // 4), v))

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


def parse(data):
    """解析 dtb，返回 (root, memreserve, version, boot_cpuid)。"""
    (magic, totalsize, off_struct, off_strings, off_rsvmap,
     version, last_comp, boot_cpuid, size_strings, size_struct) = struct.unpack_from(">10I", data, 0)
    if magic != FDT_MAGIC:
        raise ValueError("不是 DTB（magic=0x%08x）" % magic)
    strings = data[off_strings:off_strings + size_strings]

    rsv, off = [], off_rsvmap
    while off + 16 <= len(data):
        addr, size = struct.unpack_from(">QQ", data, off)
        if addr == 0 and size == 0:
            break
        rsv.append((addr, size))
        off += 16

    def str_at(o):
        return strings[o:strings.find(b"\0", o)].decode("utf-8", "replace")

    placeholder = Node("")
    cur = placeholder
    pos, end = off_struct, off_struct + size_struct
    while pos < end:
        tok, = struct.unpack_from(">I", data, pos)
        pos += 4
        if tok == FDT_BEGIN_NODE:
            e = data.find(b"\0", pos)
            child = Node(data[pos:e].decode("utf-8", "replace"), cur)
            cur.children.append(child)
            cur = child
            pos = (e + 1 + 3) & ~3
        elif tok == FDT_END_NODE:
            cur = cur.parent
        elif tok == FDT_PROP:
            ln, nameoff = struct.unpack_from(">II", data, pos)
            pos += 8
            cur.props.append((str_at(nameoff), data[pos:pos + ln]))
            pos = (pos + ln + 3) & ~3
        elif tok == FDT_NOP:
            pass
        elif tok == FDT_END:
            break
        else:
            raise ValueError("非法 token %d @%d" % (tok, pos - 4))

    root = placeholder.children[0] if len(placeholder.children) == 1 else placeholder
    root.parent = None
    return root, rsv, version, boot_cpuid


def looks_like_string(v):
    # 全 0 的 cell（如 `#clock-cells = <0>`）不能被误判成空字符串：要求至少一个可打印字节。
    return len(v) >= 2 and v.endswith(b"\0") and v[:-1] and any(
        b in PRINTABLE for b in v[:-1]) and all(
        b == 0 or b in PRINTABLE for b in v[:-1])


def fmt_string(v):
    return ", ".join('"%s"' % s.decode("utf-8", "replace") for s in v.split(b"\0") if s)


def build_phandles(root):
    """返回 (phandle -> Node, 节点路径 -> 标签)。标签来自 /__symbols__。"""
    ph, labels, symbols = {}, {}, {}
    for n in root.walk():
        c = n.get_cells("phandle") or n.get_cells("linux,phandle")
        if c:
            ph[c[0]] = n
        if n.path == "/__symbols__":
            for k, v in n.props:
                symbols[k] = v.split(b"\0")[0].decode("utf-8", "replace")
    for label, path in symbols.items():
        labels[path] = label
    return ph, labels


def pin_name(idx):
    return "RK_P%s%d" % ("ABCD"[idx // 8], idx % 8) if idx < 32 else "pin%d" % idx


def fmt_prop(name, val, ph=None, labels=None):
    ph = ph or {}
    labels = labels or {}
    if len(val) == 0:
        return ""
    if looks_like_string(val):
        return " = %s" % fmt_string(val)
    if len(val) % 4 == 0:
        cells = struct.unpack(">%dI" % (len(val) // 4), val)
        if name in SINGLE_PHANDLE_PROPS or name.endswith(("-gpios", "-gpio", "-supply", "-pwrseq")):
            mode = "first"
        elif name in PAIRWISE_PHANDLE_PROPS:
            mode = "even"
        else:
            mode = "none"

        def one(c, idx):
            ok = (mode == "first" and idx == 0) or (mode == "even" and idx % 2 == 0)
            if ok and c in ph:
                p = ph[c].path
                return "&" + labels[p] if p in labels else p
            return "0x%x" % c
        return " = <%s>" % " ".join(one(c, i) for i, c in enumerate(cells))
    return " = [%s]" % " ".join("%02x" % b for b in val)


def write_dts(root, rsv, fh, header_comment=""):
    ph, labels = build_phandles(root)
    fh.write("%s/dts-v1/;\n\n" % header_comment)
    for addr, size in rsv:
        fh.write("/memreserve/ 0x%x 0x%x;\n" % (addr, size))
    if rsv:
        fh.write("\n")
    fh.write("/ {\n")

    def rec(n, depth):
        ind = "\t" * depth
        for name, val in n.props:
            fh.write("%s%s%s;\n" % (ind, name, fmt_prop(name, val, ph, labels)))
        for c in n.children:
            fh.write("\n%s%s {\n" % (ind, c.name if c.name else "/"))
            rec(c, depth + 1)
            fh.write("%s};\n" % ind)

    rec(root, 1)
    fh.write("};\n")


# ---------- 编辑 ----------

def find_node(root, path):
    if path in ("/", ""):
        return root
    cur = root
    for part in [p for p in path.split("/") if p]:
        nxt = None
        for c in cur.children:
            if c.name == part:
                nxt = c
                break
        if nxt is None:
            raise SystemExit("找不到节点 %s（%s 下没有 %s）" % (path, cur.path or "/", part))
        cur = nxt
    return cur


def set_prop(node, name, value):
    for i, (k, _v) in enumerate(node.props):
        if k == name:
            node.props[i] = (name, value)
            return "改"
    node.props.append((name, value))
    return "加"


def rm_prop(node, name):
    n = len(node.props)
    node.props = [(k, v) for k, v in node.props if k != name]
    if len(node.props) == n:
        raise SystemExit("节点 %s 上没有属性 %s" % (node.path, name))
    return n - len(node.props)


def parse_value(text):
    """值语法：s:字符串 / u:1,2,3 / b:hex / 空（布尔）。"""
    if text is None or text == "":
        return b""
    if text.startswith("s:"):
        return b"".join(p.encode("utf-8") + b"\0" for p in text[2:].split("\\,"))
    if text.startswith("u:"):
        cells = [int(c, 0) for c in text[2:].split(",") if c != ""]
        return struct.pack(">%dI" % len(cells), *cells)
    if text.startswith("b:"):
        return bytes.fromhex(text[2:])
    raise SystemExit("看不懂的值语法：%r（用 s:/u:/b: 或留空）" % text)


def serialize(root, rsv, off_rsvmap=0x38, version=17, last_comp=16, boot_cpuid=0, pad_to=None):
    """把树序列化成 dtb。pad_to 用于"写回固定大小槽位"的场景。"""
    strings = bytearray()

    def str_off(name):
        # 仿 libfdt：在整个表里找 `名字\0` 的任意位置匹配，命中就复用。
        needle = name.encode("utf-8") + b"\0"
        idx = strings.find(needle)
        if idx >= 0:
            return idx
        idx = len(strings)
        strings.extend(needle)
        return idx

    def align4(b):
        return b + b"\0" * ((4 - len(b) % 4) % 4)

    def emit(n, out):
        out += struct.pack(">I", FDT_BEGIN_NODE)
        out += align4(n.name.encode("utf-8") + b"\0")
        for k, v in n.props:
            out += struct.pack(">III", FDT_PROP, len(v), str_off(k))
            out += align4(v)
        for c in n.children:
            emit(c, out)
        out += struct.pack(">I", FDT_END_NODE)

    struct_block = bytearray()
    emit(root, struct_block)
    struct_block += struct.pack(">I", FDT_END)

    off_dt_struct = (off_rsvmap + 16 * (len(rsv) + 1) + 7) & ~7
    off_strings = off_dt_struct + len(struct_block)
    totalsize = off_strings + len(strings)

    out = bytearray(struct.pack(">10I", FDT_MAGIC, totalsize, off_dt_struct, off_strings,
                                off_rsvmap, version, last_comp, boot_cpuid,
                                len(strings), len(struct_block)))
    out += b"\0" * (off_rsvmap - len(out))
    for a, s in rsv:
        out += struct.pack(">QQ", a, s)
    out += struct.pack(">QQ", 0, 0)
    out += b"\0" * (off_dt_struct - len(out))
    out += struct_block
    out += strings
    if pad_to is not None:
        if len(out) > pad_to:
            raise SystemExit("输出 %d 字节，超过 --pad-to %d" % (len(out), pad_to))
        out += b"\0" * (pad_to - len(out))
    return bytes(out)


def tree_sig(root):
    """把树拍平成 {路径: [(属性名, 值)]}，用于写出后的自检。"""
    return {n.path: list(n.props) for n in root.walk()}


# ---------- 语义比较 ----------

def prop_mode(name):
    import re
    if name == "rockchip,pins":
        return "pin4"
    if re.fullmatch(r"pinctrl-\d+", name):
        return "all"
    if name == "pm_qos":
        return "all"
    if name in ("msi-map", "iommu-map"):
        return "idx2"
    if name in SINGLE_PHANDLE_PROPS or name.endswith(("-gpios", "-gpio", "-supply", "-pwrseq")):
        return "first"
    if name in PAIRWISE_PHANDLE_PROPS:
        return "even"
    return "none"


def _cells_to_str(cells, mode, ph):
    out = []
    for i, c in enumerate(cells):
        is_ref = (mode == "first" and i == 0) \
            or (mode == "even" and i % 2 == 0) \
            or (mode == "all") \
            or (mode == "idx2" and i in (1, 2)) \
            or (mode == "pin4" and i % 4 == 3)
        out.append(("&" + ph[c].path) if (is_ref and c in ph) else ("0x%x" % c))
    return "cells:" + " ".join(out)


def canon_prop(name, val, ph):
    """严格规则：按约定位置把 phandle 解析成节点路径，用于判"是否语义不同"。"""
    if val is None:
        return None
    if len(val) == 0:
        return "bool"
    mode = prop_mode(name)
    # gpio-hog 内的 gpios = <pin flags> 只有 2 个 cell，第 0 个是引脚号，不是 phandle。
    if name in ("gpio", "gpios") and len(val) == 8:
        mode = "none"
    if len(val) % 4 == 0:
        cells = struct.unpack(">%dI" % (len(val) // 4), val)
        if mode != "none" or not looks_like_string(val):
            return _cells_to_str(cells, mode, ph)
    if looks_like_string(val):
        return "str:" + "|".join(s.decode("utf-8", "replace") for s in val.split(b"\0") if s)
    return "bytes:" + val.hex()


def canon_lenient(val, ph):
    """宽规则：任何能解析成 phandle 的 cell 都解析，只用于"是否仅编号不同"的二次判断。"""
    if val is None or len(val) == 0 or len(val) % 4 or looks_like_string(val):
        return None
    cells = struct.unpack(">%dI" % (len(val) // 4), val)
    return _cells_to_str(cells, "all", ph)


def under(path, prefixes):
    return any(path == p or path.startswith(p.rstrip("/") + "/") for p in prefixes)
