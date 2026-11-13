"""Build a reversible QK100 Mk2 v120 screen app candidate."""

import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path

from capstone import CS_ARCH_RISCV, CS_MODE_RISCV32, CS_MODE_RISCVC, Cs
from build_num_font import build_num_font

STOCK_SHA256 = 'f4d0dc14baa423cbea0946b31d34cf0fe61fa383cc103d94943b5a0a7267c68f'
BASE = 0x13002000
CREATE_HOOK = 0x13037522
UPDATE_HOOK = 0x13010B4E
ISLAND_BG_HOOK = 0x1303304C
DATE_BG_HOOK = 0x130369F8
TIME_X_INITIAL = 0x1303309A
TIME_X_MODE_RESTORE = 0x13033278
MINUTE_X_HOOK = 0x13036954
ORIGINAL_MINUTE_X = bytes.fromhex('33868941')
SECOND_MINUTE_X_HOOK = 0x13036980
COLON_X_HOOK = 0x13036938
ORIGINAL_COLON_X = bytes.fromhex('62868146')
SCENE_CLOCK_RETURN = 0x13034752
ORIGINAL_SECOND_MINUTE_X = bytes.fromhex('33063b01')
NUM_C1_HOOK = 0x13010AAA
NUM_MODE_HOOK = 0x130330D0
NUM_RUNTIME_MODE_HOOK = 0x13010548
ORIGINAL_NUM_RUNTIME_MODE = bytes.fromhex('13058bf2')
ORIGINAL_NUM_HOOKS = {NUM_C1_HOOK: bytes.fromhex('37c50020'),
                      NUM_MODE_HOOK: bytes.fromhex('b7a70020')}
ORIGINAL_HOOKS = {CREATE_HOOK: bytes.fromhex('b2402244'),
                  UPDATE_HOOK: bytes.fromhex('138584f2'),
                  ISLAND_BG_HOOK: bytes.fromhex('ef30606a'),
                  DATE_BG_HOOK: bytes.fromhex('ed39c848')}
LABEL_CREATE = 0x13022FF4
LABEL_FORMAT = 0x13023D34
POSITION = 0x13012060
TEXT_FONT = 0x130366E2
TEXT_COLOR = 0x130366D0
BG_COLOR = 0x130366F2
BG_OPACITY = 0x130366EA
ISLAND_BG_OPACITY = 128
DATE_BG_OPACITY = 128
FONT_16PX = 0x1303BE24
LABEL_CLASS = 0x130455EC
HIDE_OBJECT = 0x13014EC2
SHOW_OBJECT = 0x13014F2C
NUM_X, NUM_Y = 54, 75
NUM_CAPS_X, NUM_CAPS_Y = 58, 79
NUM_OFF_COLOR_RGB565 = 0x8410
NUM_CORRECTED_Y = 76
NUM_OFF_COLOR_SWAPPED_RGB565 = 0xF39C
STOCK_LVGL_GRAY_OFFSET = 0x42E54
CAPS_ACTIVE_COLOR = 0x7EF7
CAPS_INACTIVE_COLOR = 0x18C6

ZERO, RA, SP, T0, T1, T2, S0, S1 = 0, 1, 2, 5, 6, 7, 8, 9
A0, A1, A2, A3, T3, T4, T5, T6 = 10, 11, 12, 13, 28, 29, 30, 31
S8 = 24


def signed_imm(value):
    if not -2048 <= value <= 2047:
        raise ValueError(f'immediate does not fit: {value}')
    return value & 0xfff


def i_type(opcode, funct3, rd, rs1, imm):
    return (signed_imm(imm) << 20) | (rs1 << 15) | (funct3 << 12) | (rd << 7) | opcode


def s_type(funct3, rs2, rs1, imm):
    value = signed_imm(imm)
    return ((value >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | ((value & 31) << 7) | 0x23


def j_type(rd, displacement):
    if displacement % 2 or not -(1 << 20) <= displacement < (1 << 20):
        raise ValueError(f'JAL displacement does not fit: {displacement}')
    value = displacement & 0x1fffff
    return (((value >> 20) & 1) << 31) | (((value >> 1) & 0x3ff) << 21) | (((value >> 11) & 1) << 20) | (((value >> 12) & 0xff) << 12) | (rd << 7) | 0x6f


def b_type(funct3, rs1, rs2, displacement):
    if displacement % 2 or not -4096 <= displacement <= 4094:
        raise ValueError(f'branch displacement does not fit: {displacement}')
    value = displacement & 0x1fff
    return (((value >> 12) & 1) << 31) | (((value >> 5) & 0x3f) << 25) | (rs2 << 20) | (rs1 << 15) | (funct3 << 12) | (((value >> 1) & 15) << 8) | (((value >> 11) & 1) << 7) | 0x63


class Assembler:
    def __init__(self, base):
        self.base = base
        self.data = bytearray()
        self.labels = {}
        self.fixups = []

    @property
    def pc(self):
        return self.base + len(self.data)

    def mark(self, label):
        if label in self.labels:
            raise ValueError(f'duplicate label: {label}')
        self.labels[label] = self.pc

    def emit(self, word):
        self.data += struct.pack('<I', word)

    def addi(self, rd, rs1, imm):
        self.emit(i_type(0x13, 0, rd, rs1, imm))

    def andi(self, rd, rs1, imm):
        self.emit(i_type(0x13, 7, rd, rs1, imm))

    def ret(self):
        self.emit(i_type(0x67, 0, ZERO, RA, 0))

    def lui(self, rd, upper):
        self.emit((upper << 12) | (rd << 7) | 0x37)

    def lw(self, rd, rs1, imm):
        self.emit(i_type(0x03, 2, rd, rs1, imm))

    def lh(self, rd, rs1, imm):
        self.emit(i_type(0x03, 1, rd, rs1, imm))

    def lbu(self, rd, rs1, imm):
        self.emit(i_type(0x03, 4, rd, rs1, imm))

    def sw(self, rs2, rs1, imm):
        self.emit(s_type(2, rs2, rs1, imm))

    def slli(self, rd, rs1, amount):
        self.emit(i_type(0x13, 1, rd, rs1, amount))

    def add(self, rd, rs1, rs2):
        self.emit((rs2 << 20) | (rs1 << 15) | (rd << 7) | 0x33)

    def la(self, rd, target):
        offset = len(self.data)
        self.emit(0)
        self.emit(0)
        self.fixups.append(('la', offset, rd, target))

    def jal(self, rd, target):
        offset = len(self.data)
        self.emit(0)
        self.fixups.append(('jal', offset, rd, target))

    def branch(self, funct3, rs1, rs2, target):
        offset = len(self.data)
        self.emit(0)
        self.fixups.append(('branch', offset, (funct3, rs1, rs2), target))

    def beq(self, rs1, rs2, target):
        self.branch(0, rs1, rs2, target)

    def bne(self, rs1, rs2, target):
        self.branch(1, rs1, rs2, target)

    def bgeu(self, rs1, rs2, target):
        self.branch(7, rs1, rs2, target)

    def jump(self, target):
        self.jal(ZERO, target)

    def finish(self):
        for kind, offset, registers, target in self.fixups:
            address = self.labels[target] if isinstance(target, str) else target
            pc = self.base + offset
            if kind == 'la':
                upper = ((address + 0x800) >> 12) & 0xfffff
                lower = address - (upper << 12)
                struct.pack_into('<I', self.data, offset, (upper << 12) | (registers << 7) | 0x37)
                struct.pack_into('<I', self.data, offset + 4, i_type(0x13, 0, registers, registers, lower))
            elif kind == 'jal':
                struct.pack_into('<I', self.data, offset, j_type(registers, address - pc))
            else:
                funct3, rs1, rs2 = registers
                struct.pack_into('<I', self.data, offset, b_type(funct3, rs1, rs2, address - pc))
        return bytes(self.data)


def build_candidate(stock, *, date_bg_opacity=DATE_BG_OPACITY, time_x_offset=0,
                    minute_gap=0, num_indicator=False, num_caps_style=False,
                    num_gray_fix=False, num_match_caps=False, num_strengthen=False,
                    scene_colon_x_offset=0, standard_minute_extra=0):
    if type(standard_minute_extra) is not int or standard_minute_extra not in (0, -2):
        raise ValueError('standard minute extra must be 0 or -2')
    if standard_minute_extra and not minute_gap:
        raise ValueError('standard minute extra requires minute gap hook')
    if type(scene_colon_x_offset) is not int or scene_colon_x_offset not in (0, -1, -2):
        raise ValueError('scene colon x offset must be 0, -1 or -2')
    if type(date_bg_opacity) is not int or date_bg_opacity not in (0, 128):
        raise ValueError('date background opacity must be 0 or 128')
    if type(time_x_offset) is not int or time_x_offset not in (0, -2, -3, -4, -5):
        raise ValueError('time x offset must be 0, -2, -3, -4, or -5')
    if type(minute_gap) is not int or minute_gap not in (0, -1, -3):
        raise ValueError('minute gap adjustment must be 0, -1 or -3')
    if type(num_indicator) is not bool:
        raise ValueError('num indicator must be a boolean')
    if type(num_caps_style) is not bool or (num_caps_style and not num_indicator):
        raise ValueError('num_caps_style requires num_indicator')
    if type(num_gray_fix) is not bool or (num_gray_fix and not num_caps_style):
        raise ValueError('num_gray_fix requires num_caps_style')
    if type(num_match_caps) is not bool or (num_match_caps and not num_gray_fix):
        raise ValueError('num_match_caps requires num_gray_fix')
    if type(num_strengthen) is not bool or (num_strengthen and not num_match_caps):
        raise ValueError('num_strengthen requires num_match_caps')
    digest = hashlib.sha256(stock).hexdigest()
    if digest != STOCK_SHA256:
        raise ValueError(f'expected stock v120 app, got {digest}')
    if num_gray_fix and struct.unpack_from('<H', stock, STOCK_LVGL_GRAY_OFFSET)[0] != NUM_OFF_COLOR_SWAPPED_RGB565:
        raise ValueError('stock LVGL swapped-RGB565 gray palette entry mismatch')
    if stock[:4] != b'ABIN' or struct.unpack_from('<I', stock, 12)[0] != len(stock) - 64:
        raise ValueError('unexpected ABIN header')
    if struct.unpack_from('<I', stock, 16)[0] != zlib.crc32(stock[64:]):
        raise ValueError('stock program CRC mismatch')
    if struct.unpack_from('<I', stock, 60)[0] != zlib.crc32(stock[:60]):
        raise ValueError('stock header CRC mismatch')
    for address, expected in ORIGINAL_HOOKS.items():
        if stock[address - BASE:address - BASE + 4] != expected:
            raise ValueError(f'original hook mismatch at {address:#x}')
    if minute_gap:
        for address, original in ((MINUTE_X_HOOK, ORIGINAL_MINUTE_X),
                                  (SECOND_MINUTE_X_HOOK, ORIGINAL_SECOND_MINUTE_X)):
            if stock[address - BASE:address - BASE + 4] != original:
                raise ValueError(f'original minute coordinate instruction mismatch at {address:#x}')
    if num_indicator:
        for address, expected in ORIGINAL_NUM_HOOKS.items():
            if stock[address - BASE:address - BASE + 4] != expected:
                raise ValueError(f'original NUM hook mismatch at {address:#x}')
    if scene_colon_x_offset and stock[COLON_X_HOOK - BASE:COLON_X_HOOK - BASE + 4] != ORIGINAL_COLON_X:
        raise ValueError('original colon coordinate instruction mismatch')
    if num_match_caps and stock[NUM_RUNTIME_MODE_HOOK - BASE:NUM_RUNTIME_MODE_HOOK - BASE + 4] != ORIGINAL_NUM_RUNTIME_MODE:
        raise ValueError('original runtime mode hook mismatch')

    asm = Assembler(BASE + len(stock))
    asm.mark('create')
    asm.lui(A0, 0x2000c)
    asm.lw(A0, A0, 0x60)
    asm.jal(RA, LABEL_CREATE)
    asm.sw(A0, SP, 0)
    asm.lw(A0, SP, 0)
    asm.la(A1, FONT_16PX)
    asm.jal(RA, TEXT_FONT)
    asm.lw(A0, SP, 0)
    asm.addi(A1, ZERO, -1)
    asm.jal(RA, TEXT_COLOR)
    asm.lw(A0, SP, 0)
    asm.la(A1, 'format')
    asm.lui(A2, 0x2000a)
    asm.lbu(A2, A2, 0x146)
    asm.jal(RA, LABEL_FORMAT)
    asm.lw(A0, SP, 0)
    asm.addi(A1, ZERO, 1)
    asm.lui(T0, 0x2000c)
    asm.lh(A2, T0, 0xa0)
    asm.addi(A2, A2, -4)
    asm.lh(A3, T0, 0xa2)
    asm.addi(A3, A3, 17)
    asm.jal(RA, POSITION)
    if num_indicator:
        # Keep the battery percentage immediately after the animation child.
        if num_match_caps:
            # Other theme creators reuse this battery routine with a screen
            # root parent. Never allocate a fixed-position NUM on those roots.
            asm.lui(T0, 0x2000a)
            asm.lbu(T1, T0, 0x140)
            asm.bne(T1, ZERO, 'num_create_skipped')
            asm.lbu(T1, T0, 0x14b)
            asm.addi(T2, ZERO, 2)
            asm.bgeu(T1, T2, 'num_create_skipped')
        asm.lui(A0, 0x2000c)
        asm.lw(A0, A0, 0x60)
        asm.jal(RA, LABEL_CREATE)
        asm.sw(A0, SP, 0)
        asm.lw(A0, SP, 0)
        asm.la(A1, 'num_font' if num_match_caps else FONT_16PX)
        asm.jal(RA, TEXT_FONT)
        asm.lw(A0, SP, 0)
        asm.addi(A1, ZERO, -1)
        asm.jal(RA, TEXT_COLOR)
        asm.lw(A0, SP, 0)
        asm.la(A1, 'num_text')
        asm.addi(A2, ZERO, 0)
        asm.jal(RA, LABEL_FORMAT)
        asm.lw(A0, SP, 0)
        asm.addi(A1, ZERO, 1)
        asm.addi(A2, ZERO, NUM_CAPS_X if num_caps_style else NUM_X)
        asm.addi(A3, ZERO, NUM_CORRECTED_Y if num_gray_fix else
                 (NUM_CAPS_Y if num_caps_style else NUM_Y))
        asm.jal(RA, POSITION)
        asm.jal(RA, 'num_update')
        if num_match_caps:
            asm.mark('num_create_skipped')
    asm.lw(RA, SP, 12)
    asm.lw(S0, SP, 8)
    asm.jump(0x13037526)

    asm.mark('update')
    asm.addi(SP, SP, -16)
    asm.sw(RA, SP, 12)
    asm.lui(T0, 0x2000c)
    asm.lw(T1, T0, 0xa4)
    asm.beq(T1, ZERO, 'done')
    asm.lw(T2, T1, 4)
    asm.beq(T2, ZERO, 'done')
    asm.lw(T3, T2, 8)
    asm.beq(T3, ZERO, 'done')
    asm.lw(T4, T3, 0)
    asm.lw(T5, T3, 4)
    asm.addi(T6, ZERO, 0)
    asm.mark('loop')
    asm.bgeu(T6, T5, 'done')
    asm.slli(A0, T6, 2)
    asm.add(A0, T4, A0)
    asm.lw(A1, A0, 0)
    asm.beq(A1, T1, 'found')
    asm.addi(T6, T6, 1)
    asm.jump('loop')
    asm.mark('found')
    asm.addi(T6, T6, 1)
    asm.bgeu(T6, T5, 'done')
    asm.lw(A0, A0, 4)
    asm.beq(A0, ZERO, 'done')
    asm.lw(A1, A0, 0)
    asm.la(A2, LABEL_CLASS)
    asm.bne(A1, A2, 'done')
    asm.la(A1, 'format')
    asm.lui(A2, 0x2000a)
    asm.lbu(A2, A2, 0x146)
    asm.jal(RA, LABEL_FORMAT)
    asm.mark('done')
    asm.lw(RA, SP, 12)
    asm.addi(SP, SP, 16)
    asm.addi(A0, S1, -0xd8)
    asm.jump(0x13010B52)

    # The 147x99 container sits behind the alpha-bearing island image.
    asm.mark('translucent_island_background')
    asm.addi(SP, SP, -16)
    asm.sw(RA, SP, 12)
    asm.jal(RA, BG_COLOR)
    asm.lw(A0, S0, 12)
    asm.addi(A1, ZERO, ISLAND_BG_OPACITY)
    asm.jal(RA, BG_OPACITY)
    asm.lw(RA, SP, 12)
    asm.addi(SP, SP, 16)
    asm.jump(ISLAND_BG_HOOK + 4)

    # The date pill is a separate child of the 147x99 island container.
    asm.mark('translucent_date_background')
    asm.addi(SP, SP, -16)
    asm.sw(RA, SP, 12)
    asm.jal(RA, BG_COLOR)
    asm.lw(A0, S1, 0x14)
    asm.addi(A1, ZERO, date_bg_opacity)
    asm.jal(RA, BG_OPACITY)
    asm.lw(A0, S1, 0x14)
    asm.lw(RA, SP, 12)
    asm.addi(SP, SP, 16)
    asm.jump(DATE_BG_HOOK + 4)

    if minute_gap:
        for label, original, hook in (('minute_gap', ORIGINAL_MINUTE_X, MINUTE_X_HOOK),
                                      ('second_minute_gap', ORIGINAL_SECOND_MINUTE_X, SECOND_MINUTE_X_HOOK)):
            asm.mark(label)
            asm.emit(struct.unpack('<I', original)[0])
            asm.addi(A2, A2, minute_gap)
            if standard_minute_extra:
                asm.addi(SP, SP, -16)
                asm.sw(A1, SP, 0)
                asm.sw(A3, SP, 4)
                asm.lw(A3, SP, 0x4C)
                asm.la(A1, 0x130330BA)
                asm.bne(A3, A1, label + '_restore')
                asm.addi(A2, A2, standard_minute_extra)
                asm.mark(label + '_restore')
                asm.lw(A1, SP, 0)
                asm.lw(A3, SP, 4)
                asm.addi(SP, SP, 16)
            asm.jump(hook + 4)

    if num_indicator:
        for label, hook, rd, upper in (
                ('num_c1', NUM_C1_HOOK, A0, 0x2000c),
                ('num_mode', NUM_MODE_HOOK, 15, 0x2000a)):
            asm.mark(label)
            asm.addi(SP, SP, -16)
            asm.sw(RA, SP, 12)
            asm.jal(RA, 'num_update')
            asm.lw(RA, SP, 12)
            asm.addi(SP, SP, 16)
            asm.lui(rd, upper)
            asm.jump(hook + 4)
        if num_match_caps:
            asm.mark('num_runtime_mode')
            asm.addi(SP, SP, -16)
            asm.sw(RA, SP, 12)
            asm.jal(RA, 'num_update')
            asm.lw(RA, SP, 12)
            asm.addi(SP, SP, 16)
            asm.emit(struct.unpack('<I', ORIGINAL_NUM_RUNTIME_MODE)[0])
            asm.jump(NUM_RUNTIME_MODE_HOOK + 4)

        asm.mark('num_update')
        saved = (RA, T0, T1, T2, A0, A1, A2, A3, 14, 15, 16, 17, T3, T4, T5, T6)
        num_frame_size = 80 if num_caps_style else 64
        asm.addi(SP, SP, -num_frame_size)
        for index, register in enumerate(saved):
            asm.sw(register, SP, index * 4)
        if num_match_caps:
            # Theme switches delete old UI children; reject the theme before
            # following an animation pointer left over from that old screen.
            asm.lui(T0, 0x2000a)
            asm.lbu(T1, T0, 0x140)
            asm.bne(T1, ZERO, 'num_done')
            asm.lbu(T1, T0, 0x14b)
            asm.addi(T2, ZERO, 2)
            asm.bgeu(T1, T2, 'num_done')
        asm.lui(T0, 0x2000c)
        asm.lw(T1, T0, 0xa4)
        asm.beq(T1, ZERO, 'num_done')
        asm.lw(T2, T1, 4)
        asm.beq(T2, ZERO, 'num_done')
        asm.lw(T3, T2, 8)
        asm.beq(T3, ZERO, 'num_done')
        asm.lw(T4, T3, 0)
        asm.beq(T4, ZERO, 'num_done')
        asm.lw(T5, T3, 4)
        asm.addi(T6, ZERO, 0)
        asm.mark('num_loop')
        asm.bgeu(T6, T5, 'num_done')
        asm.slli(A0, T6, 2)
        asm.add(A0, T4, A0)
        asm.lw(A1, A0, 0)
        asm.beq(A1, T1, 'num_found')
        asm.addi(T6, T6, 1)
        asm.jump('num_loop')
        asm.mark('num_found')
        asm.addi(T6, T6, 2)
        asm.bgeu(T6, T5, 'num_done')
        asm.lw(A0, A0, 8)
        asm.beq(A0, ZERO, 'num_done')
        asm.lw(A1, A0, 0)
        asm.la(A2, LABEL_CLASS)
        asm.bne(A1, A2, 'num_done')
        if num_caps_style:
            asm.sw(A0, SP, 64)
        asm.lui(T0, 0x2000a)
        asm.lbu(T1, T0, 0x14c)
        asm.addi(T2, ZERO, 2)
        asm.bne(T1, T2, 'num_hide')
        asm.lbu(T1, T0, 0x141)
        asm.andi(T1, T1, 1)
        if num_caps_style:
            asm.beq(T1, ZERO, 'num_gray')
            if num_match_caps:
                asm.la(A1, CAPS_ACTIVE_COLOR)
            else:
                asm.addi(A1, ZERO, -1)
            asm.jal(RA, TEXT_COLOR)
            asm.jump('num_show')
            asm.mark('num_gray')
            asm.la(A1, CAPS_INACTIVE_COLOR if num_match_caps else
                   (NUM_OFF_COLOR_SWAPPED_RGB565 if num_gray_fix else NUM_OFF_COLOR_RGB565))
            asm.jal(RA, TEXT_COLOR)
            asm.mark('num_show')
            asm.lw(A0, SP, 64)
        else:
            asm.beq(T1, ZERO, 'num_hide')
        asm.addi(A1, ZERO, 1)
        asm.jal(RA, SHOW_OBJECT)
        asm.jump('num_done')
        asm.mark('num_hide')
        asm.addi(A1, ZERO, 1)
        asm.jal(RA, HIDE_OBJECT)
        asm.mark('num_done')
        for index, register in reversed(tuple(enumerate(saved))):
            asm.lw(register, SP, index * 4)
        asm.addi(SP, SP, num_frame_size)
        asm.ret()

    asm.mark('format')
    asm.data += b'%d%%' + bytes(1)
    asm.data += bytes((-len(asm.data)) % 4)
    if num_indicator:
        asm.mark('num_text')
        asm.data += b'NUM' + bytes(1)
    font_report = None
    if num_match_caps:
        asm.data += bytes((-len(asm.data)) % 4)
        asm.mark('num_font')
        font_blob, font_report = build_num_font(stock, asm.pc, strengthen=num_strengthen)
        asm.data += font_blob
        asm.data += bytes((-len(asm.data)) % 4)
    if scene_colon_x_offset:
        # Append after existing font/data to preserve all v17 injected addresses.
        # Clock creator saves its caller RA at sp+0x3C. Only the scene creator
        # has return address 0x13034752; standard and unknown callers keep x.
        # a2/a3 are exactly the registers overwritten by the original 4 bytes.
        asm.mark('scene_colon_x')
        asm.lw(A3, SP, 0x3C)
        asm.la(A2, SCENE_CLOCK_RETURN)
        asm.bne(A3, A2, 'colon_original_x')
        asm.addi(A2, S8, scene_colon_x_offset)
        asm.jump('colon_resume')
        asm.mark('colon_original_x')
        asm.addi(A2, S8, 0)
        asm.mark('colon_resume')
        asm.addi(A3, ZERO, 0)
        asm.jump(COLON_X_HOOK + 4)
    code = asm.finish()
    candidate = bytearray(stock + code)
    coordinate_patches = (
        (TIME_X_INITIAL, bytes.fromhex('a90b'),
         bytes.fromhex({-2: 'a10b', -3: '9d0b', -4: '990b', -5: '950b'}[time_x_offset]) if time_x_offset else bytes.fromhex('a90b')),
        (TIME_X_MODE_RESTORE, bytes.fromhex('a945'),
         bytes.fromhex({-2: 'a145', -3: '9d45', -4: '9945', -5: '9545'}[time_x_offset]) if time_x_offset else bytes.fromhex('a945')),
    )
    if time_x_offset:
        for address, original, replacement in coordinate_patches:
            offset = address - BASE
            if stock[offset:offset + 2] != original:
                raise ValueError(f'original time coordinate mismatch at {address:#x}')
            candidate[offset:offset + 2] = replacement
    for hook, label in ((CREATE_HOOK, 'create'), (UPDATE_HOOK, 'update'),
                        (ISLAND_BG_HOOK, 'translucent_island_background'),
                        (DATE_BG_HOOK, 'translucent_date_background')):
        struct.pack_into('<I', candidate, hook - BASE,
                         j_type(ZERO, asm.labels[label] - hook))
    if minute_gap:
        struct.pack_into('<I', candidate, MINUTE_X_HOOK - BASE,
                         j_type(ZERO, asm.labels['minute_gap'] - MINUTE_X_HOOK))
        struct.pack_into('<I', candidate, SECOND_MINUTE_X_HOOK - BASE,
                         j_type(ZERO, asm.labels['second_minute_gap'] - SECOND_MINUTE_X_HOOK))
    if num_indicator:
        for hook, label in ((NUM_C1_HOOK, 'num_c1'),
                            (NUM_MODE_HOOK, 'num_mode')):
            struct.pack_into('<I', candidate, hook - BASE,
                             j_type(ZERO, asm.labels[label] - hook))
    if num_match_caps:
        struct.pack_into('<I', candidate, NUM_RUNTIME_MODE_HOOK - BASE,
                         j_type(ZERO, asm.labels['num_runtime_mode'] - NUM_RUNTIME_MODE_HOOK))
    if scene_colon_x_offset:
        struct.pack_into('<I', candidate, COLON_X_HOOK - BASE,
                         j_type(ZERO, asm.labels['scene_colon_x'] - COLON_X_HOOK))
    struct.pack_into('<I', candidate, 12, len(candidate) - 64)
    struct.pack_into('<I', candidate, 16, zlib.crc32(candidate[64:]))
    struct.pack_into('<I', candidate, 60, zlib.crc32(candidate[:60]))
    decoder = Cs(CS_ARCH_RISCV, CS_MODE_RISCV32 | CS_MODE_RISCVC)
    instructions = list(decoder.disasm(code[:asm.labels['format'] - asm.base], asm.base))
    if sum(ins.size for ins in instructions) != asm.labels['format'] - asm.base:
        raise AssertionError('injected code does not disassemble completely')
    changed = [i for i, (before, after) in enumerate(zip(stock, candidate)) if before != after]
    allowed = set(range(12, 20)) | set(range(60, 64))
    for address in ORIGINAL_HOOKS:
        allowed.update(range(address - BASE, address - BASE + 4))
    if time_x_offset:
        for address, _, _ in coordinate_patches:
            allowed.update(range(address - BASE, address - BASE + 2))
    if minute_gap:
        for address in (MINUTE_X_HOOK, SECOND_MINUTE_X_HOOK):
            allowed.update(range(address - BASE, address - BASE + 4))
    if num_indicator:
        for address in ORIGINAL_NUM_HOOKS:
            allowed.update(range(address - BASE, address - BASE + 4))
    if num_match_caps:
        allowed.update(range(NUM_RUNTIME_MODE_HOOK - BASE, NUM_RUNTIME_MODE_HOOK - BASE + 4))
    if scene_colon_x_offset:
        allowed.update(range(COLON_X_HOOK - BASE, COLON_X_HOOK - BASE + 4))
    if set(changed) - allowed:
        raise AssertionError('unrelated original bytes changed')
    report = {'stock_sha256': digest,
              'candidate_sha256': hashlib.sha256(candidate).hexdigest(),
              'original_length': len(stock), 'candidate_length': len(candidate),
              'injected_addresses': {key: f'{value:#x}' for key, value in asm.labels.items()},
              'modified_original_offsets': [f'{i:#x}' for i in sorted(changed)],
              'program_crc_valid': struct.unpack_from('<I', candidate, 16)[0] == zlib.crc32(candidate[64:]),
              'header_crc_valid': struct.unpack_from('<I', candidate, 60)[0] == zlib.crc32(candidate[:60]),
              'date_bg_opacity': date_bg_opacity,
              'time_x_offset': time_x_offset,
              'minute_gap': minute_gap,
              'standard_minute_extra': standard_minute_extra,
              'num_indicator': num_indicator,
              'num_caps_style': num_caps_style,
              'num_gray_fix': num_gray_fix,
              'num_match_caps': num_match_caps, 'num_font': font_report,
              'num_strengthen': num_strengthen,
              'scene_colon_x_offset': scene_colon_x_offset,
              'hardware_validated': False}
    return bytes(candidate), report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stock', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--date-opacity', type=int, choices=(0, 128),
                        default=DATE_BG_OPACITY,
                        help='Date child background opacity; 0 avoids adding a second black layer.')
    parser.add_argument('--time-x-offset', type=int, choices=(0, -2, -3, -4, -5), default=0,
                        help='Optical time shift in pixels; -2/-3/-4/-5 preserve an eight/seven/six/five-pixel left inset.')
    parser.add_argument('--minute-gap', type=int, choices=(0, -1, -3), default=0,
                        help='Shift both minute digits together without moving the colon.')
    parser.add_argument('--standard-minute-extra', type=int, choices=(0, -2), default=0)
    parser.add_argument('--scene-colon-x-offset', type=int, choices=(0, -1, -2), default=0,
                        help='Shift only the scene clock colon left by one or two pixels.')
    parser.add_argument('--num-indicator', action='store_true',
                        help='Show NUM in the full status layout while Num Lock is on.')
    parser.add_argument('--num-caps-style', action='store_true',
                        help='Place NUM beside CAPS and use white-on/gray-off instead of hiding it.')
    parser.add_argument('--num-gray-fix', action='store_true',
                        help='Use the stock swapped-RGB565 gray and raise NUM three pixels from v14.')
    parser.add_argument('--num-match-caps', action='store_true',
                        help='Match CAPS glyph height/colors and guard other screen modes.')
    parser.add_argument('--num-strengthen', action='store_true',
                        help='Increase NUM glyph coverage to reduce its gray appearance.')
    args = parser.parse_args()
    if args.output.exists():
        parser.error(f'output already exists: {args.output}')
    candidate, report = build_candidate(args.stock.read_bytes(),
                                        date_bg_opacity=args.date_opacity,
                                        time_x_offset=args.time_x_offset,
                                        minute_gap=args.minute_gap,
                                        num_indicator=args.num_indicator,
                                        num_caps_style=args.num_caps_style,
                                        num_gray_fix=args.num_gray_fix,
                                        num_match_caps=args.num_match_caps,
                                        num_strengthen=args.num_strengthen,
                                        scene_colon_x_offset=args.scene_colon_x_offset,
                                        standard_minute_extra=args.standard_minute_extra)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(candidate)
    report['output'] = str(args.output.resolve())
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
