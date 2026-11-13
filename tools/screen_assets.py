"""Inspect the QK100 Mk2 screen resource image without touching hardware.

The first section contains packed LVGL-style descriptors and three bytes per
pixel. It ends at the QGIF container; the remaining container is left opaque.
"""

import argparse
import hashlib
import json
import struct
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Asset:
    index: int
    offset: int
    color_format: int
    width: int
    height: int
    data: bytes

    @property
    def size(self):
        return 4 + len(self.data)

    @property
    def sha256(self):
        return hashlib.sha256(self.data).hexdigest()


def parse_assets(blob):
    assets = []
    offset = 0
    while offset + 4 <= len(blob) and blob[offset:offset + 4] != b'QGIF':
        descriptor, = struct.unpack_from('<I', blob, offset)
        color_format = descriptor & 31
        reserved = (descriptor >> 5) & 31
        width = (descriptor >> 10) & 2047
        height = (descriptor >> 21) & 2047
        size = width * height * 3
        if (color_format not in (4, 5) or reserved != 0 or
                not 0 < width <= 512 or not 0 < height <= 512 or
                size > len(blob) - offset - 4):
            raise ValueError(f'invalid image descriptor at 0x{offset:x}')
        assets.append(Asset(len(assets), offset, color_format, width, height,
                            blob[offset + 4:offset + 4 + size]))
        offset += 4 + size
    if blob[offset:offset + 4] != b'QGIF':
        raise ValueError(f'QGIF boundary missing at 0x{offset:x}')
    return assets, offset


def compare(left, right):
    a, a_tail = parse_assets(left)
    b, b_tail = parse_assets(right)
    if len(a) != len(b):
        raise ValueError('asset counts differ; compare by identity manually')
    rows = []
    for x, y in zip(a, b):
        layout_changed = (x.color_format, x.width, x.height) != (y.color_format, y.width, y.height)
        changed = abs(len(x.data) - len(y.data)) + sum(u != v for u, v in zip(x.data, y.data))
        if layout_changed or changed:
            rows.append({'index': x.index, 'left_offset': f'0x{x.offset:x}',
                         'right_offset': f'0x{y.offset:x}',
                         'left_format': x.color_format, 'right_format': y.color_format,
                         'left_size': [x.width, x.height],
                         'right_size': [y.width, y.height],
                         'changed_bytes': changed})
    return {'left_sha256': hashlib.sha256(left).hexdigest(),
            'right_sha256': hashlib.sha256(right).hexdigest(),
            'asset_count': len(a), 'qgif_offsets': [a_tail, b_tail],
            'changed_assets': rows,
            'qgif_changed_bytes': (abs(len(left) - a_tail - len(right) + b_tail) +
                                   sum(u != v for u, v in zip(left[a_tail:], right[b_tail:])))}


def rgba(asset):
    if asset.color_format == 4:
        return b''.join(asset.data[i:i + 3] + b'\xff'
                        for i in range(0, len(asset.data), 3))
    output = bytearray(asset.width * asset.height * 4)
    for i in range(asset.width * asset.height):
        value = asset.data[3 * i] | (asset.data[3 * i + 1] << 8)
        output[4 * i:4 * i + 4] = bytes((((value >> 11) & 31) * 255 // 31,
                                       ((value >> 5) & 63) * 255 // 63,
                                       (value & 31) * 255 // 31,
                                       asset.data[3 * i + 2]))
    return bytes(output)


def contact_sheet(assets, output, start, end):
    from PIL import Image, ImageDraw

    selected = assets[start:end]
    columns, cell_w, cell_h = 6, 184, 190
    rows = (len(selected) + columns - 1) // columns
    sheet = Image.new('RGB', (columns * cell_w, rows * cell_h), '#dddddd')
    draw = ImageDraw.Draw(sheet)
    for n, asset in enumerate(selected):
        image = Image.frombytes('RGBA', (asset.width, asset.height), rgba(asset))
        image.thumbnail((cell_w - 8, cell_h - 28))
        x = (n % columns) * cell_w + (cell_w - image.width) // 2
        y = (n // columns) * cell_h + 22
        sheet.paste(image, (x, y), image)
        draw.text(((n % columns) * cell_w + 4, (n // columns) * cell_h + 3),
                  f'{asset.index}: {asset.width}x{asset.height} cf{asset.color_format}',
                  fill='black')
    sheet.save(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image', type=Path)
    parser.add_argument('--compare', type=Path)
    parser.add_argument('--contact-sheet', type=Path)
    parser.add_argument('--start', type=int, default=0)
    parser.add_argument('--end', type=int)
    args = parser.parse_args()
    blob = args.image.read_bytes()
    assets, qgif = parse_assets(blob)
    if args.contact_sheet:
        contact_sheet(assets, args.contact_sheet, args.start, args.end)
    result = {'sha256': hashlib.sha256(blob).hexdigest(), 'asset_count': len(assets),
              'qgif_offset': f'0x{qgif:x}', 'total_bytes': len(blob),
              'assets': [{'index': x.index, 'offset': f'0x{x.offset:x}',
                          'format': x.color_format, 'width': x.width,
                          'height': x.height, 'sha256': x.sha256} for x in assets]}
    if args.compare:
        result['comparison'] = compare(blob, args.compare.read_bytes())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
