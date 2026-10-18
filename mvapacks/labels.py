"""Render MVA altitude labels as transparent PNGs in the locked house style.

Labels are baked as icon images (not KML LabelStyle) so ForeFlight renders them
with no name chip. Per-glyph drawing gives control over kerning.
"""
from __future__ import annotations
import io
import os
from functools import lru_cache
from PIL import Image, ImageFont, ImageDraw


class LabelRenderer:
    def __init__(self, style, repo_root):
        s = style['label']
        font_path = s['font']
        if not os.path.isabs(font_path):
            font_path = os.path.join(repo_root, font_path)
        self.font_path = font_path
        self.size = int(s['size'])
        self.kern = int(s['kern'])
        self.text_fill = tuple(s['text_fill'])
        self.halo_color = tuple(s['halo_color'])
        self.halo_r = int(s['halo_radius'])
        self._font = ImageFont.truetype(self.font_path, self.size)

    @lru_cache(maxsize=512)
    def render(self, txt: str) -> bytes:
        font = self._font
        advs = [font.getlength(c) for c in txt]
        asc, desc = font.getmetrics()
        th = asc + desc
        pad = self.size // 3 + self.halo_r
        total = sum(advs) + self.kern * (len(txt) - 1)
        W = int(total) + pad * 2
        H = th + pad * 2

        # halo layer
        halo = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        hd = ImageDraw.Draw(halo)
        x = pad
        for i, c in enumerate(txt):
            hd.text((x, pad), c, font=font, fill=self.halo_color)
            x += advs[i] + self.kern

        base = Image.new('RGBA', (W, H), (0, 0, 0, 0))
        r = self.halo_r
        for dx in range(-r, r + 1):
            for dy in range(-r, r + 1):
                if dx * dx + dy * dy <= r * r:
                    base.alpha_composite(halo, (dx, dy))

        td = ImageDraw.Draw(base)
        x = pad
        for i, c in enumerate(txt):
            td.text((x, pad), c, font=font, fill=self.text_fill)
            x += advs[i] + self.kern

        bio = io.BytesIO()
        base.save(bio, 'PNG')
        return bio.getvalue()
