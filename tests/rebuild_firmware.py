"""Rebuild all three modified artifacts in memory; never connect to hardware."""

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))

import fw_repack
from patch_no_brightness_floor import PATCHES
from build_screen_ui_candidate import build_candidate as build_screen
from build_island_candidate import build_candidate as build_image


def read(name):
    return (ROOT / 'firmware' / name).read_bytes()


def matches(data, name):
    assert data == read(name), f'Rebuilt bytes differ: {name}'
    print(f'{hashlib.sha256(data).hexdigest()}  {name}')


for line in (ROOT / 'firmware/SHA256SUMS.txt').read_text().splitlines():
    expected, name = line.split('  ', 1)
    assert hashlib.sha256(read(name)).hexdigest() == expected, name

main = bytearray(read('main-v137-official.bin'))
for offset, old, new, _ in PATCHES:
    assert main[offset:offset + len(old)] == old
    main[offset:offset + len(new)] = new
fw_repack.p16be(main, fw_repack.OFF_CRC,
                fw_repack.crc16_modbus(main[fw_repack.HDR_LEN:]))
fw_repack.p16be(main, fw_repack.OFF_HCRC,
                fw_repack.crc16_modbus(main[:fw_repack.OFF_HCRC]))
matches(bytes(main), 'main-v137-nobrightfloor.bin')

screen, report = build_screen(
    read('screen-v120-official.bin'), date_bg_opacity=0,
    time_x_offset=-5, minute_gap=-1, standard_minute_extra=-2,
    num_indicator=True, num_caps_style=True, num_gray_fix=True,
    num_match_caps=True, num_strengthen=True, scene_colon_x_offset=-1)
assert report['program_crc_valid'] and report['header_crc_valid']
matches(screen, 'screen-v20.bin')

image, report = build_image(read('screen-image-v120-official.bin'), 128)
assert report['qgif_unchanged']
matches(image, 'screen-image-v120-alpha128.bin')
print('All six hashes and three rebuilt artifacts match.')
