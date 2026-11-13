"""Build an offline, byte-scoped transparency candidate for QK100 Mk2 v120."""

import argparse
import hashlib
import json
from pathlib import Path

from screen_assets import parse_assets, rgba

STOCK_SHA256 = '50beaa063d4a2464fb7525094c6e49a5bf8ba0ab059c61a1a70ad5c6acda5b9d'
EXPECTED = {13: (147, 99), 14: (109, 35)}
QGIF_OFFSET = 0x2A416D


def build_candidate(stock, maximum_alpha):
    if not 1 <= maximum_alpha <= 254:
        raise ValueError('maximum alpha must be between 1 and 254')
    digest = hashlib.sha256(stock).hexdigest()
    if digest != STOCK_SHA256:
        raise ValueError(f'expected the unmodified v120 image, got SHA-256 {digest}')
    assets, qgif_offset = parse_assets(stock)
    if len(assets) != 147 or qgif_offset != QGIF_OFFSET:
        raise ValueError('unexpected v120 resource layout')
    candidate = bytearray(stock)
    allowed = set()
    for index, dimensions in EXPECTED.items():
        asset = assets[index]
        if (asset.width, asset.height, asset.color_format) != (*dimensions, 5):
            raise ValueError(f'unexpected asset {index} layout')
        if any(asset.data[pos:pos + 2] != bytes(2)
               for pos in range(0, len(asset.data), 3)):
            raise ValueError(f'asset {index} is no longer all black')
        for pos in range(2, len(asset.data), 3):
            offset = asset.offset + 4 + pos
            candidate[offset] = (asset.data[pos] * maximum_alpha + 127) // 255
            allowed.add(offset)
    changed = [pos for pos, (old, new) in enumerate(zip(stock, candidate)) if old != new]
    if not changed or any(pos not in allowed for pos in changed):
        raise AssertionError('unexpected byte changes')
    if len(candidate) != len(stock) or candidate[qgif_offset:] != stock[qgif_offset:]:
        raise AssertionError('QGIF container or resource length changed')
    report = {
        'stock_sha256': digest,
        'candidate_sha256': hashlib.sha256(candidate).hexdigest(),
        'maximum_alpha': maximum_alpha,
        'changed_bytes': len(changed),
        'modified_asset_indices': list(EXPECTED),
        'qgif_offset': f'0x{qgif_offset:x}',
        'qgif_unchanged': True,
        'hardware_validated': False,
    }
    return bytes(candidate), report


def save_preview(stock, candidate, path):
    from PIL import Image, ImageDraw
    original, _ = parse_assets(stock)
    modified, _ = parse_assets(candidate)
    canvas = Image.new('RGB', (640, 310), '#d5d5d5')
    draw = ImageDraw.Draw(canvas)
    wallpaper = Image.frombytes('RGBA', (172, 320), rgba(original[2]))
    for row, index in enumerate(EXPECTED):
        y = 22 + row * 148
        for col, assets in enumerate((original, modified)):
            crop = wallpaper.crop((0, 0, 172, 125)).convert('RGB').resize((300, 125))
            shape = assets[index]
            overlay = Image.frombytes('RGBA', (shape.width, shape.height), rgba(shape))
            overlay = overlay.resize((int(shape.width * 1.6), int(shape.height * 1.1)))
            crop.paste(overlay, ((300 - overlay.width) // 2, (125 - overlay.height) // 2), overlay)
            canvas.paste(crop, (col * 320 + 10, y))
            draw.text((col * 320 + 12, y - 15),
                      f'asset {index}: ' + ('stock' if col == 0 else 'candidate'), fill='black')
    canvas.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stock', type=Path)
    parser.add_argument('--alpha', type=int, default=128)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--preview', type=Path)
    args = parser.parse_args()
    original = args.stock.read_bytes()
    candidate, report = build_candidate(original, args.alpha)
    if args.output.exists():
        parser.error(f'output already exists: {args.output}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        save_preview(original, candidate, args.preview)
    report['output'] = str(args.output.resolve())
    if args.preview:
        report['preview'] = str(args.preview.resolve())
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
