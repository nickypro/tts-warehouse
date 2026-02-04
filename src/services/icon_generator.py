"""Generate simple letter icons for feeds."""

import hashlib
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont


def get_color_for_name(name: str) -> tuple:
    """Generate a consistent color based on the name."""
    # Hash the name to get a consistent color
    hash_bytes = hashlib.md5(name.encode()).digest()

    # Use first 3 bytes for RGB, but keep colors vibrant
    r = 100 + (hash_bytes[0] % 156)  # 100-255
    g = 100 + (hash_bytes[1] % 156)
    b = 100 + (hash_bytes[2] % 156)

    return (r, g, b)


def generate_letter_icon(name: str, size: int = 200) -> bytes:
    """
    Generate a simple icon with the first letter of the name.

    Args:
        name: Name to generate icon for
        size: Size of the square icon in pixels

    Returns:
        PNG image as bytes
    """
    # Get consistent color for this name
    bg_color = get_color_for_name(name)

    # Create image
    img = Image.new('RGB', (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    # Get the first letter
    letter = name[0].upper() if name else "?"

    # Try to use a built-in font, fall back to default
    font_size = int(size * 0.6)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except (IOError, OSError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
        except (IOError, OSError):
            # Fall back to default font (smaller)
            font = ImageFont.load_default()

    # Calculate text position (centered)
    bbox = draw.textbbox((0, 0), letter, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (size - text_width) // 2
    y = (size - text_height) // 2 - bbox[1]  # Adjust for font ascent

    # Draw white letter
    draw.text((x, y), letter, fill=(255, 255, 255), font=font)

    # Save to bytes
    buffer = BytesIO()
    img.save(buffer, format='PNG')
    buffer.seek(0)

    return buffer.getvalue()
