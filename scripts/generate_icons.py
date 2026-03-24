"""
Generate application icons for ICCSFlux executables.

Creates .ico files with multiple sizes (16, 24, 32, 48, 64, 128, 256)
for Windows executables using Pillow.

Usage:
    python scripts/generate_icons.py

Output: assets/icons/*.ico
"""

import math
from pathlib import Path
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).parent.parent
ICON_DIR = PROJECT_ROOT / "assets" / "icons"
ICON_DIR.mkdir(parents=True, exist_ok=True)

# Standard Windows icon sizes
SIZES = [16, 24, 32, 48, 64, 128, 256]

def ri(v):
    """Round to int — all Pillow coords/widths must be integers."""
    return int(round(v))

def make_rounded_rect(draw, xy, radius, fill, outline=None, width=1):
    """Draw a rounded rectangle."""
    x0, y0, x1, y1 = [ri(v) for v in xy]
    r = min(ri(radius), (x1 - x0) // 2, (y1 - y0) // 2)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=r, fill=fill, outline=outline, width=ri(width))

def draw_waveform(draw, cx, cy, size, color, amplitude=None, periods=2.5):
    """Draw a sine waveform centered at (cx, cy)."""
    if amplitude is None:
        amplitude = size * 0.25
    half_w = size * 0.38
    points = []
    steps = max(40, ri(size))
    for i in range(steps + 1):
        t = i / steps
        x = cx - half_w + t * half_w * 2
        y = cy - amplitude * math.sin(t * periods * 2 * math.pi)
        points.append((ri(x), ri(y)))
    lw = max(1, ri(size / 32))
    draw.line(points, fill=color, width=lw)

def draw_signal_bars(draw, cx, cy, size, color):
    """Draw ascending signal bars (DAQ acquisition motif)."""
    bar_count = 5
    total_w = size * 0.55
    bar_w = total_w / (bar_count * 2) * 0.9
    max_h = size * 0.45
    base_y = cy + size * 0.15

    for i in range(bar_count):
        h = max_h * (i + 1) / bar_count
        x = cx - total_w / 2 + i * (total_w / (bar_count - 1)) - bar_w / 2
        y_top = base_y - h
        draw.rounded_rectangle(
            [ri(x), ri(y_top), ri(x + bar_w), ri(base_y)],
            radius=max(1, ri(bar_w / 4)),
            fill=color,
        )

def draw_cloud_arrow(draw, cx, cy, size, color, arrow_color):
    """Draw a cloud with an upload arrow."""
    s = size
    cloud_y = cy - s * 0.05
    r1 = s * 0.22
    r2 = s * 0.16
    r3 = s * 0.14
    r_top = s * 0.18

    # Cloud ellipses
    draw.ellipse([ri(cx - r1), ri(cloud_y - r1 * 0.6), ri(cx + r1), ri(cloud_y + r1 * 0.6)], fill=color)
    draw.ellipse([ri(cx - r1 - r2 * 0.3), ri(cloud_y - r2 * 0.8), ri(cx - r1 * 0.2), ri(cloud_y + r2 * 0.4)], fill=color)
    draw.ellipse([ri(cx + r1 * 0.2), ri(cloud_y - r3 * 0.7), ri(cx + r1 + r3 * 0.3), ri(cloud_y + r3 * 0.5)], fill=color)
    draw.ellipse([ri(cx - r_top), ri(cloud_y - r1 * 0.6 - r_top * 0.8), ri(cx + r_top), ri(cloud_y - r1 * 0.1)], fill=color)

    # Upload arrow
    arrow_y = cy + s * 0.05
    arrow_h = s * 0.22
    arrow_w = s * 0.06
    head_w = s * 0.14

    draw.rectangle(
        [ri(cx - arrow_w), ri(arrow_y - arrow_h * 0.3), ri(cx + arrow_w), ri(arrow_y + arrow_h)],
        fill=arrow_color,
    )
    draw.polygon(
        [
            (ri(cx), ri(arrow_y - arrow_h * 0.8)),
            (ri(cx - head_w), ri(arrow_y - arrow_h * 0.15)),
            (ri(cx + head_w), ri(arrow_y - arrow_h * 0.15)),
        ],
        fill=arrow_color,
    )

def draw_modbus_icon(draw, cx, cy, size, color1, color2):
    """Draw network/protocol motif for Modbus tool."""
    s = size
    node_r = s * 0.08
    draw.ellipse(
        [ri(cx - node_r * 1.5), ri(cy - node_r * 1.5), ri(cx + node_r * 1.5), ri(cy + node_r * 1.5)],
        fill=color1,
    )

    ring_r = s * 0.28
    lw = max(1, ri(size / 40))
    for i in range(6):
        angle = i * math.pi * 2 / 6 - math.pi / 2
        nx = cx + ring_r * math.cos(angle)
        ny = cy + ring_r * math.sin(angle)
        draw.line([(ri(cx), ri(cy)), (ri(nx), ri(ny))], fill=color2, width=lw)
        draw.ellipse(
            [ri(nx - node_r), ri(ny - node_r), ri(nx + node_r), ri(ny + node_r)],
            fill=color1,
        )

    # Register blocks
    block_w = s * 0.08
    block_h = s * 0.06
    block_y = cy + s * 0.15
    for i in range(4):
        bx = cx - s * 0.18 + i * s * 0.12
        draw.rectangle(
            [ri(bx - block_w / 2), ri(block_y), ri(bx + block_w / 2), ri(block_y + block_h)],
            fill=color2,
            outline=color1,
            width=max(1, lw // 2),
        )

def generate_icon(name, draw_func, bg_color, sizes=None):
    """Generate a multi-size .ico file."""
    if sizes is None:
        sizes = SIZES
    images = []
    for sz in sizes:
        img = Image.new("RGBA", (sz, sz), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        margin = max(1, sz // 16)
        radius = max(2, sz // 6)
        make_rounded_rect(
            draw,
            [margin, margin, sz - margin, sz - margin],
            radius=radius,
            fill=bg_color,
        )

        cx, cy = sz / 2, sz / 2
        content_size = sz - margin * 2
        draw_func(draw, cx, cy, content_size)

        images.append(img)

    ico_path = ICON_DIR / f"{name}.ico"
    images[-1].save(
        str(ico_path),
        format="ICO",
        sizes=[(img.width, img.height) for img in images],
        append_images=images[:-1],
    )
    print(f"  Created: {ico_path.relative_to(PROJECT_ROOT)} ({len(images)} sizes)")
    return ico_path

# --- Color palette ---
TEAL_BG = (13, 42, 58, 255)
TEAL_ACCENT = (0, 188, 212, 255)
WHITE = (255, 255, 255, 255)
LIGHT_GRAY = (200, 215, 225, 255)

GREEN_BG = (15, 45, 30, 255)
GREEN_ACCENT = (76, 175, 80, 255)
GREEN_LIGHT = (165, 214, 167, 255)

AZURE_BG = (15, 30, 55, 255)
AZURE_ACCENT = (0, 120, 212, 255)

ORANGE_BG = (50, 30, 10, 255)
ORANGE_ACCENT = (255, 152, 0, 255)
ORANGE_LIGHT = (255, 204, 128, 255)

def draw_iccsflux(draw, cx, cy, size):
    """Main app: waveform with 'F' lettermark."""
    draw_waveform(draw, cx, cy - size * 0.08, size, TEAL_ACCENT, amplitude=size * 0.18, periods=2)
    lw = max(1, ri(size / 40))
    y_base = cy + size * 0.22
    draw.line(
        [(ri(cx - size * 0.35), ri(y_base)), (ri(cx + size * 0.35), ri(y_base))],
        fill=LIGHT_GRAY,
        width=lw,
    )
    f_h = size * 0.16
    f_w = size * 0.10
    f_x = cx - f_w / 2
    f_y = y_base - f_h - size * 0.02
    flw = max(1, ri(size / 48))
    draw.line([(ri(f_x), ri(f_y)), (ri(f_x), ri(f_y + f_h))], fill=WHITE, width=flw + 1)
    draw.line([(ri(f_x), ri(f_y)), (ri(f_x + f_w), ri(f_y))], fill=WHITE, width=flw)
    draw.line([(ri(f_x), ri(f_y + f_h * 0.45)), (ri(f_x + f_w * 0.75), ri(f_y + f_h * 0.45))], fill=WHITE, width=flw)

def draw_daqservice(draw, cx, cy, size):
    """DAQ Service: signal bars + waveform."""
    draw_signal_bars(draw, cx, cy - size * 0.05, size, GREEN_ACCENT)
    draw_waveform(draw, cx, cy - size * 0.28, size * 0.7, GREEN_LIGHT, amplitude=size * 0.06, periods=3)
    lw = max(1, ri(size / 40))
    y_base = cy + size * 0.32
    draw.line(
        [(ri(cx - size * 0.3), ri(y_base)), (ri(cx + size * 0.3), ri(y_base))],
        fill=GREEN_LIGHT,
        width=lw,
    )

def draw_azure(draw, cx, cy, size):
    """Azure Uploader: cloud with upload arrow."""
    draw_cloud_arrow(draw, cx, cy, size, AZURE_ACCENT, WHITE)

def draw_modbus(draw, cx, cy, size):
    """Modbus Tool: network nodes."""
    draw_modbus_icon(draw, cx, cy, size, ORANGE_ACCENT, ORANGE_LIGHT)

def main():
    print("Generating ICCSFlux application icons...")
    print(f"Output directory: {ICON_DIR.relative_to(PROJECT_ROOT)}")
    print()

    generate_icon("iccsflux", draw_iccsflux, TEAL_BG)
    generate_icon("daq_service", draw_daqservice, GREEN_BG)
    generate_icon("azure_uploader", draw_azure, AZURE_BG)
    generate_icon("modbus_tool", draw_modbus, ORANGE_BG)

    print()
    print("Done! Icons generated:")
    for ico in sorted(ICON_DIR.glob("*.ico")):
        print(f"  {ico.name}")

if __name__ == "__main__":
    main()
