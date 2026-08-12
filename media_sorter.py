"""
This script recursively scans a user-specified directory and organizes image, video, and audio files into their corresponding category folders under media_sorted. If files with the same name are encountered, a new filename is generated automatically to prevent overwriting. Duplicate files are identified and removed by comparing both file size and SHA-256 hash values. After media files are moved, the script removes empty folders from the original source directory starting from the deepest level, while leaving the output directory untouched. All other file types remain unchanged. After each directory is processed, a summary is displayed and the script automatically waits for the next directory to process.
"""
from pathlib import Path
import hashlib
import shutil
import os
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff", ".heic", ".avif"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v", ".flv", ".wmv", ".mpeg", ".mpg", ".3gp"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".aiff", ".ape"}
# ------------------------------------------------------------
def normalize_path(input_text: str) -> Path:
    input_text = input_text.strip().strip('"\'“”‘’')
    input_text = os.path.expandvars(input_text)  # Expand environment variables in the path
    if os.name != "nt":
        input_text = input_text.replace(r"\ ", " ")
    return Path(input_text).expanduser().resolve()  # Expand the user directory and convert to a normalized absolute path
# ------------------------------------------------------------
def ask_directory() -> Path:
    while True:
        try:
            directory_path = normalize_path(input("Enter the directory to scan: "))
        except (KeyboardInterrupt, EOFError):
            raise SystemExit
        if directory_path.is_dir():  # Only accept an existing directory
            return directory_path
        print(f"Directory does not exist or is not a directory: {directory_path}")
# ------------------------------------------------------------
def get_media_type(file_path: Path):
    file_extension = file_path.suffix.lower()
    if file_extension in IMAGE_EXTENSIONS:
        return "images"
    if file_extension in VIDEO_EXTENSIONS:
        return "videos"
    if file_extension in AUDIO_EXTENSIONS:
        return "audios"
    return None
# ------------------------------------------------------------
def get_unique_path(file_path: Path) -> Path:
    if not file_path.exists():
        return file_path
    file_index = 1
    while True:
        unique_file_path = file_path.with_name(f"{file_path.stem}_{file_index}{file_path.suffix}")  # Append an index when a filename already exists
        if not unique_file_path.exists():
            return unique_file_path
        file_index += 1
# ------------------------------------------------------------
def calculate_file_hash(file_path: Path) -> str:
    hash_object = hashlib.sha256()  # Use SHA-256 to calculate the file content fingerprint
    with file_path.open("rb") as file:
        for file_chunk in iter(lambda: file.read(4 * 1024 * 1024), b""):  # Read the file in 4 MB chunks
            hash_object.update(file_chunk)
    return hash_object.hexdigest()
# ------------------------------------------------------------
def remove_empty_directories(source_directory: Path, output_directory: Path):
    directory_paths = sorted(
        (directory_path for directory_path in source_directory.rglob("*") if directory_path.is_dir()),
        key=lambda directory_path: len(directory_path.parts),
        reverse=True  # Process the deepest directories first
    )
    for directory_path in directory_paths:
        try:
            directory_path.relative_to(output_directory)
            continue  # Do not remove the output directory or its subdirectories
        except ValueError:
            pass
        try:
            directory_path.rmdir()  # rmdir only removes empty directories
            print(f"Removed empty directory: {directory_path}")
        except OSError:
            pass
# ------------------------------------------------------------
def main():
    while True:
        source_directory = ask_directory()
        output_directory = source_directory / "media_sorted"
        media_directories = {
            "images": output_directory / "images",
            "videos": output_directory / "videos",
            "audios": output_directory / "audios",
        }
        media_files = []
        for file_path in source_directory.rglob("*"):  # Recursively scan the source directory
            if not file_path.is_file():
                continue
            try:
                file_path.relative_to(output_directory)
                continue  # Avoid scanning files that have already been organized into the output directory
            except ValueError:
                pass
            media_category = get_media_type(file_path)
            if media_category:
                media_files.append((file_path, media_category))
        if not media_files:
            remove_empty_directories(source_directory, output_directory)
            print("No image, video, or audio files were found.\n")
            continue
        for directory_path in media_directories.values():
            directory_path.mkdir(parents=True, exist_ok=True)
        moved_files = []
        for file_path, media_category in media_files:
            target_path = get_unique_path(media_directories[media_category] / file_path.name)  # Prevent files with the same name from being overwritten
            try:
                shutil.move(str(file_path), str(target_path))  # Move the media file to its corresponding category directory
                moved_files.append(target_path)
                print(f"Moved: {file_path} -> {target_path}")
            except OSError as error:
                print(f"Move failed: {file_path} ({error})")
        processed_files = {}
        deleted_file_count = 0
        for file_path in moved_files:
            if not file_path.exists():
                continue
            try:
                file_size = file_path.stat().st_size  # Use file size as part of duplicate detection
                file_hash = calculate_file_hash(file_path)
                file_identity = (file_size, file_hash)  # Treat files as duplicates only when both size and hash are identical
                if file_identity in processed_files:
                    print(f"Removed duplicate: {file_path}, kept: {processed_files[file_identity]}")
                    file_path.unlink()  # Remove the file when its content is completely identical
                    deleted_file_count += 1
                else:
                    processed_files[file_identity] = file_path
            except OSError as error:
                print(f"Check failed: {file_path} ({error})")
        remove_empty_directories(source_directory, output_directory)  # Remove empty directories left in the original source directory
        print(f"\nCompleted: moved {len(moved_files)} files, removed {deleted_file_count} duplicate files.")
        print(f"Images: {media_directories['images']}")
        print(f"Videos: {media_directories['videos']}")
        print(f"Audio: {media_directories['audios']}\n")
# ------------------------------------------------------------
if __name__ == "__main__":
    main()
