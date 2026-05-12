from __future__ import annotations

import sys
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image


class TlgDecodeError(Exception):
    """Raised when a file is not a supported TLG image or cannot be decoded."""


TLG0_MAGIC = b"TLG0.0\x00sds\x1a"
TLG5_MAGIC = b"TLG5.0\x00raw\x1a"
TLG6_MAGIC = b"TLG6.0\x00raw\x1a"
MASK32 = 0xFFFFFFFF
W_BLOCK_SIZE = 8
H_BLOCK_SIZE = 8
GOLOMB_N_COUNT = 4
LEADING_ZERO_TABLE_BITS = 12
LEADING_ZERO_TABLE_SIZE = 1 << LEADING_ZERO_TABLE_BITS


@dataclass(slots=True)
class _Tlg6Header:
    channel_count: int
    data_flags: int
    color_type: int
    external_golomb_table: int
    image_width: int
    image_height: int
    max_bit_length: int

    @property
    def x_block_count(self) -> int:
        return ((self.image_width - 1) // W_BLOCK_SIZE) + 1

    @property
    def y_block_count(self) -> int:
        return ((self.image_height - 1) // H_BLOCK_SIZE) + 1


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0

    def read(self, size: int) -> bytes:
        if self.pos + size > len(self.data):
            raise TlgDecodeError("TLG 文件数据不完整。")
        out = self.data[self.pos:self.pos + size]
        self.pos += size
        return out

    def read_u8(self) -> int:
        return self.read(1)[0]

    def read_u32(self) -> int:
        return int.from_bytes(self.read(4), "little", signed=False)

    def skip(self, size: int) -> None:
        self.read(size)


def _u8(v: int) -> int:
    return v & 0xFF


def _read_u32_at(data: bytes | bytearray, offset: int) -> int:
    # The original C++ reader performs little-endian unaligned uint32 reads.
    # Pad short reads at the end so Python behaves safely on valid-but-tight buffers.
    if offset < 0:
        return 0
    chunk = data[offset:offset + 4]
    if len(chunk) < 4:
        chunk = bytes(chunk) + b"\x00" * (4 - len(chunk))
    return int.from_bytes(chunk, "little", signed=False)


def _lzss_decompress(source: bytes | bytearray, output_size: int, initial_text: bytes | bytearray | None = None) -> bytearray:
    text = bytearray(4096)
    if initial_text:
        text[:min(len(initial_text), 4096)] = initial_text[:4096]
    text_offset = 0
    out = bytearray(output_size)
    out_pos = 0
    in_pos = 0
    flags = 0
    src_len = len(source)

    while in_pos < src_len and out_pos < output_size:
        flags >>= 1
        if (flags & 0x100) != 0x100:
            flags = source[in_pos] | 0xFF00
            in_pos += 1
            if in_pos > src_len:
                break

        if (flags & 1) == 1:
            if in_pos + 2 > src_len:
                break
            x0 = source[in_pos]
            x1 = source[in_pos + 1]
            in_pos += 2
            position = x0 | ((x1 & 0x0F) << 8)
            length = 3 + ((x1 & 0xF0) >> 4)
            if length == 18:
                if in_pos >= src_len:
                    break
                length += source[in_pos]
                in_pos += 1
            for _ in range(length):
                if out_pos >= output_size:
                    break
                c = text[position]
                out[out_pos] = c
                out_pos += 1
                text[text_offset] = c
                text_offset = (text_offset + 1) & 0xFFF
                position = (position + 1) & 0xFFF
        else:
            if in_pos >= src_len:
                break
            c = source[in_pos]
            in_pos += 1
            out[out_pos] = c
            out_pos += 1
            text[text_offset] = c
            text_offset = (text_offset + 1) & 0xFFF

    return out


def _choose_reader(reader: _Reader) -> Callable[[_Reader], Image.Image]:
    for magic, func in ((TLG0_MAGIC, _read_tlg0), (TLG5_MAGIC, _read_tlg5), (TLG6_MAGIC, _read_tlg6)):
        if reader.data.startswith(magic, reader.pos):
            reader.pos += len(magic)
            return func
    raise TlgDecodeError("不是支持的 TLG0/TLG5/TLG6 图像。")


def _image_from_pixels(width: int, height: int, pixels: list[int]) -> Image.Image:
    # Pixel integers are packed as little-endian RGBA: R | G<<8 | B<<16 | A<<24.
    # Building an array in C is much faster than assigning every byte in Python.
    if sys.byteorder == "little":
        raw = array("I", (p & MASK32 for p in pixels)).tobytes()
        return Image.frombytes("RGBA", (width, height), raw)

    raw = bytearray(width * height * 4)
    j = 0
    for p in pixels:
        raw[j] = p & 0xFF
        raw[j + 1] = (p >> 8) & 0xFF
        raw[j + 2] = (p >> 16) & 0xFF
        raw[j + 3] = (p >> 24) & 0xFF
        j += 4
    return Image.frombytes("RGBA", (width, height), bytes(raw))


def _read_tlg0(reader: _Reader) -> Image.Image:
    # TLG0 is a container. The wrapped raw TLG stream follows this size field.
    _raw_data_size = reader.read_u32()
    nested = _choose_reader(reader)
    image = nested(reader)
    # Optional chunks/tags may follow; they are metadata and not needed for compositing.
    return image


def _read_tlg5(reader: _Reader) -> Image.Image:
    channel_count = reader.read_u8()
    width = reader.read_u32()
    height = reader.read_u32()
    block_height = reader.read_u32()
    if channel_count not in (3, 4):
        raise TlgDecodeError(f"不支持的 TLG5 通道数: {channel_count}")
    if width <= 0 or height <= 0 or block_height <= 0:
        raise TlgDecodeError("TLG5 图像尺寸无效。")

    block_count = (height - 1) // block_height + 1
    reader.skip(4 * block_count)

    pixels = [0] * (width * height)
    lzss_text = bytearray(4096)
    lzss_offset = 0

    def decompress_with_shared_state(source: bytes, output_size: int) -> bytearray:
        nonlocal lzss_text, lzss_offset
        out = bytearray(output_size)
        out_pos = 0
        in_pos = 0
        flags = 0
        src_len = len(source)
        while in_pos < src_len and out_pos < output_size:
            flags >>= 1
            if (flags & 0x100) != 0x100:
                flags = source[in_pos] | 0xFF00
                in_pos += 1
            if (flags & 1) == 1:
                if in_pos + 2 > src_len:
                    break
                x0 = source[in_pos]
                x1 = source[in_pos + 1]
                in_pos += 2
                position = x0 | ((x1 & 0x0F) << 8)
                length = 3 + ((x1 & 0xF0) >> 4)
                if length == 18:
                    if in_pos >= src_len:
                        break
                    length += source[in_pos]
                    in_pos += 1
                for _ in range(length):
                    if out_pos >= output_size:
                        break
                    c = lzss_text[position]
                    out[out_pos] = c
                    out_pos += 1
                    lzss_text[lzss_offset] = c
                    lzss_offset = (lzss_offset + 1) & 0xFFF
                    position = (position + 1) & 0xFFF
            else:
                if in_pos >= src_len:
                    break
                c = source[in_pos]
                in_pos += 1
                out[out_pos] = c
                out_pos += 1
                lzss_text[lzss_offset] = c
                lzss_offset = (lzss_offset + 1) & 0xFFF
        return out

    for block_y in range(0, height, block_height):
        channel_data: list[bytearray] = []
        output_size = width * block_height
        for _channel in range(channel_count):
            mark = reader.read_u8()
            block_size = reader.read_u32()
            data = reader.read(block_size)
            if mark == 0:
                block = decompress_with_shared_state(data, output_size)
            else:
                block = bytearray(data[:output_size])
                if len(block) < output_size:
                    block.extend(b"\x00" * (output_size - len(block)))
            channel_data.append(block)

        max_y = min(block_y + block_height, height)
        use_alpha = channel_count == 4
        for y in range(block_y, max_y):
            prev_red = prev_green = prev_blue = prev_alpha = 0
            block_y_shift = (y - block_y) * width
            prev_y_shift = (y - 1) * width
            y_shift = y * width
            for x in range(width):
                red = channel_data[2][block_y_shift + x]
                green = channel_data[1][block_y_shift + x]
                blue = channel_data[0][block_y_shift + x]
                alpha = channel_data[3][block_y_shift + x] if use_alpha else 0

                red = _u8(red + green)
                blue = _u8(blue + green)

                prev_red = _u8(prev_red + red)
                prev_green = _u8(prev_green + green)
                prev_blue = _u8(prev_blue + blue)
                prev_alpha = _u8(prev_alpha + alpha)

                out_red = prev_red
                out_green = prev_green
                out_blue = prev_blue
                out_alpha = prev_alpha

                if y > 0:
                    above = pixels[prev_y_shift + x]
                    out_red = _u8(out_red + (above & 0xFF))
                    out_green = _u8(out_green + ((above >> 8) & 0xFF))
                    out_blue = _u8(out_blue + ((above >> 16) & 0xFF))
                    out_alpha = _u8(out_alpha + ((above >> 24) & 0xFF))

                if not use_alpha:
                    out_alpha = 0xFF

                pixels[y_shift + x] = out_red | (out_green << 8) | (out_blue << 16) | (out_alpha << 24)

    return _image_from_pixels(width, height, pixels)


def _build_tlg6_tables() -> tuple[list[int], list[list[int]]]:
    leading_zero_table = [0] * LEADING_ZERO_TABLE_SIZE
    for i in range(LEADING_ZERO_TABLE_SIZE):
        cnt = 0
        j = 1
        while j != LEADING_ZERO_TABLE_SIZE and not (i & j):
            j <<= 1
            cnt += 1
        cnt += 1
        if j == LEADING_ZERO_TABLE_SIZE:
            cnt = 0
        leading_zero_table[i] = cnt

    compression_table = [
        [3, 7, 15, 27, 63, 108, 223, 448, 130],
        [3, 5, 13, 24, 51, 95, 192, 384, 257],
        [2, 5, 12, 21, 39, 86, 155, 320, 384],
        [2, 3, 9, 18, 33, 61, 129, 258, 511],
    ]
    bit_length_table = [[0] * GOLOMB_N_COUNT for _ in range(GOLOMB_N_COUNT * 2 * 128)]
    for n in range(GOLOMB_N_COUNT):
        a = 0
        for bit_len, repeat in enumerate(compression_table[n]):
            for _ in range(repeat):
                bit_length_table[a][n] = bit_len
                a += 1
    return leading_zero_table, bit_length_table


_LEADING_ZERO_TABLE, _GOLOMB_BIT_LENGTH_TABLE = _build_tlg6_tables()


def _decode_golomb_values(pixel_buf: bytearray, channel_offset: int, pixel_count: int, bit_pool: bytes) -> None:
    # The TLG6 bitstream is read LSB-first. Four bytes of padding keep uint32 reads safe.
    pool = bit_pool + b"\x00\x00\x00\x00"
    n = GOLOMB_N_COUNT - 1
    a = 0
    bit_pos = 1
    byte_pos = 0
    zero = 0 if (pool[0] & 1) else 1
    pixel_index = 0

    while pixel_index < pixel_count:
        t = _read_u32_at(pool, byte_pos) >> bit_pos
        b = _LEADING_ZERO_TABLE[t & (LEADING_ZERO_TABLE_SIZE - 1)]
        bit_count = b
        while not b:
            bit_count += LEADING_ZERO_TABLE_BITS
            bit_pos += LEADING_ZERO_TABLE_BITS
            byte_pos += bit_pos >> 3
            bit_pos &= 7
            t = _read_u32_at(pool, byte_pos) >> bit_pos
            b = _LEADING_ZERO_TABLE[t & (LEADING_ZERO_TABLE_SIZE - 1)]
            bit_count += b

        bit_pos += b
        byte_pos += bit_pos >> 3
        bit_pos &= 7

        bit_count -= 1
        count = 1 << bit_count
        t = _read_u32_at(pool, byte_pos)
        count += (t >> bit_pos) & (count - 1)

        bit_pos += bit_count
        byte_pos += bit_pos >> 3
        bit_pos &= 7

        if zero:
            for _ in range(count):
                if pixel_index >= pixel_count:
                    break
                pixel_buf[pixel_index * 4 + channel_offset] = 0
                pixel_index += 1
        else:
            for _ in range(count):
                if pixel_index >= pixel_count:
                    break
                t = _read_u32_at(pool, byte_pos) >> bit_pos
                if t:
                    b = _LEADING_ZERO_TABLE[t & (LEADING_ZERO_TABLE_SIZE - 1)]
                    bit_count = b
                    while not b:
                        bit_count += LEADING_ZERO_TABLE_BITS
                        bit_pos += LEADING_ZERO_TABLE_BITS
                        byte_pos += bit_pos >> 3
                        bit_pos &= 7
                        t = _read_u32_at(pool, byte_pos) >> bit_pos
                        b = _LEADING_ZERO_TABLE[t & (LEADING_ZERO_TABLE_SIZE - 1)]
                        bit_count += b
                    bit_count -= 1
                else:
                    byte_pos += 5
                    bit_count = pool[byte_pos - 1]
                    bit_pos = 0
                    t = _read_u32_at(pool, byte_pos)
                    b = 0

                if a >= len(_GOLOMB_BIT_LENGTH_TABLE):
                    raise TlgDecodeError("TLG6 Golomb 数据异常。")
                k = _GOLOMB_BIT_LENGTH_TABLE[a][n]
                v = (bit_count << k) + ((t >> b) & ((1 << k) - 1))
                sign = (v & 1) - 1
                v >>= 1
                a += v
                pixel_buf[pixel_index * 4 + channel_offset] = _u8((v ^ sign) + sign + 1)
                pixel_index += 1

                bit_pos += b + k
                byte_pos += bit_pos >> 3
                bit_pos &= 7

                n -= 1
                if n < 0:
                    a >>= 1
                    n = GOLOMB_N_COUNT - 1
        zero ^= 1


def _make_gt_mask(a: int, b: int) -> int:
    a &= MASK32
    b &= MASK32
    tmp2 = (~b) & MASK32
    tmp = ((a & tmp2) + (((a ^ tmp2) >> 1) & 0x7F7F7F7F)) & 0x80808080
    return (((tmp >> 7) + 0x7F7F7F7F) ^ 0x7F7F7F7F) & MASK32


def _packed_bytes_add(a: int, b: int) -> int:
    a &= MASK32
    b &= MASK32
    return (a + b - ((((a & b) << 1) + ((a ^ b) & 0xFEFEFEFE)) & 0x01010100)) & MASK32


def _med(a: int, b: int, c: int, v: int) -> int:
    a &= MASK32
    b &= MASK32
    c &= MASK32
    v &= MASK32
    aa_gt_bb = _make_gt_mask(a, b)
    x = (a ^ b) & aa_gt_bb
    aa = (x ^ a) & MASK32
    bb = (x ^ b) & MASK32
    n = _make_gt_mask(c, bb)
    nn = _make_gt_mask(aa, c)
    m = (~(n | nn)) & MASK32
    base = ((n & aa) | (nn & bb) | (((bb & m) - (c & m) + (aa & m)) & MASK32)) & MASK32
    return _packed_bytes_add(base, v)


def _avg(a: int, b: int, _c: int, v: int) -> int:
    a &= MASK32
    b &= MASK32
    v &= MASK32
    base = ((a & b) + (((a ^ b) & 0xFEFEFEFE) >> 1) + ((a ^ b) & 0x01010101)) & MASK32
    return _packed_bytes_add(base, v)


def _transform(kind: int, r: int, g: int, b: int) -> tuple[int, int, int]:
    kind &= 0x0F
    if kind == 0:
        pass
    elif kind == 1:
        r = _u8(r + g); b = _u8(b + g)
    elif kind == 2:
        g = _u8(g + b); r = _u8(r + g)
    elif kind == 3:
        g = _u8(g + r); b = _u8(b + g)
    elif kind == 4:
        b = _u8(b + r); g = _u8(g + b); r = _u8(r + g)
    elif kind == 5:
        b = _u8(b + r); g = _u8(g + b)
    elif kind == 6:
        b = _u8(b + g)
    elif kind == 7:
        g = _u8(g + b)
    elif kind == 8:
        r = _u8(r + g)
    elif kind == 9:
        r = _u8(r + b); g = _u8(g + r); b = _u8(b + g)
    elif kind == 10:
        b = _u8(b + r); g = _u8(g + r)
    elif kind == 11:
        r = _u8(r + b); g = _u8(g + b)
    elif kind == 12:
        r = _u8(r + b); g = _u8(g + r)
    elif kind == 13:
        b = _u8(b + g); r = _u8(r + b); g = _u8(g + r)
    elif kind == 14:
        g = _u8(g + r); b = _u8(b + g); r = _u8(r + b)
    elif kind == 15:
        g = _u8(g + (b << 1)); r = _u8(r + (b << 1))
    return r, g, b


def _decode_line(
    prev_line: list[int],
    current_line: list[int],
    width: int,
    start_block: int,
    block_limit: int,
    filter_types: bytearray,
    skip_block_units: int,
    pixel_buf: bytearray,
    in_index: int,
    initialp: int,
    odd_skip: int,
    direction: int,
    channel_count: int,
) -> None:
    prev_index = start_block * W_BLOCK_SIZE
    cur_index = start_block * W_BLOCK_SIZE
    if start_block:
        p = current_line[cur_index - 1]
        up = prev_line[prev_index - 1]
    else:
        p = up = initialp

    in_index += skip_block_units * start_block
    step = 1 if (direction & 1) else -1

    for i in range(start_block, block_limit):
        w = width - i * W_BLOCK_SIZE
        if w > W_BLOCK_SIZE:
            w = W_BLOCK_SIZE
        ww = w
        if step == -1:
            in_index += ww - 1
        if i & 1:
            in_index += odd_skip * ww

        filter_func = _avg if (filter_types[i] & 1) else _med
        transform_kind = filter_types[i] >> 1

        for _ in range(w):
            val = _read_u32_at(pixel_buf, in_index * 4)
            a = (val >> 24) & 0xFF
            r = (val >> 16) & 0xFF
            g = (val >> 8) & 0xFF
            b = val & 0xFF
            r, g, b = _transform(transform_kind, r, g, b)

            u = prev_line[prev_index] if 0 <= prev_index < width else 0
            v = ((b << 16) & 0xFF0000) | ((g << 8) & 0xFF00) | (r & 0xFF) | ((a << 24) & 0xFF000000)
            p = filter_func(p, u, up, v)
            if channel_count == 3:
                p = (p | 0xFF000000) & MASK32
            up = u
            if 0 <= cur_index < width:
                current_line[cur_index] = p
            cur_index += 1
            prev_index += 1
            in_index += step

        in_index += skip_block_units + (-ww if step == 1 else 1)
        if i & 1:
            in_index -= odd_skip * ww


def _read_tlg6(reader: _Reader) -> Image.Image:
    header = _Tlg6Header(
        channel_count=reader.read_u8(),
        data_flags=reader.read_u8(),
        color_type=reader.read_u8(),
        external_golomb_table=reader.read_u8(),
        image_width=reader.read_u32(),
        image_height=reader.read_u32(),
        max_bit_length=reader.read_u32(),
    )
    if header.channel_count not in (1, 3, 4):
        raise TlgDecodeError(f"不支持的 TLG6 通道数: {header.channel_count}")
    if header.image_width <= 0 or header.image_height <= 0:
        raise TlgDecodeError("TLG6 图像尺寸无效。")

    filter_data_size = reader.read_u32()
    compressed_filter_types = reader.read(filter_data_size)
    initial = bytearray(4096)
    ptr = 0
    for i in range(32):
        for j in range(16):
            for _ in range(4):
                initial[ptr] = i
                ptr += 1
            for _ in range(4):
                initial[ptr] = j
                ptr += 1
    filter_types = _lzss_decompress(compressed_filter_types, header.x_block_count * header.y_block_count, initial)

    pixels = [0] * (header.image_width * header.image_height)
    zero_line = [0] * header.image_width
    prev_line = zero_line
    main_count = header.image_width // W_BLOCK_SIZE
    fraction = header.image_width - main_count * W_BLOCK_SIZE

    for y in range(0, header.image_height, H_BLOCK_SIZE):
        ylim = min(y + H_BLOCK_SIZE, header.image_height)
        pixel_count = (ylim - y) * header.image_width
        pixel_buf = bytearray(pixel_count * 4)

        for channel in range(header.channel_count):
            bit_length = reader.read_u32()
            method = (bit_length >> 30) & 3
            bit_length &= 0x3FFFFFFF
            byte_length = (bit_length + 7) // 8
            bit_pool = reader.read(byte_length)
            if method != 0:
                raise TlgDecodeError(f"不支持的 TLG6 编码方式: {method}")
            _decode_golomb_values(pixel_buf, channel, pixel_count, bit_pool)

        ft_start = (y // H_BLOCK_SIZE) * header.x_block_count
        ft = filter_types[ft_start:ft_start + header.x_block_count]
        skip_units = (ylim - y) * W_BLOCK_SIZE

        for yy in range(y, ylim):
            current_line = [0] * header.image_width
            direction = (yy & 1) ^ 1
            odd_skip = (ylim - yy - 1) - (yy - y)
            initialp = 0xFF000000 if header.channel_count == 3 else 0

            if main_count:
                start = min(header.image_width, W_BLOCK_SIZE) * (yy - y)
                _decode_line(
                    prev_line,
                    current_line,
                    header.image_width,
                    0,
                    main_count,
                    ft,
                    skip_units,
                    pixel_buf,
                    start,
                    initialp,
                    odd_skip,
                    direction,
                    header.channel_count,
                )

            if main_count != header.x_block_count:
                ww = min(fraction, W_BLOCK_SIZE)
                start = ww * (yy - y)
                _decode_line(
                    prev_line,
                    current_line,
                    header.image_width,
                    main_count,
                    header.x_block_count,
                    ft,
                    skip_units,
                    pixel_buf,
                    start,
                    initialp,
                    odd_skip,
                    direction,
                    header.channel_count,
                )

            row_start = yy * header.image_width
            pixels[row_start:row_start + header.image_width] = current_line
            prev_line = current_line

    return _image_from_pixels(header.image_width, header.image_height, pixels)


def read_tlg(path: str | Path) -> Image.Image:
    """Decode a TLG0/TLG5/TLG6 image into a Pillow RGBA image."""
    data = Path(path).read_bytes()
    reader = _Reader(data)
    func = _choose_reader(reader)
    return func(reader).convert("RGBA")


__all__ = ["read_tlg", "TlgDecodeError"]
