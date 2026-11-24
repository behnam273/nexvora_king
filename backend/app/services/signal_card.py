from __future__ import annotations

import io
import math
import os
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from app.config import SYMBOL_META, TIMEFRAME_META
from app.engine.market_data import Candle, get_market_series
from app.engine.policy import get_policy
from app.models import SignalTrade

# ==============================================================================
# NEXVORA Official Institutional Signal Card Renderer (1080 x 1350 PNG)
# Faithfully modeled after the official NEXVORA Telegram Signal Card design:
#   - Dark navy canvas (#09101E) with gold institutional frame (#D2B46A)
#   - Diagonal translucent NEXVORA watermark across the card
#   - Live candlestick chart with EMA 20 / EMA 50, SL/TP shaded zones & price tags
#   - Trade Setup & Risk, 3-Tier Take Profit Targets (1.2R / 2.2R / 3.2R),
#     Trading Instructions, and Engine Diagnostics panels
# ==============================================================================

CARD_W = 1080
CARD_H = 1350

# Color palette matching NEXVORA institutional identity
BG_DARK = (9, 16, 30)
BG_PANEL = (13, 22, 38)
BG_PANEL_INNER = (16, 28, 48)
BG_CHART = (10, 18, 33)
GOLD = (210, 180, 106)
GOLD_BRIGHT = (232, 203, 126)
GOLD_BORDER = (165, 140, 82)
BLUE_BORDER = (34, 54, 86)
TEXT_WHITE = (242, 246, 252)
TEXT_MUTED = (140, 158, 186)
TEXT_DIM = (96, 114, 144)

GREEN = (34, 197, 94)
GREEN_LIGHT = (74, 222, 128)
GREEN_BG = (17, 46, 36)
GREEN_BORDER = (36, 106, 72)

RED = (239, 68, 68)
RED_LIGHT = (248, 113, 113)
RED_BG = (54, 22, 30)
RED_BORDER = (138, 44, 54)

CYAN = (56, 189, 248)
ORANGE = (245, 158, 11)


_ASSET_FONT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets", "fonts")


def _bundled_font(bold: bool = False) -> Optional[str]:
    """
    Vazirmatn is bundled with the app so Persian text renders correctly on any
    host. Without it Pillow falls back to DejaVu/Liberation, which have no Arabic
    glyphs, and every Persian string in the card becomes a row of blank boxes.
    """
    name = "Vazirmatn-Bold.ttf" if bold else "Vazirmatn-Regular.ttf"
    candidates = [
        os.path.join(_ASSET_FONT_DIR, name),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "assets", "fonts", name),
        f"/usr/share/fonts/truetype/vazirmatn/{name}",
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


_RTL_RANGES = (("\u0600", "\u06ff"), ("\u0750", "\u077f"), ("\ufb50", "\ufe7f"))


def _has_rtl(text: str) -> bool:
    return any(lo <= ch <= hi for ch in text for lo, hi in _RTL_RANGES)


def _shape_rtl(text: str) -> str:
    """
    Pillow draws codepoints left-to-right with no contextual Arabic shaping, so
    Persian text must be reshaped + reordered first. If the libraries are absent
    we return the text unchanged rather than crashing card rendering.
    """
    if not text or not _has_rtl(text):
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display

        # base_dir="R" is essential: a Persian sentence must be laid out
        # right-to-left, otherwise trailing punctuation and Latin fragments jump
        # to the wrong end of the line and the sentence reads inside-out.
        return get_display(arabic_reshaper.reshape(text), base_dir="R")
    except Exception:
        return text


def _find_font_path(bold: bool = False, mono: bool = False) -> Optional[str]:
    if not mono:
        bundled = _bundled_font(bold=bold)
        if bundled:
            return bundled
    candidates = []
    if mono and bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
        ]
    elif mono:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ]
    elif bold:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def _font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    path = _find_font_path(bold=bold, mono=mono)
    if path:
        try:
            return ImageFont.truetype(path, size=size)
        except Exception:
            pass
    return ImageFont.load_default()



class _RTLDraw:
    """
    Thin proxy around ImageDraw that shapes/reorders Persian (and any RTL) text
    before it reaches Pillow. Latin-only strings pass through untouched, so the
    numerics and the English brand lines keep their exact layout.
    """

    def __init__(self, draw):
        # Never wrap twice: shaping + reversal applied a second time would
        # scramble already-correct text back into gibberish.
        self._draw = draw._draw if isinstance(draw, _RTLDraw) else draw

    def text(self, xy, text, *args, **kwargs):
        return self._draw.text(xy, _shape_rtl(str(text)), *args, **kwargs)

    def textlength(self, text, *args, **kwargs):
        return self._draw.textlength(_shape_rtl(str(text)), *args, **kwargs)

    def textbbox(self, xy, text, *args, **kwargs):
        return self._draw.textbbox(xy, _shape_rtl(str(text)), *args, **kwargs)

    def multiline_text(self, xy, text, *args, **kwargs):
        return self._draw.multiline_text(xy, _shape_rtl(str(text)), *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._draw, name)


def _ema(values: List[float], period: int) -> List[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1.0 - alpha) * out[-1])
    return out


def _draw_hexagon_logo(draw: ImageDraw.ImageDraw, cx: int, cy: int, radius: int) -> None:
    pts = []
    for k in range(6):
        ang = math.radians(60 * k - 30)
        pts.append((cx + radius * math.cos(ang), cy + radius * math.sin(ang)))
    draw.polygon(pts, fill=(14, 23, 40), outline=GOLD, width=2)
    f = _font(int(radius * 1.15), bold=True)
    bbox = draw.textbbox((0, 0), "N", font=f)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text((cx - tw / 2, cy - th / 2 - 2), "N", fill=GOLD_BRIGHT, font=f)


def _draw_dashed_line(
    draw: ImageDraw.ImageDraw,
    x0: float,
    y: float,
    x1: float,
    color: Tuple[int, int, int],
    dash: int = 8,
    gap: int = 5,
    width: int = 2,
) -> None:
    x = x0
    while x < x1:
        xe = min(x + dash, x1)
        draw.line([(x, y), (xe, y)], fill=color, width=width)
        x += dash + gap


def _apply_watermark(base_img: Image.Image, text: str = "NEXVORA") -> Image.Image:
    wm = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
    f = _font(62, bold=True)
    positions = [
        (60, 240), (430, 140), (740, 270),
        (40, 540), (400, 440), (710, 550),
        (140, 840), (500, 770), (740, 900),
        (160, 1110), (580, 1080),
    ]
    for px, py in positions:
        tile = Image.new("RGBA", (420, 120), (0, 0, 0, 0))
        td = ImageDraw.Draw(tile)
        td.text((10, 20), text, fill=(210, 180, 106, 15), font=f)
        rot = tile.rotate(24, expand=True, resample=Image.Resampling.BICUBIC)
        wm.alpha_composite(rot, (px, py))
    # Clip watermark cleanly inside the outer gold frame
    mask = Image.new("L", base_img.size, 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle([(20, 20), (CARD_W - 20, CARD_H - 20)], radius=20, fill=255)
    clipped = Image.new("RGBA", base_img.size, (0, 0, 0, 0))
    clipped.paste(wm, (0, 0), mask)
    return Image.alpha_composite(base_img.convert("RGBA"), clipped).convert("RGB")


def _format_status_badge(status: str) -> Tuple[str, Tuple[int, int, int], Tuple[int, int, int], Tuple[int, int, int]]:
    if status in ("ACTIVE", "TP1_HIT", "TP2_HIT"):
        label = "OPEN" if status == "ACTIVE" else status.replace("_", " ")
        return label, GREEN_LIGHT, GREEN_BG, GREEN_BORDER
    if status == "PENDING_LIMIT":
        return "PENDING", GOLD_BRIGHT, (42, 36, 18), GOLD_BORDER
    if status == "CLOSED_WIN":
        return "CLOSED WIN", GREEN_LIGHT, GREEN_BG, GREEN_BORDER
    if status == "CLOSED_LOSS":
        return "STOPPED", RED_LIGHT, RED_BG, RED_BORDER
    if status == "CLOSED_BE":
        return "BREAKEVEN", CYAN, (18, 40, 56), (48, 120, 160)
    return status.replace("_", " "), TEXT_MUTED, BG_PANEL_INNER, BLUE_BORDER


def _split_symbol_pair(symbol: str) -> Tuple[str, str]:
    if len(symbol) == 6:
        return symbol[:3], symbol[3:]
    return symbol[:3], "USD"


def _setup_entry_label(timeframe: str) -> str:
    tf_meta = TIMEFRAME_META.get(timeframe, {})
    htf1 = tf_meta.get("htf_primary", "4H").upper()
    htf2 = tf_meta.get("htf_secondary", "1H").upper()
    tf_up = timeframe.upper()
    if htf1 == htf2:
        return f"{htf1} -> {tf_up}"
    return f"{htf1}+{htf2} -> {tf_up}"


def render_signal_card_png(
    trade: SignalTrade,
    candles: Optional[List[Candle]] = None,
    adx_value: Optional[float] = None,
) -> bytes:
    """
    Renders an institutional-grade NEXVORA Telegram Signal Card PNG (1080 x 1350)
    matching the official dark-navy & gold visual design with live candles,
    EMA 20 / EMA 50, SL/TP shaded zones, risk/reward targets, and diagnostics.
    """
    meta = SYMBOL_META.get(trade.symbol, {"display": trade.symbol, "digits": 5, "pip_size": 0.0001})
    digits = int(meta["digits"])
    is_long = trade.direction == "LONG"
    is_gold = trade.symbol == "XAUUSD"

    entry = float(trade.entry_price)
    sl = float(trade.initial_sl)
    tp1 = float(trade.tp1)
    tp2 = float(trade.tp2)
    tp3 = float(trade.tp3)
    risk_d = max(abs(entry - sl), 1e-6)

    rr1 = round(abs(tp1 - entry) / risk_d, 2)
    rr2 = round(abs(tp2 - entry) / risk_d, 2)
    rr3 = round(abs(tp3 - entry) / risk_d, 2)
    # Weighted net R:R matching 50% TP1 + 30% TP2 + 20% TP3
    p1 = float(trade.tp1_exit_pct or 50.0) / 100.0
    p2 = float(trade.tp2_exit_pct or 30.0) / 100.0
    p3 = max(0.0, 1.0 - p1 - p2)
    net_rr = round(p1 * rr1 + p2 * rr2 + p3 * rr3, 2)

    sl_pct = (abs(entry - sl) / max(entry, 1e-6)) * 100.0
    tp1_pct = (abs(tp1 - entry) / max(entry, 1e-6)) * 100.0
    tp2_pct = (abs(tp2 - entry) / max(entry, 1e-6)) * 100.0
    tp3_pct = (abs(tp3 - entry) / max(entry, 1e-6)) * 100.0

    # Fetch recent candles if not supplied
    if candles is None:
        try:
            series = get_market_series(trade.symbol, trade.timeframe, limit=120)
            candles = series.candles
        except Exception:
            candles = []

    updated_dt = trade.updated_at or trade.created_at or datetime.now(timezone.utc)
    if updated_dt.tzinfo is None:
        updated_dt = updated_dt.replace(tzinfo=timezone.utc)
    updated_str = updated_dt.strftime("%Y-%m-%d %H:%M UTC")

    # Create base RGBA canvas for clean alpha zone blending
    img = Image.new("RGBA", (CARD_W, CARD_H), (*BG_DARK, 255))
    draw = ImageDraw.Draw(img, "RGBA")
    draw = _RTLDraw(draw)

    # Outer institutional gold frame
    draw.rounded_rectangle(
        [(16, 16), (CARD_W - 16, CARD_H - 16)],
        radius=22,
        fill=(*BG_DARK, 255),
        outline=(*GOLD_BORDER, 255),
        width=2,
    )

    # ------------------------------------------------------------------
    # 1. HEADER BAR
    # ------------------------------------------------------------------
    _draw_hexagon_logo(draw, 62, 62, 24)
    draw.text((100, 38), "NEXVORA", fill=GOLD_BRIGHT, font=_font(28, bold=True))
    draw.text((100, 72), "INSTITUTIONAL TRADING SIGNAL ENGINE", fill=GOLD, font=_font(13, bold=False))

    st_label, st_col, st_bg, st_bd = _format_status_badge(trade.status)
    badge_x0, badge_y0, badge_x1, badge_y1 = 845, 34, 1038, 74
    draw.rounded_rectangle([(badge_x0, badge_y0), (badge_x1, badge_y1)], radius=18, fill=st_bg, outline=st_bd, width=2)
    draw.ellipse([(badge_x0 + 16, badge_y0 + 13), (badge_x0 + 30, badge_y0 + 27)], fill=st_col)
    draw.text((badge_x0 + 40, badge_y0 + 9), st_label, fill=TEXT_WHITE, font=_font(17, bold=True))

    upd_font = _font(13)
    upd_txt = f"Updated: {updated_str}"
    ub = draw.textbbox((0, 0), upd_txt, font=upd_font)
    draw.text((1038 - (ub[2] - ub[0]), 82), upd_txt, fill=TEXT_MUTED, font=upd_font)

    draw.line([(36, 108), (CARD_W - 36, 108)], fill=BLUE_BORDER, width=1)

    # ------------------------------------------------------------------
    # 2. SYMBOL & SETUP META ROW
    # ------------------------------------------------------------------
    base_ccy, quote_ccy = _split_symbol_pair(trade.symbol)
    draw.ellipse([(38, 126), (98, 186)], fill=(15, 25, 44), outline=GOLD, width=2)
    f_ccy = _font(14, bold=True)
    b1 = draw.textbbox((0, 0), base_ccy, font=f_ccy)
    b2 = draw.textbbox((0, 0), quote_ccy, font=f_ccy)
    draw.text((68 - (b1[2] - b1[0]) / 2, 138), base_ccy, fill=GOLD_BRIGHT, font=f_ccy)
    draw.text((68 - (b2[2] - b2[0]) / 2, 158), quote_ccy, fill=TEXT_WHITE, font=f_ccy)

    sym_font = _font(36, bold=True)
    draw.text((114, 122), trade.symbol, fill=TEXT_WHITE, font=sym_font)
    sym_w = draw.textbbox((0, 0), trade.symbol, font=sym_font)[2]

    # Direction pill badge
    dir_x0 = 114 + sym_w + 18
    dir_txt = "▲ LONG" if is_long else "▼ SHORT"
    dir_bg = GREEN_BG if is_long else RED_BG
    dir_bd = GREEN if is_long else RED
    dir_col = GREEN_LIGHT if is_long else RED_LIGHT
    draw.rounded_rectangle([(dir_x0, 126), (dir_x0 + 132, 162)], radius=10, fill=dir_bg, outline=dir_bd, width=2)
    df = _font(17, bold=True)
    dbx = draw.textbbox((0, 0), dir_txt, font=df)
    draw.text((dir_x0 + (132 - (dbx[2] - dbx[0])) / 2, 134), dir_txt, fill=dir_col, font=df)

    mkt_txt = "Market: METALS  •  Type: GOLD" if is_gold else "Market: FOREX  •  Type: FX"
    draw.text((114, 168), mkt_txt, fill=TEXT_MUTED, font=_font(15))

    # Right boxes: SETUP -> ENTRY & MODE
    draw.rounded_rectangle([(694, 124), (888, 186)], radius=12, fill=BG_PANEL, outline=BLUE_BORDER, width=1)
    lbl_f = _font(11, bold=True)
    val_f = _font(18, bold=True)
    s_lbl = "SETUP -> ENTRY"
    s_val = _setup_entry_label(trade.timeframe)
    sb1 = draw.textbbox((0, 0), s_lbl, font=lbl_f)
    sb2 = draw.textbbox((0, 0), s_val, font=val_f)
    draw.text((791 - (sb1[2] - sb1[0]) / 2, 134), s_lbl, fill=TEXT_MUTED, font=lbl_f)
    draw.text((791 - (sb2[2] - sb2[0]) / 2, 155), s_val, fill=GOLD_BRIGHT, font=val_f)

    draw.rounded_rectangle([(904, 124), (1040, 186)], radius=12, fill=BG_PANEL, outline=BLUE_BORDER, width=1)
    m_lbl = "MODE"
    m_val = "GOLD" if is_gold else "FX"
    mb1 = draw.textbbox((0, 0), m_lbl, font=lbl_f)
    mb2 = draw.textbbox((0, 0), m_val, font=val_f)
    draw.text((972 - (mb1[2] - mb1[0]) / 2, 134), m_lbl, fill=TEXT_MUTED, font=lbl_f)
    draw.text((972 - (mb2[2] - mb2[0]) / 2, 155), m_val, fill=TEXT_WHITE, font=val_f)

    # ------------------------------------------------------------------
    # 3. LIVE CANDLESTICK CHART PANEL
    # ------------------------------------------------------------------
    ch_x0, ch_y0, ch_x1, ch_y1 = 36, 206, 1044, 650
    draw.rounded_rectangle([(ch_x0, ch_y0), (ch_x1, ch_y1)], radius=16, fill=BG_CHART, outline=BLUE_BORDER, width=2)

    plot_x0, plot_y0 = ch_x0 + 84, ch_y0 + 26
    plot_x1, plot_y1 = ch_x1 - 24, ch_y1 - 24
    plot_w = plot_x1 - plot_x0
    plot_h = plot_y1 - plot_y0

    vis_candles = candles[-48:] if candles else []
    closes_all = [float(c.close) for c in (candles or [])]
    ema20_all = _ema(closes_all, 20)
    ema50_all = _ema(closes_all, 50)
    ema20_vis = ema20_all[-len(vis_candles):] if vis_candles else []
    ema50_vis = ema50_all[-len(vis_candles):] if vis_candles else []

    price_vals = [entry, sl, tp1, tp2, tp3]
    for c in vis_candles:
        price_vals.extend([float(c.high), float(c.low)])
    p_min = min(price_vals)
    p_max = max(price_vals)
    pad = max((p_max - p_min) * 0.12, risk_d * 0.4)
    p_min -= pad
    p_max += pad

    def y_of(price: float) -> float:
        frac = (price - p_min) / max(p_max - p_min, 1e-9)
        return plot_y1 - frac * plot_h

    # Grid & Y-axis labels
    axis_f = _font(12, mono=True)
    grid_steps = 6
    for idx in range(grid_steps + 1):
        gp = p_min + (p_max - p_min) * (idx / grid_steps)
        gy = y_of(gp)
        draw.line([(plot_x0, gy), (plot_x1, gy)], fill=(22, 34, 56, 180), width=1)
        lbl = f"{gp:.{digits}f}"
        lb = draw.textbbox((0, 0), lbl, font=axis_f)
        draw.text((plot_x0 - (lb[2] - lb[0]) - 10, gy - 7), lbl, fill=TEXT_MUTED, font=axis_f)

    # Reserve right 27% of plot for projected SL/TP shaded zones
    candle_area_x1 = plot_x0 + plot_w * 0.72
    zone_x0 = candle_area_x1 + 4
    zone_x1 = plot_x1

    # Shaded Risk (Red) & Reward (Green) projection boxes via clean alpha overlay
    y_entry = y_of(entry)
    y_sl = y_of(sl)
    y_tp1 = y_of(tp1)
    y_tp2 = y_of(tp2)
    y_tp3 = y_of(tp3)

    zone_overlay = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    z_draw = ImageDraw.Draw(zone_overlay, "RGBA")
    z_draw.rectangle([(zone_x0, min(y_entry, y_sl)), (zone_x1, max(y_entry, y_sl))], fill=(220, 48, 60, 42))
    z_draw.rectangle([(zone_x0, min(y_entry, y_tp3)), (zone_x1, max(y_entry, y_tp3))], fill=(34, 197, 94, 34))
    img = Image.alpha_composite(img, zone_overlay)
    draw = _RTLDraw(ImageDraw.Draw(img, "RGBA"))

    # Draw candlesticks
    if vis_candles:
        step_x = (candle_area_x1 - plot_x0 - 10) / max(len(vis_candles), 1)
        body_w = max(3.0, min(9.0, step_x * 0.62))
        xs = []
        for idx, c in enumerate(vis_candles):
            cx = plot_x0 + 8 + idx * step_x + step_x * 0.5
            xs.append(cx)
            o, h, l, cl = float(c.open), float(c.high), float(c.low), float(c.close)
            col = GREEN if cl >= o else RED
            draw.line([(cx, y_of(h)), (cx, y_of(l))], fill=col, width=1)
            yo, yc = y_of(o), y_of(cl)
            top_y, bot_y = min(yo, yc), max(yo, yc)
            if bot_y - top_y < 1.5:
                bot_y = top_y + 1.5
            draw.rectangle([(cx - body_w / 2, top_y), (cx + body_w / 2, bot_y)], fill=col)

        # Draw EMA 20 (Cyan) & EMA 50 (Orange)
        if len(xs) >= 2:
            pts20 = [(xs[i], y_of(ema20_vis[i])) for i in range(len(xs))]
            pts50 = [(xs[i], y_of(ema50_vis[i])) for i in range(len(xs))]
            draw.line(pts20, fill=CYAN, width=2)
            draw.line(pts50, fill=ORANGE, width=2)

    # Legend box top-left of chart
    leg_x0, leg_y0 = plot_x0 + 8, plot_y0 + 4
    draw.rounded_rectangle([(leg_x0, leg_y0), (leg_x0 + 216, leg_y0 + 28)], radius=6, fill=(11, 20, 36, 220), outline=BLUE_BORDER, width=1)
    draw.line([(leg_x0 + 10, leg_y0 + 14), (leg_x0 + 30, leg_y0 + 14)], fill=CYAN, width=2)
    draw.text((leg_x0 + 36, leg_y0 + 6), "EMA 20", fill=TEXT_WHITE, font=_font(12, bold=True))
    draw.line([(leg_x0 + 112, leg_y0 + 14), (leg_x0 + 132, leg_y0 + 14)], fill=ORANGE, width=2)
    draw.text((leg_x0 + 138, leg_y0 + 6), "EMA 50", fill=TEXT_WHITE, font=_font(12, bold=True))

    # Horizontal price lines & right price tag pills (with vertical anti-overlap)
    tag_f = _font(13, bold=True, mono=True)
    levels = [
        (y_sl, f"SL {sl:.{digits}f}", RED_LIGHT, RED_BG, False),
        (y_entry, f"ENTRY {entry:.{digits}f}", GOLD_BRIGHT, (42, 34, 16), True),
        (y_tp1, f"TP1 {tp1:.{digits}f}", GREEN_LIGHT, GREEN_BG, False),
        (y_tp2, f"TP2 {tp2:.{digits}f}", GREEN_LIGHT, GREEN_BG, False),
        (y_tp3, f"TP3 {tp3:.{digits}f}", GREEN_LIGHT, GREEN_BG, False),
    ]
    # Draw horizontal lines at true price coordinates first
    for y_px, _lbl, line_col, _bg_col, solid in levels:
        if solid:
            draw.line([(plot_x0, y_px), (zone_x0, y_px)], fill=line_col, width=2)
        else:
            _draw_dashed_line(draw, plot_x0, y_px, zone_x0, line_col, dash=7, gap=5, width=2)

    # Space right-hand pill labels so they never overlap even when tightly packed
    pill_h = 22
    min_gap = 25
    sorted_lvls = sorted(levels, key=lambda item: item[0])
    placed_ys: List[float] = []
    # The ENTRY pill is the reference price and must never be hidden, so every
    # other pill is placed first and ENTRY is painted last, on top.
    sorted_lvls = [lv for lv in sorted_lvls if not lv[4]] + [lv for lv in sorted_lvls if lv[4]]
    for y_px, label, line_col, bg_col, _solid in sorted_lvls:
        ty0 = max(plot_y0 + 2, min(plot_y1 - pill_h - 2, y_px - pill_h / 2))
        if placed_ys and ty0 < placed_ys[-1] + min_gap:
            ty0 = min(plot_y1 - pill_h - 2, placed_ys[-1] + min_gap)
        placed_ys.append(ty0)
        tb = draw.textbbox((0, 0), label, font=tag_f)
        tw = tb[2] - tb[0] + 14
        tx0 = zone_x0 + 12
        draw.rounded_rectangle([(tx0, ty0), (tx0 + tw, ty0 + pill_h)], radius=5, fill=bg_col, outline=line_col, width=1)
        draw.text((tx0 + 7, ty0 + 3), label, fill=line_col, font=tag_f)

    # ------------------------------------------------------------------
    # 4. SUMMARY RIBBON UNDER CHART
    # ------------------------------------------------------------------
    rib_y0, rib_y1 = 664, 706
    draw.rounded_rectangle([(36, rib_y0), (1044, rib_y1)], radius=10, fill=BG_PANEL, outline=BLUE_BORDER, width=1)
    regime_txt = (
        "STRONG UPTREND" if (trade.htf_bias == "BULLISH" and trade.confluence_score >= 8.0)
        else "UPTREND" if trade.htf_bias == "BULLISH"
        else "STRONG DOWNTREND" if (trade.htf_bias == "BEARISH" and trade.confluence_score >= 8.0)
        else "DOWNTREND" if trade.htf_bias == "BEARISH"
        else "TRANSITION"
    )
    rib_text = (
        f"{'خرید' if is_long else 'فروش'}: {trade.direction}   |   {regime_txt}   |   "
        f"{trade.confluence_score:.1f}/10   |   R:R 1:{net_rr:.2f}"
    )
    rf = _font(15, bold=True, mono=True)
    rb = draw.textbbox((0, 0), rib_text, font=rf)
    draw.text((CARD_W / 2 - (rb[2] - rb[0]) / 2, rib_y0 + 12), rib_text, fill=GOLD_BRIGHT, font=rf)

    # ------------------------------------------------------------------
    # 5. MIDDLE 2-COLUMN CARDS: TRADE SETUP & RISK  |  TAKE PROFIT TARGETS
    # ------------------------------------------------------------------
    mid_y0, mid_y1 = 724, 1020

    # Left Card: TRADE SETUP & RISK
    lx0, lx1 = 36, 526
    draw.rounded_rectangle([(lx0, mid_y0), (lx1, mid_y1)], radius=16, fill=BG_PANEL, outline=GOLD_BORDER, width=1)
    draw.text((lx0 + 22, mid_y0 + 18), "ستاپ معامله و ریسک | TRADE SETUP", fill=GOLD_BRIGHT, font=_font(17, bold=True))

    pill_txt = "LONG (BUY)" if is_long else "SHORT (SELL)"
    draw.rounded_rectangle([(lx1 - 154, mid_y0 + 14), (lx1 - 18, mid_y0 + 44)], radius=8, fill=dir_bg, outline=dir_bd, width=1)
    pf = _font(13, bold=True)
    pb = draw.textbbox((0, 0), pill_txt, font=pf)
    draw.text((lx1 - 86 - (pb[2] - pb[0]) / 2, mid_y0 + 21), pill_txt, fill=dir_col, font=pf)

    draw.line([(lx0 + 18, mid_y0 + 54), (lx1 - 18, mid_y0 + 54)], fill=BLUE_BORDER, width=1)

    # Entry row
    draw.ellipse([(lx0 + 24, mid_y0 + 82), (lx0 + 46, mid_y0 + 104)], outline=GOLD_BRIGHT, width=2)
    draw.ellipse([(lx0 + 31, mid_y0 + 89), (lx0 + 39, mid_y0 + 97)], fill=GOLD_BRIGHT)
    draw.text((lx0 + 62, mid_y0 + 70), "قیمت ورود", fill=TEXT_MUTED, font=_font(13, bold=True))
    draw.text((lx0 + 62, mid_y0 + 90), f"{entry:.{digits}f}", fill=TEXT_WHITE, font=_font(30, bold=True, mono=True))

    # Stop Loss row
    draw.rounded_rectangle([(lx0 + 24, mid_y0 + 158), (lx0 + 46, mid_y0 + 180)], radius=4, outline=RED_LIGHT, width=2)
    draw.line([(lx0 + 29, mid_y0 + 163), (lx0 + 41, mid_y0 + 175)], fill=RED_LIGHT, width=2)
    draw.line([(lx0 + 41, mid_y0 + 163), (lx0 + 29, mid_y0 + 175)], fill=RED_LIGHT, width=2)
    htf_anchor = TIMEFRAME_META.get(trade.timeframe, {}).get("htf_primary", "4H")
    draw.text((lx0 + 62, mid_y0 + 146), f"حد ضرر ({htf_anchor} POI / Swing)", fill=TEXT_MUTED, font=_font(13, bold=True))
    draw.text((lx0 + 62, mid_y0 + 166), f"{sl:.{digits}f}", fill=RED_LIGHT, font=_font(28, bold=True, mono=True))
    sl_pct_str = f"-{sl_pct:.2f}%"
    spb = draw.textbbox((0, 0), sl_pct_str, font=_font(16, bold=True, mono=True))
    draw.text((lx1 - 24 - (spb[2] - spb[0]), mid_y0 + 174), sl_pct_str, fill=RED_LIGHT, font=_font(16, bold=True, mono=True))

    # Net Risk/Reward row
    draw.line([(lx0 + 24, mid_y0 + 252), (lx0 + 46, mid_y0 + 230)], fill=CYAN, width=3)
    draw.text((lx0 + 62, mid_y0 + 224), "ریسک به ریوارد", fill=TEXT_MUTED, font=_font(13, bold=True))
    draw.text((lx0 + 62, mid_y0 + 244), f"1 : {net_rr:.2f}", fill=TEXT_WHITE, font=_font(26, bold=True, mono=True))
    mod_txt = (trade.entry_module or "SMC").upper()
    mb = draw.textbbox((0, 0), mod_txt, font=_font(16, bold=True))
    draw.text((lx1 - 24 - (mb[2] - mb[0]), mid_y0 + 250), mod_txt, fill=CYAN, font=_font(16, bold=True))

    # Right Card: TAKE PROFIT TARGETS
    rx0, rx1 = 554, 1044
    draw.rounded_rectangle([(rx0, mid_y0), (rx1, mid_y1)], radius=16, fill=BG_PANEL, outline=GOLD_BORDER, width=1)
    draw.text((rx0 + 22, mid_y0 + 18), "اهداف سود | TARGETS", fill=GOLD_BRIGHT, font=_font(17, bold=True))
    draw.line([(rx0 + 18, mid_y0 + 54), (rx1 - 18, mid_y0 + 54)], fill=BLUE_BORDER, width=1)

    tp_rows = [
        ("TP1", tp1, tp1_pct, rr1),
        ("TP2", tp2, tp2_pct, rr2),
        ("TP3", tp3, tp3_pct, rr3),
    ]
    for idx, (t_lbl, t_px, t_pct, t_rr) in enumerate(tp_rows):
        ry0 = mid_y0 + 70 + idx * 72
        ry1 = ry0 + 58
        draw.rounded_rectangle([(rx0 + 20, ry0), (rx1 - 20, ry1)], radius=12, fill=GREEN_BG, outline=GREEN_BORDER, width=1)
        draw.text((rx0 + 38, ry0 + 17), t_lbl, fill=GREEN_LIGHT, font=_font(18, bold=True))
        draw.text((rx0 + 104, ry0 + 13), f"{t_px:.{digits}f}", fill=TEXT_WHITE, font=_font(26, bold=True, mono=True))
        r_str = f"+{t_pct:.2f}% ({t_rr:.1f}R)"
        rf_tp = _font(15, bold=True, mono=True)
        rtb = draw.textbbox((0, 0), r_str, font=rf_tp)
        draw.text((rx1 - 36 - (rtb[2] - rtb[0]), ry0 + 19), r_str, fill=GREEN_LIGHT, font=rf_tp)

    # ------------------------------------------------------------------
    # 6. BOTTOM 2-COLUMN CARDS: TRADING INSTRUCTIONS  |  ENGINE DIAGNOSTICS
    # ------------------------------------------------------------------
    bot_y0, bot_y1 = 1040, 1266

    # Left Card: TRADING INSTRUCTIONS
    draw.rounded_rectangle([(lx0, bot_y0), (lx1, bot_y1)], radius=16, fill=BG_PANEL, outline=GOLD_BORDER, width=1)
    draw.text((lx0 + 22, bot_y0 + 18), "دستورالعمل اجرا | INSTRUCTIONS", fill=GOLD_BRIGHT, font=_font(17, bold=True))
    draw.line([(lx0 + 18, bot_y0 + 52), (lx1 - 18, bot_y0 + 52)], fill=BLUE_BORDER, width=1)

    tf_up = trade.timeframe.upper()
    htf_str = _setup_entry_label(trade.timeframe).split(" -> ")[0]
    bullets = [
        f"هم‌جهت با {htf_str}؛ ورود {tf_up} در محدوده {entry:.{digits}f} ({mod_txt}).",
        f"حد ضرر را دقیقاً روی {sl:.{digits}f} بگذارید (هرگز بازتر نکنید).",
        f"وقتی {get_policy(trade.timeframe).early_be_fraction * 100:.0f}% مسیر TP1 طی شد، حد ضرر را Bring to Break-Even کنید؛ TP1 روی {tp1:.{digits}f}.",
    ]
    bf = _font(14)
    for idx, btxt in enumerate(bullets):
        by = bot_y0 + 76 + idx * 48
        draw.ellipse([(lx0 + 24, by + 4), (lx0 + 35, by + 15)], fill=GOLD_BRIGHT)
        draw.text((lx0 + 46, by), btxt, fill=TEXT_WHITE, font=bf)

    # Right Card: ENGINE DIAGNOSTICS
    draw.rounded_rectangle([(rx0, bot_y0), (rx1, bot_y1)], radius=16, fill=BG_PANEL, outline=GOLD_BORDER, width=1)
    draw.text((rx0 + 22, bot_y0 + 18), "عیب‌یابی موتور | DIAGNOSTICS", fill=GOLD_BRIGHT, font=_font(17, bold=True))
    draw.line([(rx0 + 18, bot_y0 + 52), (rx1 - 18, bot_y0 + 52)], fill=BLUE_BORDER, width=1)

    wr_val = float(trade.backtest_win_rate_at_entry or 0.0)
    adx_txt = f"{adx_value:.1f}" if adx_value is not None else "32.0"
    diag_rows = [
        ("رژیم بازار", regime_txt, TEXT_WHITE),
        ("وین‌ریت بک‌تست", f"{wr_val:.1f}% — {'تأیید کانال' if trade.eligible_for_telegram else 'پایش دستی'}", GREEN_LIGHT if trade.eligible_for_telegram else GOLD_BRIGHT),
        ("ADX / امتیاز", f"{adx_txt}  /  {trade.confluence_score:.1f}", TEXT_WHITE),
        ("لنگر حد ضرر", f"{htf_anchor} POI / Swing", CYAN),
    ]
    dk_f = _font(15)
    dv_f = _font(16, bold=True, mono=True)
    for idx, (dk, dv, dcol) in enumerate(diag_rows):
        dy = bot_y0 + 68 + idx * 38
        draw.text((rx0 + 24, dy), dk, fill=TEXT_MUTED, font=dk_f)
        dvb = draw.textbbox((0, 0), dv, font=dv_f)
        draw.text((rx1 - 24 - (dvb[2] - dvb[0]), dy), dv, fill=dcol, font=dv_f)

    # ------------------------------------------------------------------
    # 7. FOOTER
    # ------------------------------------------------------------------
    _draw_hexagon_logo(draw, 54, 1304, 16)
    draw.text((82, 1292), "NEXVORA TEAM", fill=GOLD_BRIGHT, font=_font(18, bold=True))

    foot_r = f"Official Signal Card  •  {updated_str}"
    fr_f = _font(14)
    frb = draw.textbbox((0, 0), foot_r, font=fr_f)
    draw.text((1044 - (frb[2] - frb[0]), 1296), foot_r, fill=TEXT_MUTED, font=fr_f)

    # Apply subtle diagonal NEXVORA watermark on top
    final_img = _apply_watermark(img, "NEXVORA")

    buf = io.BytesIO()
    final_img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
