'''生成"灯组开关不再改写亮度"的 QK100 Mk2 主控候选包。

改动 4 处、共 8 字节（其余由 fw_repack.py 重算 payload CRC 0x3E 与头 CRC 0x7E）：
    运行地址 0x02036936  file 0x0F9B6   C1 70 (strb r1,[r0,#3])   -> 00 BF (nop)  键灯 ≤40 -> 40
    0x02036958  0x0F9D8   41 73 (strb r1,[r0,#0D])  -> 00 BF                      logo ≤10 -> 10
    0x02037304  0x10384   41 73 (strb r1,[r0,#0D])  -> 00 BF                      logo ≤10 -> 40
    0x020381AE  0x1122E   C1 70 (strb r1,[r0,#3])   -> 00 BF                      键灯 ≤40 -> 200

背景：
    固件里每个灯组都有一个"开关时顺手抬亮度"的保护，避免下次开灯全黑：
        键灯  0x02036926 cmp #0x28 / 0x02036936 写 40   (maxBrightness=200 -> 显示 20%)
        键灯  0x0203699E cmp #0x28 / 0x020381AE 写 200  (显示 100%)
        logo  0x02036948 cmp #0x0A / 0x02036958 写 10
        logo  0x020372F4 cmp #0x0A / 0x02037304 写 40   (logo maxBrightness=40；网页却按 200 刻度
                                                        换算，于是显示成 20%)
    实测（probe_funcinfo.py --watch）抓到 logo 亮度 6 -> 40 的跳变，对应 0x02037304。
    拾音灯没有独立亮度字段，用的是所在灯组的亮度字节，所以这些地板会连带影响拾音灯亮度。
    本补丁把 4 个"写亮度"指令全部 nop，开关只改 Switch 位，绝不碰亮度值。

副作用：
    亮度本来就是 0 时，开灯后仍然是 0（灯不亮），需要用网页把亮度调上去。

用法：
    python tools/patch_no_brightness_floor.py
    # 输出 build/36B0_3059_0_v137_nobrightfloor.bin
'''

import hashlib
import pathlib
import subprocess
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / 'firmware' / 'main-v137-official.bin'
OUT_DIR = ROOT / 'build'
DST = OUT_DIR / '36B0_3059_0_v137_nobrightfloor.bin'

# (文件偏移, 原值, 新值, 说明)
PATCHES = [
    (0x0F9B6, b'\xC1\x70', b'\x00\xBF',
     '0x02036936 strb r1,[r0,#3]  -> nop（键灯开灯时 ≤40 抬到 40）'),
    (0x0F9D8, b'\x41\x73', b'\x00\xBF',
     '0x02036958 strb r1,[r0,#0D] -> nop（logo 开灯时 ≤10 抬到 10）'),
    (0x10384, b'\x41\x73', b'\x00\xBF',
     '0x02037304 strb r1,[r0,#0D] -> nop（logo 开灯时 ≤10 直接抬到 40）'),
    (0x1122E, b'\xC1\x70', b'\x00\xBF',
     '0x020381AE strb r1,[r0,#3]  -> nop（键灯开灯时 ≤40 直接抬到 200）'),
]


def main():
    raw = bytearray(SRC.read_bytes())
    original = bytes(raw)
    print(f'原件 {SRC}')
    print(f'     {len(raw)} 字节  SHA256 {hashlib.sha256(bytes(raw)).hexdigest()}')
    for off, old, new, note in PATCHES:
        actual = bytes(raw[off:off + len(old)])
        if actual != old:
            raise SystemExit(f'锚点不符：file {off:#07x} 期望 {old.hex()} 实际 {actual.hex()}')
        raw[off:off + len(new)] = new
        print(f'     patch file {off:#07x}: {old.hex()} -> {new.hex()}   {note}')

    OUT_DIR.mkdir(exist_ok=True)
    tmp = OUT_DIR / '_patched.raw.bin'
    tmp.write_bytes(bytes(raw))
    result = subprocess.run(
        [sys.executable, str(ROOT / 'tools' / 'fw_repack.py'), 'fix', str(tmp), str(DST)],
        check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
    print('     ' + result.stdout.strip())
    tmp.unlink()

    final = DST.read_bytes()
    check = subprocess.run(
        [sys.executable, str(ROOT / 'tools' / 'fw_repack.py'), 'verify', str(DST)],
        capture_output=True, text=True, encoding='utf-8', errors='replace')
    print(check.stdout.rstrip())
    if check.returncode != 0:
        raise SystemExit('校验失败，不要刷写')

    diff = [(i, original[i], final[i]) for i in range(len(original)) if original[i] != final[i]]
    print(f'输出 {DST}  ({len(final)} 字节)')
    print(f'     SHA256 {hashlib.sha256(final).hexdigest()}')
    print(f'     与原件的差异字节 {len(diff)} 个：')
    for i, before, after in diff:
        print(f'       file {i:#07x}  {before:02X} -> {after:02X}')
    return 0


if __name__ == '__main__':
    sys.exit(main())