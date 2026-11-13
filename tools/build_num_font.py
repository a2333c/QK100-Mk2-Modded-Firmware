"""Clone the stock uncompressed LVGL font, matching CAPS' 11-pixel glyph height."""

import struct

BASE = 0x13002000
FONT = 0x1303BE24


def build_num_font(stock, destination, *, strengthen=False):
    def read(address, size):
        offset = address - BASE
        if not 0 <= offset <= len(stock) - size:
            raise ValueError('font read outside pinned stock image')
        return stock[offset:offset + size]

    font = bytearray(read(FONT, 28))
    descriptor_address, = struct.unpack_from('<I', font, 16)
    descriptor = bytearray(read(descriptor_address, 24))
    bitmap_address, glyph_address, cmaps_address, _kern, _scale, bits, _cache = struct.unpack(
        '<4I2HI', descriptor)
    if ((bits >> 9) & 15) != 4 or bits >> 14:
        raise ValueError('requires the stock uncompressed 4bpp font')
    cmaps = []
    glyph_count = 0
    for index in range(bits & 511):
        raw = read(cmaps_address + index * 20, 20)
        first, length, start = struct.unpack_from('<IHH', raw)
        list_count, kind = struct.unpack_from('<HB', raw, 16)
        if kind not in (2, 3):
            raise ValueError('unexpected stock font cmap')
        glyph_count = max(glyph_count, start + (length if kind == 2 else list_count))
        cmaps.append((first, length, start, kind))
    glyphs = bytearray(read(glyph_address, glyph_count * 8))
    bitmap_length = max((struct.unpack_from('<I', glyphs, i * 8)[0] & 0xfffff) +
                        (glyphs[i * 8 + 4] * glyphs[i * 8 + 5] + 1) // 2
                        for i in range(glyph_count))
    bitmap = bytearray(read(bitmap_address, bitmap_length))
    changed = []
    for char in 'NUM':
        matches = [start + ord(char) - first for first, length, start, kind in cmaps
                   if kind == 2 and first <= ord(char) < first + length]
        if len(matches) != 1:
            raise ValueError('NUM character lacks an unambiguous stock glyph')
        index = matches[0]
        word, width, height, x_offset, y_offset = struct.unpack_from('<IBBbb', glyphs, index * 8)
        if height != 10:
            raise ValueError('unexpected source NUM cap height')
        offset = word & 0xfffff
        pixels = [(bitmap[offset + p // 2] >> (4 if p % 2 == 0 else 0)) & 15
                  for p in range(width * height)]
        resized = []
        denominator = 22
        for y in range(11):
            source = (2 * y + 1) * height - 11
            lower, fraction = divmod(source, denominator)
            y0, y1 = max(0, min(height - 1, lower)), max(0, min(height - 1, lower + 1))
            for x in range(width):
                resized.append((pixels[y0 * width + x] * (denominator - fraction) +
                                pixels[y1 * width + x] * fraction + denominator // 2) // denominator)
        if strengthen:
            resized = [min(15, (alpha * 5 + 2) // 4) for alpha in resized]
        new_offset = len(bitmap)
        for p in range(0, len(resized), 2):
            bitmap.append((resized[p] << 4) | (resized[p + 1] if p + 1 < len(resized) else 0))
        struct.pack_into('<IBBbb', glyphs, index * 8,
                         (word & 0xfff00000) | new_offset, width, 11, x_offset, y_offset)
        changed.append({'char': char, 'index': index, 'width': width, 'height': 11,
                        'advance': (word >> 20) / 16})
    glyph_offset = 28 + 24
    bitmap_offset = glyph_offset + len(glyphs)
    struct.pack_into('<I', font, 16, destination + 28)
    struct.pack_into('<II', descriptor, 0, destination + bitmap_offset, destination + glyph_offset)
    # The original cmaps, kerning and glyph-id cache remain valid: glyph ids
    # and advances are unchanged. Only NUM bitmap offsets and heights differ.
    return bytes(font + descriptor + glyphs + bitmap), {
        'address': hex(destination), 'glyph_count': glyph_count,
        'line_height': struct.unpack_from('<H', font, 8)[0],
        'baseline': struct.unpack_from('<H', font, 10)[0], 'glyphs': changed}
