#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""QK100 Mk2 (ING9168 / IngChips) 主控固件镜像 —— 校验与重打包工具

镜像格式（36B0_3059_0.bin, v137 实测）:
    0x000  +0x00  "INGCHIPS"                    8   magic
    0x008  +0x08  0x0c + "ING91680C_TB"         目标芯片/模板名（长度前缀）
    0x018  +0x18  0x0c + "HS_KB_WH_V01"         工程名（长度前缀）
    0x030  +0x30  "V0.0.1" x2                   两个 6 字节版本串
    0x03c  +0x3c  00 02                         未知（大端 u16? 疑为 flags/位宽）
    0x03e  +0x3e  u16 LE  CRC16 of payload      校验（见下）
    0x042  +0x42  00 01                         未知（大端 u16?）
    0x044  +0x44  u32 LE = payload_size / 0x100 页数
    0x06a  +0x6a  u32 LE = 装载地址 (0x02027000)
    0x06e  +0x6e  u32 LE = payload_size (0x32300)
    0x080  ...    payload = 搬运到 0x02027000 的镜像（向量表 + 代码 + 常量）

校验算法（已用原厂 v137 反推并验证通过）:
    crc = CRC-16/MODBUS  (poly 0xA001 反射式, init 0xFFFF, 覆盖 payload 全部字节)
    写入头部 0x3e 时按大端存放:  header[0x3e]=crc>>8, header[0x3f]=crc&0xff
    v137 实测 payload CRC = 0x653b -> 头部为 "65 3b"(0x3e/0x3f)

    头 CRC 同样是 CRC-16/MODBUS，覆盖 header[0x00:0x7e]（**包含** 0x3e 的 payload CRC），
    大端写在 0x7e:  header[0x7e]=hcrc>>8, header[0x7f]=hcrc&0xff
    v137 实测 header CRC = 0xd5ec -> "d5 ec"(0x7e/0x7f)
    因此改 payload 后 0x3e 与 0x7e 必须一起重算，否则镜像不自洽。

地址换算:
    file_offset = 0x80 + (addr - 0x02027000)

用法:
    python fw_repack.py info    <image.bin>
    python fw_repack.py verify  <image.bin>          # 只读校验，退出码 0=通过
    python fw_repack.py fix     <in.bin> <out.bin>   # 重算 size 字段与 CRC 后另存
    python fw_repack.py addr2off <addr-hex>
"""

import sys

try:  # 便于在 GBK 控制台下输出中文
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HDR_LEN = 0x80
FLASH_BASE = 0x02027000
OFF_MAGIC = 0x00
OFF_TARGET = 0x08
OFF_PROJECT = 0x18
OFF_FLAGS = 0x3C
OFF_CRC = 0x3E
OFF_PAGES = 0x44
OFF_LOAD = 0x6A
OFF_SIZE = 0x6E
OFF_HCRC = 0x7E      # 头 CRC: CRC16/MODBUS 覆盖 header[0x00:0x7E]，含 0x3E 的 payload CRC


def crc16_modbus(data: bytes, init: int = 0xFFFF) -> int:
    """CRC-16/MODBUS: poly 0xA001(反射), init 0xFFFF, 无最终异或。"""
    crc = init
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc & 0xFFFF


def u16(buf: bytes, off: int) -> int:
    return buf[off] | (buf[off + 1] << 8)


def u32(buf: bytes, off: int) -> int:
    return int.from_bytes(buf[off:off + 4], "little")


def u16be(buf: bytes, off: int) -> int:
    return (buf[off] << 8) | buf[off + 1]


def p16(buf: bytearray, off: int, val: int) -> None:
    buf[off:off + 2] = (val & 0xFFFF).to_bytes(2, "little")


def p16be(buf: bytearray, off: int, val: int) -> None:
    buf[off:off + 2] = (val & 0xFFFF).to_bytes(2, "big")


def p32(buf: bytearray, off: int, val: int) -> None:
    buf[off:off + 4] = (val & 0xFFFFFFFF).to_bytes(4, "little")


def parse(img: bytes) -> dict:
    if img[OFF_MAGIC:OFF_MAGIC + 8] != b"INGCHIPS":
        raise SystemExit("不是 IngChips 更新镜像（magic 不符）")
    tlen = img[OFF_TARGET]
    plen = img[OFF_PROJECT]
    info = {
        "target": img[OFF_TARGET + 1:OFF_TARGET + 1 + tlen].decode("ascii", "replace"),
        "project": img[OFF_PROJECT + 1:OFF_PROJECT + 1 + plen].decode("ascii", "replace"),
        "ver30": img[0x30:0x36].decode("ascii", "replace"),
        "ver36": img[0x36:0x3C].decode("ascii", "replace"),
        "flags3c": img[OFF_FLAGS:OFF_FLAGS + 2].hex(" "),
        "crc_header": u16be(img, OFF_CRC),
        "hcrc_field": u16be(img, OFF_HCRC),
        "hcrc_calc": crc16_modbus(img[:OFF_HCRC]),
        "pages": u32(img, OFF_PAGES),
        "load_addr": u32(img, OFF_LOAD),
        "size_field": u32(img, OFF_SIZE),
        "payload_len": len(img) - HDR_LEN,
        "payload_crc": crc16_modbus(img[HDR_LEN:]),
    }
    return info


def cmd_info(path: str) -> int:
    img = open(path, "rb").read()
    i = parse(img)
    print(f"file              : {path}  ({len(img)} bytes)")
    print(f"target(chip)      : {i['target']}")
    print(f"project           : {i['project']}")
    print(f"version strings   : {i['ver30']} / {i['ver36']}")
    print(f"flags @0x3c       : {i['flags3c']}")
    print(f"load address      : 0x{i['load_addr']:08x}")
    print(f"payload size      : 0x{i['payload_len']:x} ({i['payload_len']})  field@0x6e=0x{i['size_field']:x}")
    print(f"pages field @0x44 : 0x{i['pages']:x} (= size/0x100 ? {i['pages'] == i['payload_len'] // 0x100})")
    print(f"payload CRC16     : 0x{i['payload_crc']:04x}   header@0x3e=0x{i['crc_header']:04x}"
          f"   -> {'OK' if i['payload_crc'] == i['crc_header'] else 'MISMATCH'}")
    print(f"header CRC16      : 0x{i['hcrc_calc']:04x}   header@0x7e=0x{i['hcrc_field']:04x}"
          f"   -> {'OK' if i['hcrc_calc'] == i['hcrc_field'] else 'MISMATCH'}")
    return 0


def cmd_verify(path: str) -> int:
    img = open(path, "rb").read()
    i = parse(img)
    ok = True
    checks = [
        ("payload 大小(0x6e)", i["size_field"] == i["payload_len"]),
        ("页数(0x44)", i["pages"] == i["payload_len"] // 0x100),
        ("CRC16(0x3e)", i["crc_header"] == i["payload_crc"]),
        ("头 CRC16(0x7e)", i["hcrc_field"] == i["hcrc_calc"]),
        ("装载地址(0x6a)", i["load_addr"] == FLASH_BASE),
    ]
    for name, good in checks:
        print(f"[{'OK  ' if good else 'FAIL'}] {name}")
        ok = ok and good
    print("=> " + ("镜像自洽，可直接通过 IAP 升级" if ok else "镜像不自洽，请用 fix 重算后再升级"))
    return 0 if ok else 1


def cmd_fix(src: str, dst: str) -> int:
    img = bytearray(open(src, "rb").read())
    parse(bytes(img))  # magic 自检
    payload = bytes(img[HDR_LEN:])
    size = len(payload)
    p32(img, OFF_SIZE, size)
    p32(img, OFF_PAGES, size // 0x100)
    if u32(img, OFF_LOAD) == 0:
        p32(img, OFF_LOAD, FLASH_BASE)
    p16be(img, OFF_CRC, crc16_modbus(payload))
    p16be(img, OFF_HCRC, crc16_modbus(bytes(img[:OFF_HCRC])))  # 必须放在 payload CRC 之后
    open(dst, "wb").write(bytes(img))
    print(f"written {dst}: size=0x{size:x} pages=0x{size // 0x100:x} "
          f"crc=0x{crc16_modbus(payload):04x} hcrc=0x{u16be(bytes(img), OFF_HCRC):04x}")
    return 0


def cmd_addr2off(a: str) -> int:
    adv = int(a, 16)
    print(f"addr 0x{adv:08x} -> file offset 0x{HDR_LEN + adv - FLASH_BASE:x}")
    return 0


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    op = argv[1]
    if op == "info":
        return cmd_info(argv[2])
    if op == "verify":
        return cmd_verify(argv[2])
    if op == "fix" and len(argv) >= 4:
        return cmd_fix(argv[2], argv[3])
    if op == "addr2off":
        return cmd_addr2off(argv[2])
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))