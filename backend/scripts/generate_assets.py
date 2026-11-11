from pathlib import Path

from PIL import Image, ImageDraw

BRAIN_DIR = Path("/Users/qts/.gemini/antigravity-ide/brain/8db6cf06-1ec3-44ea-9ee7-406361996c4a")
ASSETS_DIR = Path(__file__).resolve().parent / "assets"

PNG_SOURCES = {
    "site_overview.jpg": "site_overview_1780099574902.png",
    "blockwork_day5.jpg": "blockwork_progress_1780099598070.png",
}

def create_variants(img: Image.Image, base_name: str) -> None:
    # 1. Save original as high-quality JPEG
    original_path = ASSETS_DIR / base_name
    img.save(original_path, format="JPEG", quality=90)
    print(f"Saved original: {original_path} ({original_path.stat().st_size} bytes)")

    # 2. Save compressed variant (display)
    display = img.copy()
    display.thumbnail((1600, 1600))
    
    # Draw watermark matching PhotoService
    draw = ImageDraw.Draw(display)
    # Using default font, if custom is needed, it defaults to basic
    draw.text(
        (12, max(display.height - 28, 12)),
        "Garrisons Investments",
        fill=(255, 255, 255),
    )
    
    compressed_name = base_name.replace(".jpg", "_compressed.jpg")
    compressed_path = ASSETS_DIR / compressed_name
    display.save(compressed_path, format="JPEG", quality=82)
    print(f"Saved compressed: {compressed_path} ({compressed_path.stat().st_size} bytes)")

    # 3. Save thumbnail variant
    thumbnail = img.copy()
    thumbnail.thumbnail((360, 360))
    
    thumb_name = base_name.replace(".jpg", "_thumb.jpg")
    thumb_path = ASSETS_DIR / thumb_name
    thumbnail.save(thumb_path, format="JPEG", quality=75)
    print(f"Saved thumbnail: {thumb_path} ({thumb_path.stat().st_size} bytes)")

def main():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    
    for dest_jpg, src_png in PNG_SOURCES.items():
        src_path = BRAIN_DIR / src_png
        if not src_path.exists():
            print(f"Source PNG not found at {src_path}")
            continue
            
        print(f"Processing {src_png} -> {dest_jpg}...")
        with Image.open(src_path) as img:
            img_rgb = img.convert("RGB")
            create_variants(img_rgb, dest_jpg)

if __name__ == "__main__":
    main()
