"""WearFit / Chronos style watch face (.bin) reader and writer.

Format (reverse engineered from public sample dials, see notes):
  uint32 LE  record count N
  N x 20-byte records:
      u8 id, u8 id2, u8 aoff, u8 flag, u16 x, u16 y, u16 w, u16 h,
      u32 palette_offset, u32 data_offset          (all little endian)
  then, in record order, for each record:
      palette  (n x RGB565 LE)   at palette_offset
      indices  (w*h bytes)       at data_offset  (= palette_offset + 2*n)
  trailer: b"screenConfig" + 0x0B

Record kinds used here:
  id 0x09 / id2 0x01      full screen background
  id 0x0D / id2 0x10      analog hand frame, flag 0x80.
      48 records: hour (16), minute (16), second (16).  The 16 frames of a
      hand are the hand rotated 0, 6, ... 90 degrees clockwise from 12
      o'clock.  Pure black (RGB565 0x0000) is transparent.  x, y is the
      pivot (screen center of the hand).  Inside a frame the pivot sits at
      (aoff, h - aoff).  The watch builds the other three quadrants by
      mirroring.

Only the standard library and Pillow are needed.
"""
import math
import struct

from PIL import Image

TRAILER = b"screenConfig\x0b"
# Last byte of the trailer is a screen type code (seen in real dials):
# 240x240 -> 7, 240x280 / 240x288 -> 11, 240x296 -> 21, 360x360 -> 13.
SCREEN_CODES = {(240, 240): 7, (240, 280): 11, (240, 288): 11,
                (240, 296): 21, (360, 360): 13}
FRAMES = 16            # frames per hand: 0..90 degrees in 6 degree steps
STEP = 6.0
MAX_COLORS = 254       # palette size limit used by the sample dials
DARKEST = 0x0841       # smallest non-transparent RGB565 color


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def rgb_to_565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def c565_to_rgb(v):
    r = (v >> 11) & 31
    g = (v >> 5) & 63
    b = v & 31
    return (r * 255 // 31, g * 255 // 63, b * 255 // 31)


def _palette_bytes(colors565):
    return b"".join(struct.pack("<H", c) for c in colors565)


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------
def parse_bin(data):
    count = struct.unpack_from("<I", data, 0)[0]
    records = []
    for i in range(count):
        r = 4 + 20 * i
        rid, id2, aoff, flag = data[r], data[r + 1], data[r + 2], data[r + 3]
        x, y, w, h = struct.unpack_from("<HHHH", data, r + 4)
        clt, dat = struct.unpack_from("<II", data, r + 12)
        records.append({"i": i, "id": rid, "id2": id2, "aoff": aoff,
                        "flag": flag, "x": x, "y": y, "w": w, "h": h,
                        "clt": clt, "dat": dat})
    return records


def record_image(data, rec, transparent_black=False):
    """Decode one record to a PIL image (RGBA when transparent_black)."""
    w, h, clt, dat = rec["w"], rec["h"], rec["clt"], rec["dat"]
    if clt == dat:
        words = struct.unpack_from("<%dH" % (w * h), data, dat)
        pixels = [c565_to_rgb(v) for v in words]
        raw = words
    else:
        n = (dat - clt) // 2
        pal = struct.unpack_from("<%dH" % n, data, clt)
        idx = data[dat:dat + w * h]
        raw = [pal[k] if k < n else 0 for k in idx]
        lut = [c565_to_rgb(v) for v in pal]
        pixels = [lut[k] if k < n else (0, 0, 0) for k in idx]
    if transparent_black:
        img = Image.new("RGBA", (w, h))
        img.putdata([p + (0 if v == 0 else 255,) for p, v in zip(pixels, raw)])
        return img
    img = Image.new("RGB", (w, h))
    img.putdata(pixels)
    return img


def hand_records(records):
    """Return {"hour": [..16..], "minute": [...], "second": [...]} or None."""
    hands = [r for r in records if r["id"] == 0x0D]
    n = len(hands) // 3
    if n < 2 or len(hands) != 3 * n:
        return None
    return {"hour": hands[:n], "minute": hands[n:2 * n],
            "second": hands[2 * n:]}


def render_bin(data, hour, minute, second, background=None):
    """Preview what the watch should show.  Quadrant mirroring is an
    assumption based on how the frames are stored (see module docstring)."""
    records = parse_bin(data)
    bg_rec = records[0]
    out = (background.copy() if background is not None
           else record_image(data, bg_rec))
    hands = hand_records(records)
    if not hands:
        return out
    angles = {"hour": ((hour % 12) + minute / 60.0) * 30.0,
              "minute": (minute + second / 60.0) * 6.0,
              "second": second * 6.0}
    for name in ("hour", "minute", "second"):
        recs = hands[name]
        place_frame(out, data, recs, angles[name] % 360.0)
    return out


def place_frame(out, data, recs, angle):
    quadrant = int(angle // 90) % 4
    theta = angle - 90 * quadrant
    count = len(recs)                  # 16 normally, more = smoother hands
    step = 90.0 / (count - 1)
    rev = (90.0 - theta) / step
    fwd = theta / step
    index = {0: fwd, 1: rev, 2: fwd, 3: rev}[quadrant]
    index = max(0, min(count - 1, int(round(index))))
    rec = recs[index]
    frame = record_image(data, rec, transparent_black=True)
    w, h, aoff = rec["w"], rec["h"], rec["aoff"]
    cx, cy = rec["x"], rec["y"]
    if quadrant == 0:
        pivot = (aoff, h - aoff)
    elif quadrant == 1:
        frame = frame.transpose(Image.FLIP_TOP_BOTTOM)
        pivot = (aoff, aoff)
    elif quadrant == 2:
        frame = frame.transpose(Image.ROTATE_180)
        pivot = (w - aoff, aoff)
    else:
        frame = frame.transpose(Image.FLIP_LEFT_RIGHT)
        pivot = (w - aoff, h - aoff)
    out.paste(frame, (cx - pivot[0], cy - pivot[1]), frame)


# ---------------------------------------------------------------------------
# live digits (time, date) - preview renderer
# ---------------------------------------------------------------------------
DIGIT_IDS = {0x00: "hour", 0x01: "minute", 0x02: "day", 0x03: "month",
             0x07: "year", 0x1B: "second"}


def _place_values(value):
    text = str(int(value))
    return [int(text[-1 - i]) if i < len(text) else 0 for i in range(8)]


def render_full(data, when):
    """Render background, live digits, weekday and hands for a datetime.

    Digit records: for one element id the first record is the ones digit, the
    next the tens digit, and so on.  A record holds `cmp` equally tall images
    stacked vertically (cmp = id2 & 0x7F when id2 bit 7 is set).
    """
    records = parse_bin(data)
    out = record_image(data, records[0])
    values = {0x00: when.hour, 0x01: when.minute, 0x02: when.day,
              0x03: when.month, 0x07: when.year, 0x1B: when.second,
              0x0B: 85, 0x10: 72, 0x14: 320, 0x16: 32}   # sample values
    seen = {}
    # places per element id: the watch repeats the places when an id has more
    # records than places (battery 40 shows 0 4 0 4 0), so a second element
    # with the same id works again from the ones digit
    period = {0x0B: 2, 0x10: 2, 0x14: 4, 0x16: 3, 0x00: 2, 0x01: 2,
              0x02: 2, 0x03: 2, 0x1B: 2}
    for rec in records[1:]:
        rid = rec["id"]
        cmp_ = (rec["id2"] & 0x7F) if rec["id2"] & 0x80 else 1
        if rid in values:
            n = seen.get(rid, 0)
            seen[rid] = n + 1
            digit = _place_values(values[rid])[n % period.get(rid, 99)]
            if digit >= cmp_:
                digit = 0
            _paste_piece(out, data, rec, digit, cmp_)
        elif rid == 0x06:
            _paste_piece(out, data, rec, when.weekday() % max(cmp_, 1), cmp_)
    hands = hand_records(records)
    if hands:
        angles = {"hour": ((when.hour % 12) + when.minute / 60.0) * 30.0,
                  "minute": (when.minute + when.second / 60.0) * 6.0,
                  "second": when.second * 6.0}
        for name in ("hour", "minute", "second"):
            place_frame(out, data, hands[name], angles[name] % 360.0)
    return out


def _paste_piece(out, data, rec, index, cmp_):
    img = record_image(data, rec, transparent_black=True)
    piece_h = img.height // cmp_
    index = max(0, min(cmp_ - 1, index))
    piece = img.crop((0, index * piece_h, img.width, (index + 1) * piece_h))
    out.paste(piece, (rec["x"], rec["y"]), piece)


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------
def quantize_opaque(img_rgb, transparent_mask=None, max_colors=MAX_COLORS,
                    dither=False):
    """Return (palette565 list, index bytes).  When transparent_mask is given
    (an "L"/"1" image, nonzero = transparent) palette entry 0 is black and
    transparent pixels use it."""
    reserve = 1 if transparent_mask is not None else 0
    colors = max_colors - reserve
    # snap to what RGB565 can show so the palette is exact
    rch, gch, bch = img_rgb.split()
    snapped = Image.merge("RGB", (
        rch.point(lambda v: (v >> 3) * 255 // 31),
        gch.point(lambda v: (v >> 2) * 255 // 63),
        bch.point(lambda v: (v >> 3) * 255 // 31)))
    px = snapped.load()
    w, h = snapped.size
    uniq = snapped.getcolors(maxcolors=w * h) or []
    if len(uniq) <= colors:
        pal_rgb = [c for _n, c in uniq]
        lookup = {c: i for i, c in enumerate(pal_rgb)}
        idx = bytearray(lookup[px[xx, yy]] for yy in range(h)
                        for xx in range(w))
    else:
        q = snapped.quantize(
            colors=colors, method=Image.Quantize.MEDIANCUT,
            dither=(Image.Dither.FLOYDSTEINBERG if dither
                    else Image.Dither.NONE))
        flat = q.getpalette()
        used = max(q.getdata()) + 1
        pal_rgb = [tuple(flat[3 * k:3 * k + 3]) for k in range(used)]
        idx = bytearray(q.tobytes())
    pal565 = [rgb_to_565(*c) for c in pal_rgb]
    if transparent_mask is not None:
        pal565 = [0] + [c if c != 0 else DARKEST for c in pal565]
        mask = transparent_mask.tobytes()
        idx = bytearray((0 if mask[k] else idx[k] + 1) for k in range(len(idx)))
    return pal565, bytes(idx)


def _alpha_composite_layers(side, layers, angle, resample=Image.BICUBIC):
    """Rotate every layer (pivot centered RGBA, "dx","dy","mode") and
    composite them onto one transparent square canvas, pivot in the middle."""
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    half = side // 2
    rad = math.radians(angle)
    for layer in layers:
        dx, dy = layer.get("dx", 0.0), layer.get("dy", 0.0)
        if layer.get("mode") == "hand":
            dx, dy = (dx * math.cos(rad) - dy * math.sin(rad),
                      dx * math.sin(rad) + dy * math.cos(rad))
        rotated = layer["image"].rotate(-angle, resample=resample,
                                        expand=False)
        piece = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        piece.paste(rotated, (half + int(round(dx)) - rotated.width // 2,
                              half + int(round(dy)) - rotated.height // 2))
        canvas = Image.alpha_composite(canvas, piece)
    return canvas


def _flatten(rgba, alpha_cutoff=24):
    """RGBA -> (RGB premultiplied on black, transparent mask 'L')."""
    a = rgba.getchannel("A")
    black = Image.new("RGB", rgba.size, (0, 0, 0))
    rgb = Image.composite(rgba.convert("RGB"), black, a)
    mask = a.point(lambda v: 255 if v < alpha_cutoff else 0)
    rgb.paste((0, 0, 0), mask=mask)
    return rgb, mask


def make_hand_frames(layers, max_extent, dot=None, max_tail=255, scale=1.0,
                     frames=FRAMES):
    """Return (aoff, [`frames` dicts with image,mask,x_ext,y_ext]) for one
    hand.  The frames cover 0..90 degrees; frames=16 means 6 degree steps
    (normal file), frames=31 means 3 degree steps (experimental, smoother).

    layers: list of layer dicts (same as the GUI), may be empty/None.
    dot: optional pivot-centered RGBA image drawn on top.
    max_extent: radius in pixels of the biggest hand (sets the work canvas).
    """
    layers = list(layers or [])
    if scale != 1.0:
        scaled = []
        for item in layers:
            img = item["image"]
            size = (max(1, int(round(img.width * scale))),
                    max(1, int(round(img.height * scale))))
            scaled.append(dict(item, image=img.resize(size, Image.LANCZOS),
                               dx=item.get("dx", 0.0) * scale,
                               dy=item.get("dy", 0.0) * scale))
        layers = scaled
    if dot is not None:
        layers = layers + [{"image": dot, "dx": 0.0, "dy": 0.0,
                            "mode": "screen"}]
    if not layers:
        blank = Image.new("RGB", (2, 2), (0, 0, 0))
        mask = Image.new("L", (2, 2), 255)
        return 1, [{"image": blank, "mask": mask, "ox": 1, "oy": 1}] * frames
    biggest = max(max(l["image"].size) for l in layers)
    offs = max(max(abs(l.get("dx", 0.0)), abs(l.get("dy", 0.0)))
               for l in layers)
    half = int(math.ceil(biggest / 2.0 + offs)) + 4
    side = half * 2
    rendered = []
    left = down = 1
    step = 90.0 / (frames - 1)
    for k in range(frames):
        rgba = _alpha_composite_layers(side, layers, k * step)
        rgb, mask = _flatten(rgba)
        bbox = Image.eval(mask, lambda v: 255 - v).getbbox()
        if bbox is None:
            bbox = (half, half - 1, half + 1, half)
        x0, y0, x1, y1 = bbox
        left = max(left, half - x0)
        down = max(down, y1 - half)
        rendered.append((rgb, mask, bbox))
    aoff = int(min(255, max_tail, max(left, down, 1)))
    frames = []
    for rgb, mask, bbox in rendered:
        x0, y0, x1, y1 = bbox
        ext_x = max(1, x1 - half)
        ext_y = max(1, half - y0)
        box = (half - aoff, half - ext_y, half + ext_x, half + aoff)
        frames.append({"image": rgb.crop(box), "mask": mask.crop(box)})
    return aoff, frames


def build_bin(background, cx, cy, hands, dither_bg=True, digits=None,
              pivots=None):
    """Build the .bin bytes.

    background: PIL RGB image of the full screen (hands NOT included).
    cx, cy: pivot pixel of the hands.
    pivots: optional {"hour"/"minute"/"second": (x, y)} to give a hand its
        own pivot pixel (default: every hand uses cx, cy).
    hands: {"hour"/"minute"/"second": (aoff, frames)} from make_hand_frames,
        or None for a digital face without analog hands.
    digits: optional list of live digit records, in drawing order.  Each is
        {"id": element id, "x", "y", "images": [RGBA sprite per value]}.  For
        one element id list the ones digit first, then tens, and so on.
    """
    background = background.convert("RGB")
    w, h = background.size
    items = []   # (id, id2, aoff, flag, x, y, w, h, palette565, indices)
    pal, idx = quantize_opaque(background, None, MAX_COLORS, dither=dither_bg)
    items.append((0x09, 0x01, 0, 0, 0, 0, w, h, pal, idx))
    for dig in (digits or []):
        sprites = dig["images"]
        sw, sh = sprites[0].size
        stack = Image.new("RGBA", (sw, sh * len(sprites)), (0, 0, 0, 0))
        for k, sprite in enumerate(sprites):
            stack.paste(sprite, (0, k * sh))
        rgb, mask = _flatten(stack)
        pal, idx = quantize_opaque(rgb, mask, MAX_COLORS)
        items.append((dig["id"], 0x80 | len(sprites), 0x82, 0x00,
                      int(dig["x"]), int(dig["y"]), sw, sh * len(sprites),
                      pal, idx))
    for name in (("hour", "minute", "second") if hands else ()):
        aoff, frames = hands[name]
        px, py = (pivots or {}).get(name, (cx, cy))
        px = max(0, min(w, int(round(px))))
        py = max(0, min(h, int(round(py))))
        for fr in frames:
            im = fr["image"]
            pal, idx = quantize_opaque(im, fr["mask"], MAX_COLORS)
            # id2 = number of frames of the hand (0x10 = 16 in normal files)
            items.append((0x0D, len(frames), aoff, 0x80, px, py,
                          im.width, im.height, pal, idx))
    head = struct.pack("<I", len(items))
    offset = 4 + 20 * len(items)
    records = bytearray()
    blobs = bytearray()
    for rid, id2, aoff, flag, x, y, iw, ih, pal, idx in items:
        clt = offset + len(blobs)
        dat = clt + 2 * len(pal)
        records += struct.pack("<BBBBHHHHII", rid, id2, aoff, flag,
                               x, y, iw, ih, clt, dat)
        blobs += _palette_bytes(pal) + idx
    code = SCREEN_CODES.get((w, h), 11)
    trailer = b"screenConfig" + bytes([code])
    return head + bytes(records) + bytes(blobs) + trailer
