import sys
from io import BytesIO
from pathlib import Path

# Add backend directory to sys.path so we can import from app
sys.path.append(str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.services.storage_service import minio_client
from scripts.seed import SEED_PHOTO_OBJECTS


def main():
    settings = get_settings()
    client = minio_client(settings)
    bucket = settings.minio_bucket

    print(f"Connecting to MinIO endpoint: {settings.minio_endpoint}")
    print(f"Target Bucket: {bucket}")
    
    try:
        if not client.bucket_exists(bucket):
            print(f"Bucket '{bucket}' does not exist. Creating it...")
            client.make_bucket(bucket)
            
        uploaded = 0
        for object_key, (content_type, data) in SEED_PHOTO_OBJECTS.items():
            if len(data) <= 2000:
                print(f"Skipping placeholder file: {object_key} (size: {len(data)} bytes)")
                continue

            print(f"Uploading {object_key} ({len(data)} bytes, mime: {content_type})...")
            client.put_object(
                bucket,
                object_key,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            uploaded += 1
            
        print(f"\nSuccessfully force-pushed {uploaded} high-resolution test photos to storage!")
    except Exception as exc:
        print(f"\nError pushing to storage: {exc}")
        print("Make sure your MinIO instance is running and reachable.")

if __name__ == "__main__":
    main()
