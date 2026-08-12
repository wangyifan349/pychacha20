"""
本脚本用于递归扫描用户指定的目录，将其中的图片、视频和音频文件分别整理到 media_sorted 下对应的分类目录中；遇到同名文件时会自动生成新的文件名以避免覆盖，并通过文件大小和 SHA-256 哈希值识别并删除内容完全相同的重复文件。媒体文件移动完成后，脚本会从深层目录开始清理原处理目录中的空文件夹，但不会清理输出目录；其他类型的文件不会被移动或删除。每次处理完成后会输出处理结果，并自动等待输入下一个需要处理的目录。
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
    input_text = os.path.expandvars(input_text)  # 展开路径中的环境变量
    if os.name != "nt":
        input_text = input_text.replace(r"\ ", " ")
    return Path(input_text).expanduser().resolve()  # 展开用户目录并转换为规范绝对路径
# ------------------------------------------------------------
def ask_directory() -> Path:
    while True:
        try:
            directory_path = normalize_path(input("请输入要扫描的目录："))
        except (KeyboardInterrupt, EOFError):
            raise SystemExit
        if directory_path.is_dir():  # 仅接受真实存在的目录
            return directory_path
        print(f"目录不存在或不是目录：{directory_path}")
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
        unique_file_path = file_path.with_name(f"{file_path.stem}_{file_index}{file_path.suffix}")  # 同名时追加序号
        if not unique_file_path.exists():
            return unique_file_path
        file_index += 1
# ------------------------------------------------------------
def calculate_file_hash(file_path: Path) -> str:
    hash_object = hashlib.sha256()  # 使用 SHA-256 计算文件内容指纹
    with file_path.open("rb") as file:
        for file_chunk in iter(lambda: file.read(4 * 1024 * 1024), b""):  # 每次分块读取 4 MB
            hash_object.update(file_chunk)
    return hash_object.hexdigest()
# ------------------------------------------------------------
def remove_empty_directories(source_directory: Path, output_directory: Path):
    directory_paths = sorted(
        (directory_path for directory_path in source_directory.rglob("*") if directory_path.is_dir()),
        key=lambda directory_path: len(directory_path.parts),
        reverse=True  # 从最深层目录开始处理
    )
    for directory_path in directory_paths:
        try:
            directory_path.relative_to(output_directory)
            continue  # 输出目录及其子目录不参与清理
        except ValueError:
            pass
        try:
            directory_path.rmdir()  # 仅空目录可以被 rmdir 删除
            print(f"删除空文件夹：{directory_path}")
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
        for file_path in source_directory.rglob("*"):  # 递归扫描处理目录
            if not file_path.is_file():
                continue
            try:
                file_path.relative_to(output_directory)
                continue  # 避免再次扫描已经整理到输出目录中的文件
            except ValueError:
                pass
            media_category = get_media_type(file_path)
            if media_category:
                media_files.append((file_path, media_category))
        if not media_files:
            remove_empty_directories(source_directory, output_directory)
            print("没有找到图片、视频或音频文件。\n")
            continue
        for directory_path in media_directories.values():
            directory_path.mkdir(parents=True, exist_ok=True)
        moved_files = []
        for file_path, media_category in media_files:
            target_path = get_unique_path(media_directories[media_category] / file_path.name)  # 防止同名文件覆盖
            try:
                shutil.move(str(file_path), str(target_path))  # 将媒体文件移动到对应分类目录
                moved_files.append(target_path)
                print(f"移动：{file_path} -> {target_path}")
            except OSError as error:
                print(f"移动失败：{file_path} ({error})")
        processed_files = {}
        deleted_file_count = 0
        for file_path in moved_files:
            if not file_path.exists():
                continue
            try:
                file_size = file_path.stat().st_size  # 文件大小作为重复判断的一部分
                file_hash = calculate_file_hash(file_path)
                file_identity = (file_size, file_hash)  # 大小与哈希均相同才视为重复文件
                if file_identity in processed_files:
                    print(f"删除重复：{file_path}，保留：{processed_files[file_identity]}")
                    file_path.unlink()  # 删除内容完全重复的文件
                    deleted_file_count += 1
                else:
                    processed_files[file_identity] = file_path
            except OSError as error:
                print(f"检查失败：{file_path} ({error})")
        remove_empty_directories(source_directory, output_directory)  # 清理原处理目录中移动后留下的空目录
        print(f"\n完成：移动 {len(moved_files)} 个文件，删除 {deleted_file_count} 个重复文件。")
        print(f"图片：{media_directories['images']}")
        print(f"视频：{media_directories['videos']}")
        print(f"音频：{media_directories['audios']}\n")
# ------------------------------------------------------------
if __name__ == "__main__":
    main()
