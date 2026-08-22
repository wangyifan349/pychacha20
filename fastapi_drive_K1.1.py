from __future__ import annotations

# FastAPI Drive K1.1
#
# 程序介绍：
# 本程序是一个基于 FastAPI 的单文件、多用户网络文件管理程序。
# 用户登录后拥有独立的文件存储目录，可在浏览器中完成文件和文件夹的上传、
# 下载、新建、重命名、移动、删除、批量选择、拖放移动以及目录浏览等操作。
#
# 主要功能：
# 1. 用户系统
#    支持注册、登录和会话保持，不同用户使用独立的物理文件目录，互不混用。
#
# 2. 文件管理
#    支持文件和文件夹上传、文件夹结构上传、新建文件夹、重命名、移动、删除、
#    多选、框选、Ctrl/Cmd 多选、Shift 连选、拖放移动以及外部拖拽上传。
#
# 3. 文件下载与 7z 打包
#    普通文件可直接下载；文件夹或多个选中项目可使用 py7zr 打包为 7z 后下载。
#
# 4. 在线文本编辑
#    支持常见文本和代码文件在线打开、编辑和保存。
#    文本编码检测只使用 charset_normalizer.from_bytes，保存时尽量保持原编码，
#    无法按原编码保存时转换为 UTF-8。
#
# 5. 图片在线查看
#    图片通过独立浏览器窗口查看，支持缩小、放大、显示当前缩放比例和适应窗口。
#    图片查看窗口同时提供下载和关闭操作。
#
# 6. 视频在线播放
#    视频通过独立浏览器窗口播放，使用浏览器原生播放器。
#    播放区域尽量占满可用窗口空间，并支持浏览器原生进度拖动和播放控制。
#
# 7. 音频在线播放
#    音频通过独立浏览器窗口播放，使用浏览器原生音频播放器。
#
# 8. PDF 在线查看
#    PDF 通过独立浏览器窗口查看，内容区域尽量铺满可用窗口空间，
#    查看窗口同时提供下载和关闭操作。
#
# 9. 分享功能
#    可以为文件或文件夹创建独立分享链接。
#    分享文件夹后，访问者可以继续浏览其内部目录和文件。
#    分享页面支持文件下载、目录/多项目打包下载，以及受支持文件的在线查看。
#    分享的文本文件使用与私人文本查看相同的界面，并以只读方式打开。
#
# 10. 分享管理
#     提供独立的分享管理页面，可查看当前分享位置、分享链接和创建时间，
#     并支持打开分享链接、复制链接和取消分享。
#
# 11. 数据存储
#     实际文件只保存在 storage/users/<user_id>/files 目录中，不写入数据库。
#     users.db 只保存账户信息，shares.db 只保存当前有效的分享链接记录。
#
# 12. 界面与交互
#     文件区域采用紧凑卡片布局，支持面包屑目录导航、右键菜单、多项目选择、
#     双向框选、拖放操作以及独立的在线查看窗口。
#
# 主要依赖：
# fastapi
# uvicorn
# python-multipart
# py7zr
# charset-normalizer
#
# 启动方式：
# python fastapi_drive_K1.py
#
# K1.1 基线：
# K1 基础上移除普通不可预览文件右键菜单中的多余分隔线。

import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import py7zr
from charset_normalizer import from_bytes
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
)
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

# ==================== 启动配置 ====================
HOST = "0.0.0.0"  # 监听地址：0.0.0.0 = 本机和局域网均可访问
PORT = 8000  # Web 访问端口：需要换端口只改这里
LOG_LEVEL = "info"  # Uvicorn 日志级别
# =================================================

BASE_DIR = Path(__file__).resolve().parent
STORAGE_ROOT = (BASE_DIR / "storage").resolve()
USERS_ROOT = (STORAGE_ROOT / "users").resolve()
# 每个用户只访问 storage/users/<user_id>/files，文件内容不进数据库。
USERS_DB = (BASE_DIR / "users.db").resolve()  # 仅账户信息
SHARES_DB = (BASE_DIR / "shares.db").resolve()  # 仅分享链接
SECRET_FILE = (BASE_DIR / "secret.key").resolve()
USERS_ROOT.mkdir(parents=True, exist_ok=True)

MAX_TEXT_FILE_SIZE = 5 * 1024 * 1024
INVALID_NAME_RE = re.compile(r'[<>:"|?*\\/\x00-\x1f]')
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\-\.]{3,32}$")

TEXT_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".js",
    ".ts",
    ".jsx",
    ".tsx",
    ".css",
    ".scss",
    ".html",
    ".htm",
    ".json",
    ".xml",
    ".csv",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".conf",
    ".cfg",
    ".log",
    ".sql",
    ".sh",
    ".bat",
    ".cmd",
    ".ps1",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".java",
    ".go",
    ".rs",
    ".php",
    ".rb",
    ".env",
}
IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".webp",
    ".bmp",
    ".avif",
    ".ico",
    ".svg",
}
VIDEO_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".ogv",
    ".mov",
    ".m4v",
}
AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".ogg",
    ".oga",
    ".m4a",
    ".aac",
    ".flac",
    ".opus",
}
PDF_EXTENSIONS = {".pdf"}


# -----------------------------------------------------------------------------
# 应用与数据库基础设施
# -----------------------------------------------------------------------------
def load_secret() -> str:
    env = os.environ.get("FASTAPI_DRIVE_SECRET_KEY")
    if env:
        return env
    if SECRET_FILE.exists():
        value = SECRET_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    value = secrets.token_urlsafe(48)
    try:
        SECRET_FILE.write_text(value, encoding="utf-8")
    except OSError:
        pass
    return value


app = FastAPI(title="FastAPI Drive")
app.add_middleware(
    SessionMiddleware,
    secret_key=load_secret(),
    same_site="lax",
    max_age=30 * 24 * 3600,
)


def current_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def open_users_db() -> sqlite3.Connection:
    connection = sqlite3.connect(USERS_DB)
    connection.row_factory = sqlite3.Row
    return connection


def open_shares_db() -> sqlite3.Connection:
    connection = sqlite3.connect(SHARES_DB)
    connection.row_factory = sqlite3.Row
    return connection


def init_db() -> None:
    # users.db 只保存登录/注册账户信息。
    with open_users_db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

    # shares.db 只保存当前有效的分享链接。
    # 不保存文件列表、大小、类型、显示名、下载次数、最后访问时间等文件元数据。
    expected_columns = ["id", "token", "user_id", "rel_path", "created_at"]

    with open_shares_db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='shares'"
        ).fetchone()

        if not exists:
            conn.execute(
                """
                CREATE TABLE shares (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL,
                    rel_path TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
        else:
            old_columns = [
                row[1]
                for row in conn.execute("PRAGMA table_info(shares)").fetchall()
            ]

            # 自动把旧版较宽的分享表收缩为最小表结构。
            if old_columns != expected_columns:
                rows = conn.execute("SELECT * FROM shares").fetchall()
                old_column_set = set(old_columns)

                conn.execute("DROP TABLE IF EXISTS shares_minimal")
                conn.execute(
                    """
                    CREATE TABLE shares_minimal (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        token TEXT NOT NULL UNIQUE,
                        user_id INTEGER NOT NULL,
                        rel_path TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )

                for row in rows:
                    # 旧版已取消的分享不再保留。
                    if "is_active" in old_column_set and not int(row["is_active"] or 0):
                        continue
                    token = row["token"] if "token" in old_column_set else ""
                    rel = row["rel_path"] if "rel_path" in old_column_set else ""
                    user_id = int(row["user_id"] or 0) if "user_id" in old_column_set else 0
                    created_at = (
                        row["created_at"]
                        if "created_at" in old_column_set and row["created_at"]
                        else current_timestamp()
                    )
                    if not token or rel is None:
                        continue
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO shares_minimal(id, token, user_id, rel_path, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (row["id"] if "id" in old_column_set else None, token, user_id, rel, created_at),
                    )

                conn.execute("DROP TABLE shares")
                conn.execute("ALTER TABLE shares_minimal RENAME TO shares")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_shares_token ON shares(token)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_shares_user_path ON shares(user_id, rel_path)")
        conn.commit()


init_db()


# -----------------------------------------------------------------------------
# 登录、会话与用户目录
# -----------------------------------------------------------------------------
def password_hash(password: str) -> str:
    salt = os.urandom(16)
    rounds = 240_000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    # 兼容参考 Flask 成品旧 users.db 中的 SHA-256 摘要。
    if re.fullmatch(r"[0-9a-fA-F]{64}", stored or ""):
        expected = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(expected, stored.lower())
    try:
        algo, rounds, salt_hex, digest_hex = stored.split("$", 3)
        if algo != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(rounds),
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    except Exception:
        return False


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with open_users_db() as conn:
        row = conn.execute(
            "SELECT id, username, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        request.session.clear()
        return None
    return dict(row)


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(401, "请先登录")
    return user


def user_files_root(user_id: int) -> Path:
    root = (USERS_ROOT / str(user_id) / "files").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def migrate_legacy_storage_to_first_user(user_id: int) -> None:
    """首次启用账号体系时，保留旧版 storage/ 根目录中的现有文件。"""
    user_root = user_files_root(user_id)
    legacy_items = [
        p for p in STORAGE_ROOT.iterdir()
        if p.name != "users"
    ]
    if not legacy_items or any(user_root.iterdir()):
        return

    for source in legacy_items:
        target = unique_target(user_root / source.name)
        shutil.move(str(source), str(target))

    # 旧 FastAPI 版本的分享记录没有 user_id，迁移给首个用户。
    with open_shares_db() as conn:
        conn.execute(
            "UPDATE shares SET user_id = ? WHERE user_id = 0",
            (user_id,),
        )
        conn.commit()


# -----------------------------------------------------------------------------
# 路径、文件与预览工具
# -----------------------------------------------------------------------------
def normalize_rel_path(raw: str = "") -> str:
    raw = (raw or "").strip().replace("\\", "/").strip("/")
    if not raw:
        return ""
    parts = []
    for part in PurePosixPath(raw).parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise HTTPException(400, "非法路径")
        parts.append(part)
    return "/".join(parts)


def resolve_user_path(user_id: int, rel_path: str = "") -> tuple[str, Path]:
    rel_path = normalize_rel_path(rel_path)
    root = user_files_root(user_id)
    abs_path = (root / rel_path).resolve()
    if abs_path != root and root not in abs_path.parents:
        raise HTTPException(400, "非法路径")
    return rel_path, abs_path


def path_to_rel(user_id: int, path: Path) -> str:
    root = user_files_root(user_id)
    return "" if path == root else path.relative_to(root).as_posix()


def clean_name(name: str) -> str:
    name = (name or "").strip().replace("\u200b", "").rstrip(". ")
    if not name or name in {".", ".."}:
        raise HTTPException(400, "名称不合法")
    if INVALID_NAME_RE.search(name):
        raise HTTPException(400, "名称中包含非法字符")
    return name


def normalize_upload_rel_path(raw: str) -> list[str]:
    raw = (raw or "").replace("\\", "/").strip("/")
    if not raw:
        return []
    parts = []
    for part in PurePosixPath(raw).parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise HTTPException(400, "上传目录结构中存在非法路径")
        parts.append(clean_name(part))
    return parts


def unique_target(target: Path) -> Path:
    if not target.exists():
        return target
    stem = target.stem if target.suffix else target.name
    suffix = target.suffix if target.suffix else ""
    i = 1
    while True:
        candidate = target.with_name(f"{stem} ({i}){suffix}")
        if not candidate.exists():
            return candidate
        i += 1


def preview_kind(path: Path) -> str:
    if not path.is_file():
        return "none"
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return "text"
    if suffix in IMAGE_EXTENSIONS:
        return "image"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in PDF_EXTENSIONS:
        return "pdf"
    return "none"


def collapse_nested_paths(paths: list[Path]) -> list[Path]:
    result = []
    seen = set()
    for path in sorted(paths, key=lambda x: (len(x.parts), str(x).lower())):
        if str(path) in seen:
            continue
        seen.add(str(path))
        if any(parent in path.parents for parent in result):
            continue
        result.append(path)
    return result


def resolve_many(user_id: int, paths: list[str]) -> list[Path]:
    if not paths:
        raise HTTPException(400, "paths 不能为空")
    root = user_files_root(user_id)
    result = []
    for rel in paths:
        _, path = resolve_user_path(user_id, rel)
        if path == root:
            raise HTTPException(400, "根目录不能参与该操作")
        if not path.exists():
            raise HTTPException(404, f"路径不存在：{rel}")
        result.append(path)
    return collapse_nested_paths(result)


def read_preview_text(path: Path) -> tuple[str, str]:
    if path.stat().st_size > MAX_TEXT_FILE_SIZE:
        raise HTTPException(400, "文本文件超过 5MB，请下载后查看")

    raw = path.read_bytes()
    if not raw:
        return "", "utf-8"

    matches = from_bytes(raw)
    best = matches.best()
    if best is None or not best.encoding:
        raise HTTPException(400, "无法可靠识别当前文本编码")

    # 短中文文本的一致性分数可能很低；候选中存在国标编码时优先使用。
    # 检测来源仍然只有 charset_normalizer。
    if float(best.percent_coherence or 0) <= 1.0:
        for candidate in matches:
            encoding = (candidate.encoding or "").lower().replace("-", "_")
            if encoding in {"gb18030", "gbk", "gb2312", "cp936"}:
                return str(candidate), candidate.encoding

    return str(best), best.encoding


def encode_preview_text(content: str, preferred_encoding: str):
    encoding = (preferred_encoding or "utf-8").strip() or "utf-8"
    try:
        return content.encode(encoding), encoding, False
    except (UnicodeEncodeError, LookupError):
        return content.encode("utf-8"), "utf-8", True


def create_7z(
    paths: list[Path],
    archive_name: str,
    background_tasks: BackgroundTasks,
):
    selected = collapse_nested_paths(paths)
    fd, tmp_name = tempfile.mkstemp(prefix="fastapi-drive-", suffix=".7z")
    os.close(fd)
    tmp = Path(tmp_name)

    filters = [{"id": py7zr.FILTER_LZMA2, "preset": 7}]
    with py7zr.SevenZipFile(tmp, "w", filters=filters) as archive:
        if len(selected) == 1:
            path = selected[0]
            if path.is_file():
                archive.write(path, arcname=path.name)
            else:
                archive.writeall(path, arcname=path.name)
        else:
            common_parent = Path(
                os.path.commonpath([str(path.parent) for path in selected])
            )
            for path in selected:
                arcname = path.relative_to(common_parent).as_posix()
                if path.is_file():
                    archive.write(path, arcname=arcname)
                else:
                    archive.writeall(path, arcname=arcname)

    background_tasks.add_task(tmp.unlink, missing_ok=True)
    if not archive_name.lower().endswith(".7z"):
        archive_name += ".7z"
    return FileResponse(
        tmp,
        filename=Path(archive_name).name,
        media_type="application/x-7z-compressed",
    )


def get_share(token: str):
    with open_shares_db() as conn:
        return conn.execute(
            """
            SELECT id, token, user_id, rel_path, created_at
            FROM shares
            WHERE token = ?
            """,
            (token,),
        ).fetchone()


def resolve_public_share_target(share, subpath: str = ""):
    user_id = int(share["user_id"])
    _, shared_root = resolve_user_path(user_id, share["rel_path"])
    if not shared_root.exists():
        raise HTTPException(404, "分享源不存在")

    subpath = normalize_rel_path(subpath)
    if shared_root.is_file():
        return shared_root, shared_root, ""

    target = shared_root if not subpath else (shared_root / subpath).resolve()
    if target != shared_root and shared_root not in target.parents:
        raise HTTPException(400, "非法路径")
    if not target.exists():
        raise HTTPException(404, "对象不存在")
    return shared_root, target, subpath


def resolve_public_many(share, paths: list[str]) -> list[Path]:
    if not paths:
        raise HTTPException(400, "paths 不能为空")

    shared_root, _, _ = resolve_public_share_target(share, "")
    if shared_root.is_file():
        return [shared_root]

    result = []
    for rel in paths:
        rel = normalize_rel_path(rel)
        path = (shared_root / rel).resolve()
        if path != shared_root and shared_root not in path.parents:
            raise HTTPException(400, "非法路径")
        if path == shared_root or not path.exists():
            raise HTTPException(404, f"对象不存在：{rel}")
        result.append(path)
    return collapse_nested_paths(result)


def update_share_paths(user_id: int, old_path: str, new_path: str) -> None:
    """文件或文件夹移动/重命名后，同步更新其分享记录路径。"""
    with open_shares_db() as conn:
        rows = conn.execute(
            """
            SELECT id, rel_path
            FROM shares
            WHERE user_id = ?
              AND (rel_path = ? OR rel_path LIKE ?)
            """,
            (user_id, old_path, old_path + "/%"),
        ).fetchall()

        for row in rows:
            updated_path = new_path + row["rel_path"][len(old_path):]
            conn.execute(
                "UPDATE shares SET rel_path = ? WHERE id = ?",
                (updated_path, row["id"]),
            )

        conn.commit()


def html_escape(value: str) -> str:
    return html.escape(value, quote=True)


# -----------------------------------------------------------------------------
# API 请求模型
# -----------------------------------------------------------------------------
class MkdirBody(BaseModel):
    path: str = ""
    name: str


class RenameBody(BaseModel):
    path: str
    new_name: str


class PathsBody(BaseModel):
    paths: list[str]


class MoveBody(BaseModel):
    paths: list[str]
    dst_dir: str


class TextSaveBody(BaseModel):
    path: str
    content: str
    encoding: str = "utf-8"


class ShareCreateBody(BaseModel):
    path: str


class ShareCancelBody(BaseModel):
    share_id: int


# -----------------------------------------------------------------------------
# 登录 / 注册 / 页面入口
# -----------------------------------------------------------------------------
@app.get("/")
def home(request: Request):
    target = "/drive" if current_user(request) else "/login"
    return RedirectResponse(target, status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_user(request):
        return RedirectResponse("/drive", status_code=303)
    return HTMLResponse(
        AUTH_HTML.replace("__MODE__", "login").replace("__ERROR__", "")
    )


@app.post("/login")
def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
):
    username = username.strip()

    with open_users_db() as conn:
        row = conn.execute(
            "SELECT id, username, password_sha256 FROM users WHERE username = ?",
            (username,),
        ).fetchone()

        if not row or not verify_password(password, row["password_sha256"]):
            html = (
                AUTH_HTML
                .replace("__MODE__", "login")
                .replace("__ERROR__", "用户名或密码错误")
            )
            return HTMLResponse(html, status_code=400)

        # 登录参考 Flask 成品中的旧 SHA-256 账户时，自动升级为 PBKDF2。
        if re.fullmatch(r"[0-9a-fA-F]{64}", row["password_sha256"] or ""):
            conn.execute(
                "UPDATE users SET password_sha256 = ? WHERE id = ?",
                (password_hash(password), row["id"]),
            )
            conn.commit()

    request.session["user_id"] = row["id"]
    return RedirectResponse("/drive", status_code=303)


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if current_user(request):
        return RedirectResponse("/drive", status_code=303)
    return HTMLResponse(
        AUTH_HTML.replace("__MODE__", "register").replace("__ERROR__", "")
    )


@app.post("/register")
def register(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password2: str = Form(...),
):
    username = username.strip()

    if not USERNAME_RE.fullmatch(username):
        error = "用户名需为 3-32 位，只能包含字母、数字、下划线、减号、点"
    elif len(password) < 6:
        error = "密码至少 6 位"
    elif password != password2:
        error = "两次输入的密码不一致"
    else:
        error = ""

    if error:
        html = (
            AUTH_HTML
            .replace("__MODE__", "register")
            .replace("__ERROR__", error)
        )
        return HTMLResponse(html, status_code=400)

    try:
        with open_users_db() as conn:
            cur = conn.execute(
                """
                INSERT INTO users(username, password_sha256, created_at)
                VALUES (?, ?, ?)
                """,
                (username, password_hash(password), current_timestamp()),
            )
            conn.commit()
            user_id = cur.lastrowid
            user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    except sqlite3.IntegrityError:
        html = (
            AUTH_HTML
            .replace("__MODE__", "register")
            .replace("__ERROR__", "用户名已存在")
        )
        return HTMLResponse(html, status_code=409)

    user_files_root(user_id)
    if user_count == 1:
        migrate_legacy_storage_to_first_user(user_id)
    request.session["user_id"] = user_id
    return RedirectResponse("/drive", status_code=303)


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


@app.get("/drive", response_class=HTMLResponse)
def drive_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(
        DRIVE_HTML.replace("__USERNAME__", html_escape(user["username"]))
    )


@app.get("/shares", response_class=HTMLResponse)
def shares_page(request: Request):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return HTMLResponse(
        SHARES_HTML.replace("__USERNAME__", html_escape(user["username"]))
    )


@app.get("/api/me")
def api_me(user=Depends(require_user)):
    return {"ok": True, "user": user}


# -----------------------------------------------------------------------------
# 私有文件 API
# -----------------------------------------------------------------------------
@app.get("/api/list")
def api_list(path: str = "", user=Depends(require_user)):
    _, abs_path = resolve_user_path(user["id"], path)
    if not abs_path.exists() or not abs_path.is_dir():
        raise HTTPException(404, "目录不存在")

    children = sorted(
        abs_path.iterdir(),
        key=lambda p: (p.is_file(), p.name.lower()),
    )

    rels = [path_to_rel(user["id"], child) for child in children]
    shared_map = {}

    if rels:
        placeholders = ",".join("?" for _ in rels)
        with open_shares_db() as conn:
            rows = conn.execute(
                f"""
                SELECT token, rel_path
                FROM shares
                WHERE user_id = ?
                  AND rel_path IN ({placeholders})
                """,
                [user["id"], *rels],
            ).fetchall()
            shared_map = {
                row["rel_path"]: f"/s/{row['token']}"
                for row in rows
            }

    items = []
    for child in children:
        stat = child.stat()
        rel = path_to_rel(user["id"], child)
        items.append({
            "name": child.name,
            "path": rel,
            "type": "folder" if child.is_dir() else "file",
            "size": None if child.is_dir() else stat.st_size,
            "mtime": int(stat.st_mtime),
            "child_count": (
                sum(1 for _ in child.iterdir())
                if child.is_dir()
                else None
            ),
            "preview_type": preview_kind(child),
            "shared": rel in shared_map,
            "share_url": shared_map.get(rel),
        })

    return {
        "ok": True,
        "path": path_to_rel(user["id"], abs_path),
        "items": items,
    }


@app.get("/api/folders/children")
def api_folder_children(
    path: str = "",
    user=Depends(require_user),
):
    _, abs_path = resolve_user_path(user["id"], path)
    if not abs_path.exists() or not abs_path.is_dir():
        raise HTTPException(404, "目录不存在")

    folders = []
    for child in sorted(abs_path.iterdir(), key=lambda p: p.name.lower()):
        if not child.is_dir():
            continue
        try:
            has_children = any(x.is_dir() for x in child.iterdir())
        except OSError:
            has_children = False

        folders.append({
            "path": path_to_rel(user["id"], child),
            "name": child.name,
            "has_children": has_children,
        })

    return {
        "ok": True,
        "path": path_to_rel(user["id"], abs_path),
        "folders": folders,
    }


@app.post("/api/upload")
async def api_upload(
    path: str = Form(""),
    files: list[UploadFile] = File(...),
    relative_paths: str = Form("[]"),
    user=Depends(require_user),
):
    _, target_dir = resolve_user_path(user["id"], path)
    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(404, "目标目录不存在")

    try:
        rels = json.loads(relative_paths) if relative_paths else []
    except json.JSONDecodeError:
        rels = []
    if not isinstance(rels, list):
        rels = []

    saved = []
    skipped = []

    for i, upload in enumerate(files):
        if not upload.filename:
            continue

        try:
            raw_rel = rels[i] if i < len(rels) else ""
            parts = normalize_upload_rel_path(raw_rel)
            if not parts:
                parts = [clean_name(Path(upload.filename).name)]

            dest_dir = target_dir
            for sub in parts[:-1]:
                dest_dir = dest_dir / sub
            dest_dir.mkdir(parents=True, exist_ok=True)

            output = unique_target(dest_dir / parts[-1])
            with output.open("wb") as writer:
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    writer.write(chunk)

            saved.append(path_to_rel(user["id"], output))
        except Exception as exc:
            skipped.append({
                "name": upload.filename,
                "reason": str(exc),
            })
        finally:
            await upload.close()

    return {
        "ok": True,
        "saved": saved,
        "skipped": skipped,
        "count": len(saved),
    }


@app.post("/api/folder")
def api_create_folder(
    body: MkdirBody,
    user=Depends(require_user),
):
    _, parent = resolve_user_path(user["id"], body.path)
    if not parent.exists() or not parent.is_dir():
        raise HTTPException(404, "父目录不存在")

    target = unique_target(parent / clean_name(body.name))
    target.mkdir()

    return {
        "ok": True,
        "path": path_to_rel(user["id"], target),
    }


@app.post("/api/rename")
def api_rename(
    body: RenameBody,
    user=Depends(require_user),
):
    old_rel, src = resolve_user_path(user["id"], body.path)
    root = user_files_root(user["id"])

    if src == root or not src.exists():
        raise HTTPException(404, "目标不存在")

    target = src.with_name(clean_name(body.new_name))
    if target.exists():
        raise HTTPException(409, "同名目标已存在")

    src.rename(target)
    new_rel = path_to_rel(user["id"], target)
    update_share_paths(user["id"], old_rel, new_rel)

    return {
        "ok": True,
        "old_path": old_rel,
        "new_path": new_rel,
    }


@app.post("/api/move")
def api_move(
    body: MoveBody,
    user=Depends(require_user),
):
    sources = resolve_many(user["id"], body.paths)
    dst_rel, dst = resolve_user_path(user["id"], body.dst_dir)

    if not dst.exists() or not dst.is_dir():
        raise HTTPException(404, "目标目录不存在")

    moved = []
    skipped = []

    for src in sources:
        src_rel = path_to_rel(user["id"], src)

        if dst == src.parent:
            skipped.append({
                "path": src_rel,
                "reason": "源和目标目录相同",
            })
            continue

        if src.is_dir() and (dst == src or src in dst.parents):
            skipped.append({
                "path": src_rel,
                "reason": "不能移动到自身或子目录",
            })
            continue

        target = unique_target(dst / src.name)
        shutil.move(str(src), str(target))
        new_rel = path_to_rel(user["id"], target)

        moved.append({
            "from": src_rel,
            "to": new_rel,
        })
        update_share_paths(user["id"], src_rel, new_rel)

    return {
        "ok": True,
        "dst_dir": dst_rel,
        "moved": moved,
        "skipped": skipped,
    }


@app.post("/api/delete")
def api_delete(
    body: PathsBody,
    user=Depends(require_user),
):
    paths = resolve_many(user["id"], body.paths)
    deleted = []

    with open_shares_db() as conn:
        for path in sorted(
            paths,
            key=lambda item: len(item.parts),
            reverse=True,
        ):
            rel = path_to_rel(user["id"], path)

            conn.execute(
                """
                DELETE FROM shares
                WHERE user_id = ?
                  AND (rel_path = ? OR rel_path LIKE ?)
                """,
                (user["id"], rel, rel + "/%"),
            )

            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

            deleted.append(rel)

        conn.commit()

    return {
        "ok": True,
        "deleted": deleted,
    }


@app.get("/api/text")
def api_text_read(
    path: str,
    user=Depends(require_user),
):
    rel, abs_path = resolve_user_path(user["id"], path)

    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(404, "文件不存在")
    if preview_kind(abs_path) != "text":
        raise HTTPException(400, "该文件不是支持的文本类型")

    content, encoding = read_preview_text(abs_path)

    return {
        "ok": True,
        "path": rel,
        "name": abs_path.name,
        "content": content,
        "encoding": encoding,
    }


@app.post("/api/text")
def api_text_save(
    body: TextSaveBody,
    user=Depends(require_user),
):
    rel, abs_path = resolve_user_path(user["id"], body.path)

    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(404, "文件不存在")
    if preview_kind(abs_path) != "text":
        raise HTTPException(400, "该文件不是支持的文本类型")
    if len(body.content.encode("utf-8")) > MAX_TEXT_FILE_SIZE:
        raise HTTPException(400, "文本内容超过 5MB")

    payload, encoding, converted = encode_preview_text(
        body.content,
        body.encoding,
    )
    abs_path.write_bytes(payload)

    return {
        "ok": True,
        "path": rel,
        "encoding": encoding,
        "converted_to_utf8": converted,
    }


@app.get("/api/media")
def api_media(
    path: str,
    user=Depends(require_user),
):
    _, abs_path = resolve_user_path(user["id"], path)

    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(404, "文件不存在")
    if preview_kind(abs_path) not in {"image", "video", "audio", "pdf"}:
        raise HTTPException(400, "不支持在线预览")

    return FileResponse(
        abs_path,
        filename=abs_path.name,
        content_disposition_type="inline",
    )


@app.get("/api/download")
def api_download(
    background_tasks: BackgroundTasks,
    path: str,
    user=Depends(require_user),
):
    _, abs_path = resolve_user_path(user["id"], path)

    if (
        not abs_path.exists()
        or abs_path == user_files_root(user["id"])
    ):
        raise HTTPException(404, "对象不存在")

    if abs_path.is_file():
        return FileResponse(abs_path, filename=abs_path.name)

    return create_7z(
        [abs_path],
        abs_path.name + ".7z",
        background_tasks,
    )


@app.post("/api/download/batch")
def api_download_batch(
    body: PathsBody,
    background_tasks: BackgroundTasks,
    user=Depends(require_user),
):
    paths = resolve_many(user["id"], body.paths)

    if len(paths) == 1 and paths[0].is_file():
        return FileResponse(paths[0], filename=paths[0].name)

    return create_7z(
        paths,
        datetime.now().strftime("%Y%m%d_%H%M%S") + ".7z",
        background_tasks,
    )


# -----------------------------------------------------------------------------
# 在线文本与媒体查看页面
# -----------------------------------------------------------------------------
def render_text_page(
    file_path: str,
    file_name: str,
    load_url: str,
    *,
    read_only: bool,
) -> HTMLResponse:
    """私有编辑和公开分享查看共用完全相同的页面模板。"""
    html = (
        EDITOR_HTML
        .replace("__FILE_PATH__", json.dumps(file_path, ensure_ascii=False))
        .replace("__FILE_NAME__", html_escape(file_name))
        .replace("__LOAD_URL__", json.dumps(load_url, ensure_ascii=False))
        .replace("__SAVE_URL__", json.dumps("/api/text" if not read_only else ""))
        .replace("__READ_ONLY__", "true" if read_only else "false")
    )
    return HTMLResponse(html)


@app.get("/editor", response_class=HTMLResponse)
def editor_page(
    path: str,
    request: Request,
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    rel, abs_path = resolve_user_path(user["id"], path)

    if (
        not abs_path.exists()
        or not abs_path.is_file()
        or preview_kind(abs_path) != "text"
    ):
        raise HTTPException(404, "文件不存在或不支持编辑")

    return render_text_page(
        rel,
        abs_path.name,
        f"/api/text?path={quote(rel, safe='')}",
        read_only=False,
    )



def render_media_page(
    file_name: str,
    media_kind: str,
    media_url: str,
    download_url: str,
) -> HTMLResponse:
    """私有媒体和公开分享媒体共用同一个新窗口预览页面。"""
    labels = {
        "image": "图片",
        "video": "视频",
        "audio": "音频",
        "pdf": "PDF",
    }

    if media_kind == "image":
        media_body = (
            f'<img class="preview-image" src="{html_escape(media_url)}" '
            f'alt="{html_escape(file_name)}">'
        )
    elif media_kind == "video":
        media_body = (
            f'<video class="preview-video" controls preload="metadata" '
            f'src="{html_escape(media_url)}"></video>'
        )
    elif media_kind == "audio":
        media_body = (
            '<div class="audio-player-panel">'
            f'<audio class="preview-audio" controls preload="metadata" '
            f'src="{html_escape(media_url)}"></audio>'
            '</div>'
        )
    elif media_kind == "pdf":
        media_body = (
            f'<iframe class="preview-pdf" src="{html_escape(media_url)}"></iframe>'
        )
    else:
        raise HTTPException(400, "不支持该媒体预览类型")

    html = (
        MEDIA_VIEW_HTML
        .replace("__FILE_NAME__", html_escape(file_name))
        .replace("__MEDIA_LABEL__", labels[media_kind])
        .replace("__MEDIA_BODY__", media_body)
        .replace(
            "__BODY_CLASS__",
            "image-mode" if media_kind == "image"
            else "video-mode" if media_kind == "video"
            else "pdf-mode" if media_kind == "pdf"
            else "",
        )
        .replace("__DOWNLOAD_URL__", json.dumps(download_url, ensure_ascii=False))
        .replace("__MEDIA_KIND__", json.dumps(media_kind, ensure_ascii=False))
    )
    return HTMLResponse(html)


@app.get("/viewer", response_class=HTMLResponse)
def media_viewer_page(
    path: str,
    request: Request,
):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)

    rel, abs_path = resolve_user_path(user["id"], path)

    if not abs_path.exists() or not abs_path.is_file():
        raise HTTPException(404, "文件不存在")

    kind = preview_kind(abs_path)
    if kind not in {"image", "video", "audio", "pdf"}:
        raise HTTPException(400, "该文件不支持媒体新窗口预览")

    encoded = quote(rel, safe="")
    return render_media_page(
        abs_path.name,
        kind,
        f"/api/media?path={encoded}",
        f"/api/download?path={encoded}",
    )


# -----------------------------------------------------------------------------
# 私有分享管理 API
# -----------------------------------------------------------------------------
@app.post("/api/share/create")
def api_share_create(
    body: ShareCreateBody,
    user=Depends(require_user),
):
    rel, abs_path = resolve_user_path(user["id"], body.path)

    if not abs_path.exists() or abs_path == user_files_root(user["id"]):
        raise HTTPException(404, "对象不存在")

    with open_shares_db() as conn:
        row = conn.execute(
            """
            SELECT id, token
            FROM shares
            WHERE user_id = ? AND rel_path = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user["id"], rel),
        ).fetchone()

        if row:
            share_id = row["id"]
            token = row["token"]
        else:
            token = secrets.token_urlsafe(18)
            cur = conn.execute(
                """
                INSERT INTO shares(token, user_id, rel_path, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (token, user["id"], rel, current_timestamp()),
            )
            conn.commit()
            share_id = cur.lastrowid

    return {
        "ok": True,
        "share_id": share_id,
        "path": rel,
        "share_url": f"/s/{token}",
    }


@app.get("/api/share/list")
def api_share_list(user=Depends(require_user)):
    with open_shares_db() as conn:
        rows = conn.execute(
            """
            SELECT id, token, rel_path, created_at
            FROM shares
            WHERE user_id = ?
            ORDER BY id DESC
            """,
            (user["id"],),
        ).fetchall()

    shares = []
    for row in rows:
        _, abs_path = resolve_user_path(user["id"], row["rel_path"])
        exists = abs_path.exists()
        shares.append({
            "id": row["id"],
            "token": row["token"],
            "rel_path": row["rel_path"],
            # 展示信息实时从文件系统计算，不写数据库。
            "item_type": ("folder" if abs_path.is_dir() else "file") if exists else "missing",
            "share_name": abs_path.name if exists else (Path(row["rel_path"]).name or row["rel_path"]),
            "created_at": row["created_at"],
            "exists": exists,
            "share_url": f"/s/{row['token']}",
        })

    return {"ok": True, "shares": shares}


@app.post("/api/share/cancel")
def api_share_cancel(
    body: ShareCancelBody,
    user=Depends(require_user),
):
    with open_shares_db() as conn:
        cur = conn.execute(
            "DELETE FROM shares WHERE id = ? AND user_id = ?",
            (body.share_id, user["id"]),
        )
        conn.commit()

    if cur.rowcount == 0:
        raise HTTPException(404, "分享记录不存在")

    return {"ok": True}


# -----------------------------------------------------------------------------
# 公开分享页面与公开下载 API
# -----------------------------------------------------------------------------
@app.get("/s/{token}", response_class=HTMLResponse)
def share_page(token: str):
    share = get_share(token)
    if not share:
        raise HTTPException(404, "分享不存在或已失效")

    shared_root, _, _ = resolve_public_share_target(share, "")
    html = (
        PUBLIC_SHARE_HTML
        .replace("__TOKEN__", json.dumps(token))
        .replace("__SHARE_NAME__", html_escape(shared_root.name))
    )
    return HTMLResponse(html)


@app.get("/s/{token}/api/list")
def share_list(
    token: str,
    subpath: str = "",
):
    share = get_share(token)
    if not share:
        raise HTTPException(404, "分享不存在或已失效")

    shared_root, target, subpath = resolve_public_share_target(
        share,
        subpath,
    )

    if target.is_file():
        stat = target.stat()

        return {
            "ok": True,
            "item_type": "file",
            "share_name": shared_root.name,
            "subpath": subpath,
            "items": [],
            "current": {
                "name": target.name,
                "path": subpath,
                "type": "file",
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
                "preview_type": preview_kind(target),
            },
        }

    items = []

    for path in sorted(
        target.iterdir(),
        key=lambda p: (p.is_file(), p.name.lower()),
    ):
        stat = path.stat()

        items.append({
            "name": path.name,
            "path": path.relative_to(shared_root).as_posix(),
            "type": "folder" if path.is_dir() else "file",
            "size": None if path.is_dir() else stat.st_size,
            "mtime": int(stat.st_mtime),
            "preview_type": preview_kind(path),
        })

    return {
        "ok": True,
        "item_type": "folder",
        "share_name": shared_root.name,
        "subpath": subpath,
        "items": items,
    }


@app.get("/s/{token}/view", response_class=HTMLResponse)
def share_text_page(
    token: str,
    subpath: str = "",
):
    share = get_share(token)
    if not share:
        raise HTTPException(404, "分享不存在或已失效")

    _, abs_path, subpath = resolve_public_share_target(
        share,
        subpath,
    )

    if (
        not abs_path.is_file()
        or preview_kind(abs_path) != "text"
    ):
        raise HTTPException(404, "文件不存在或不支持文本查看")

    return render_text_page(
        subpath,
        abs_path.name,
        f"/s/{token}/api/text?subpath={quote(subpath, safe='')}",
        read_only=True,
    )


@app.get("/s/{token}/api/text")
def share_text(
    token: str,
    subpath: str = "",
):
    share = get_share(token)
    if not share:
        raise HTTPException(404, "分享不存在或已失效")

    _, abs_path, subpath = resolve_public_share_target(
        share,
        subpath,
    )

    if (
        not abs_path.is_file()
        or preview_kind(abs_path) != "text"
    ):
        raise HTTPException(400, "该文件不是支持的文本类型")

    content, encoding = read_preview_text(abs_path)

    return {
        "ok": True,
        "subpath": subpath,
        "name": abs_path.name,
        "content": content,
        "encoding": encoding,
    }



@app.get("/s/{token}/viewer", response_class=HTMLResponse)
def share_media_viewer_page(
    token: str,
    subpath: str = "",
):
    share = get_share(token)
    if not share:
        raise HTTPException(404, "分享不存在或已失效")

    _, abs_path, normalized_subpath = resolve_public_share_target(
        share,
        subpath,
    )

    if not abs_path.is_file():
        raise HTTPException(404, "文件不存在")

    kind = preview_kind(abs_path)
    if kind not in {"image", "video", "audio", "pdf"}:
        raise HTTPException(400, "该文件不支持媒体新窗口预览")

    encoded = quote(normalized_subpath, safe="")
    return render_media_page(
        abs_path.name,
        kind,
        f"/s/{token}/media?subpath={encoded}",
        f"/s/{token}/download?subpath={encoded}",
    )


@app.get("/s/{token}/media")
def share_media(
    token: str,
    subpath: str = "",
):
    share = get_share(token)
    if not share:
        raise HTTPException(404, "分享不存在或已失效")

    _, abs_path, _ = resolve_public_share_target(
        share,
        subpath,
    )

    if (
        not abs_path.is_file()
        or preview_kind(abs_path)
        not in {"image", "video", "audio", "pdf"}
    ):
        raise HTTPException(404, "不支持预览")

    return FileResponse(
        abs_path,
        filename=abs_path.name,
        content_disposition_type="inline",
    )


@app.get("/s/{token}/download")
def share_download(
    token: str,
    background_tasks: BackgroundTasks,
    subpath: str = "",
):
    share = get_share(token)
    if not share:
        raise HTTPException(404, "分享不存在或已失效")

    _, abs_path, _ = resolve_public_share_target(
        share,
        subpath,
    )


    if abs_path.is_file():
        return FileResponse(abs_path, filename=abs_path.name)

    return create_7z(
        [abs_path],
        abs_path.name + ".7z",
        background_tasks,
    )


@app.post("/s/{token}/download/batch")
def share_download_batch(
    token: str,
    body: PathsBody,
    background_tasks: BackgroundTasks,
):
    share = get_share(token)
    if not share:
        raise HTTPException(404, "分享不存在或已失效")

    paths = resolve_public_many(share, body.paths)


    if len(paths) == 1 and paths[0].is_file():
        return FileResponse(paths[0], filename=paths[0].name)

    return create_7z(
        paths,
        datetime.now().strftime("%Y%m%d_%H%M%S") + ".7z",
        background_tasks,
    )

# -----------------------------------------------------------------------------
# 登录 / 注册页面
# -----------------------------------------------------------------------------
AUTH_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FastAPI Drive</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;height:100%;font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#fff7f2;color:#3b261e}
.auth-page{min-height:100%;display:grid;place-items:center;padding:3vh 3vw}
.auth-panel{width:min(96vw,980px);min-height:min(92vh,720px);background:#fff;border:1px solid #f0c5aa;border-radius:18px;padding:clamp(28px,5vw,64px);box-shadow:0 18px 50px rgba(120,45,0,.10);display:flex;flex-direction:column;justify-content:center;align-items:center}
h1{width:min(100%,520px);font-size:clamp(26px,3vw,36px);margin:0 0 28px;color:#A63E00}
label{display:block;font-size:14px;color:#8a5a42;margin:14px 0 7px}
input{width:100%;height:50px;border:1px solid #e5b596;border-radius:10px;padding:0 14px;font-size:15px;outline:none;background:#fffdfb}
input:focus{border-color:#F05A00;box-shadow:0 0 0 3px rgba(240,90,0,.12)}
.auth-submit-button{width:100%;height:50px;border:0;border-radius:10px;background:#F05A00;color:#fff;margin-top:22px;cursor:pointer;font-size:16px;font-weight:700}
.auth-switch{width:min(100%,520px);text-align:center;font-size:14px;color:#8a5a42;margin-top:18px}
.auth-switch a{color:#C84600;font-weight:700}
.auth-error{width:min(100%,520px);background:rgba(240,90,0,.08);color:#A63E00;border:1px solid #F05A00;border-radius:8px;padding:10px 12px;font-size:13px;margin-bottom:12px}
button:focus-visible,input:focus-visible,.item:focus-visible{outline:2px solid #F05A00;outline-offset:2px}
</style>
</head>
<body>
<div class="auth-page">
  <div class="auth-panel">
    <h1 id="authTitle"></h1>
    <div id="authError" class="auth-error">__ERROR__</div>
    <form id="authForm" method="post" style="width:min(100%,520px)">
      <label>用户名</label>
      <input name="username" required autocomplete="username">
      <label>密码</label>
      <input name="password" type="password" required autocomplete="current-password">
      <div id="passwordConfirmGroup">
        <label>确认密码</label>
        <input name="password2" type="password" autocomplete="new-password">
      </div>
      <button class="auth-submit-button" id="authSubmitButton"></button>
    </form>
    <div class="auth-switch" id="authSwitch"></div>
  </div>
</div>
<script>
const mode = "__MODE__";
const isRegister = mode === "register";

document.getElementById("authTitle").textContent = isRegister
  ? "注册 FastAPI Drive"
  : "登录 FastAPI Drive";
document.getElementById("authSubmitButton").textContent = isRegister
  ? "注册并进入"
  : "登录";
document.getElementById("passwordConfirmGroup").style.display = isRegister
  ? "block"
  : "none";
document.getElementById("authForm").action = isRegister
  ? "/register"
  : "/login";
document.getElementById("authSwitch").innerHTML = isRegister
  ? '已有账户？ <a href="/login">登录</a>'
  : '没有账户？ <a href="/register">注册</a>';

if (!document.getElementById("authError").textContent.trim()) {
  document.getElementById("authError").style.display = "none";
}
</script>
</body>
</html>"""
# -----------------------------------------------------------------------------
# 主文件管理页面
# -----------------------------------------------------------------------------
DRIVE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FastAPI Drive</title>
<style>
*{box-sizing:border-box}
:root{--bg:#fff8f3;--line:#efd5c5;--text:#3b261e;--muted:#8a6552;--sel:rgba(240,90,0,.10);--selb:#F05A00;--danger:#B32600}
html,body{margin:0;height:100%;font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text)}
body{display:flex;flex-direction:column;overflow:hidden}
header{height:44px;min-height:44px;background:#fffaf7;border-bottom:1px solid var(--line);display:flex;align-items:center;padding:0 10px;gap:4px;overflow:auto;white-space:nowrap}
.breadcrumb-button{border:0;background:transparent;padding:5px 6px;border-radius:6px;cursor:pointer;color:#5a3524;font-size:13px}
.breadcrumb-button:hover,.breadcrumb-button.drop-over{background:rgba(240,90,0,.09)}
.breadcrumb-separator{color:#aaa}
#driveBreadcrumbs{display:flex;align-items:center;gap:4px;min-width:0;flex:1;overflow:auto}
.account-toolbar{margin-left:auto;font-size:11px;color:#777;white-space:nowrap}
.account-toolbar a{color:#444;text-decoration:none}
.account-toolbar a:hover{text-decoration:underline}
#fileWorkspace{position:relative;flex:1;overflow:auto;padding:8px}
#fileGrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(86px,104px));gap:7px;align-content:start;justify-content:start;min-height:100%}
.file-card{position:relative;aspect-ratio:1/1;background:#fff;border:1px solid #ead3c5;border-radius:7px;padding:6px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;user-select:none;cursor:default}
.file-card:hover{border-color:#F05A00;box-shadow:0 1px 3px rgba(240,90,0,.16)}
.file-card.selected{background:var(--sel);border-color:var(--selb);box-shadow:0 0 0 1px var(--selb) inset}
.file-card.dragging{opacity:.55}
.file-card.drop-over,#fileWorkspace.external-over{outline:2px dashed #F05A00;outline-offset:-3px}
.file-icon{font-size:22px;line-height:1;margin-bottom:5px}
.file-name{width:100%;min-height:27px;font-size:11px;font-weight:550;line-height:1.22;text-align:center;white-space:normal;overflow:hidden;word-break:break-all;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2}
.file-meta{width:100%;font-size:9px;color:var(--muted);margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.share-badge{position:absolute;right:4px;top:4px;background:rgba(240,90,0,.10);color:#A63E00;border-radius:999px;padding:1px 4px;font-size:8px}
.file-empty-state{grid-column:1/-1;min-height:60vh;display:grid;place-items:center;color:#999;font-size:12px}
#selectionMarquee{position:fixed;display:none;z-index:800;pointer-events:none;border:1px solid #F05A00;background:rgba(240,90,0,.14)}
#contextMenu{position:fixed;display:none;z-index:1100;min-width:180px;background:#fff;border:1px solid #d7d7d7;border-radius:8px;padding:5px;box-shadow:0 10px 26px #0002}
.context-menu-item{padding:8px 10px;border-radius:6px;font-size:13px;cursor:pointer}
.context-menu-item:hover{background:rgba(240,90,0,.08)}
.context-menu-item.danger{color:var(--danger)}
.context-menu-separator{height:1px;background:#eee;margin:4px}
#toastMessage{position:fixed;left:50%;bottom:15px;transform:translateX(-50%);background:#222;color:#fff;padding:8px 12px;border-radius:7px;font-size:12px;display:none;z-index:2000}
#busyIndicator{position:fixed;right:10px;bottom:10px;background:#fff;border:1px solid #ddd;border-radius:999px;padding:5px 9px;font-size:11px;display:none;z-index:1200}
#selectionIndicator{position:fixed;left:10px;bottom:10px;background:#fff;border:1px solid #ddd;border-radius:999px;padding:5px 9px;font-size:11px;color:#555;display:none;z-index:700}
.dialog-overlay{position:fixed;inset:0;background:#0005;display:none;align-items:center;justify-content:center;padding:14px;z-index:1300}
.dialog-overlay.show{display:flex}
.dialog-panel{width:min(94vw,640px);max-height:88vh;background:#fff;border-radius:10px;border:1px solid #ddd;box-shadow:0 20px 60px #0004;display:flex;flex-direction:column;overflow:hidden}
.dialog-panel.wide{width:min(96vw,1050px)}
.dialog-header{height:42px;min-height:42px;display:flex;align-items:center;justify-content:space-between;padding:0 12px;border-bottom:1px solid #eee}
.dialog-title{font-size:14px;font-weight:700;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dialog-close-button{border:0;background:transparent;font-size:20px;cursor:pointer}
.dialog-body{padding:10px;overflow:auto;min-height:0}
.dialog-footer{padding:8px 10px;border-top:1px solid #eee;display:flex;justify-content:flex-end;gap:7px}
.dialog-button{border:1px solid #ccc;background:#fff;padding:6px 10px;border-radius:7px;cursor:pointer;font-size:12px}
.dialog-button.primary{background:#F05A00;color:#fff;border-color:#F05A00}
.media-player{width:100%;max-height:74vh;background:#000}
.audio-player{width:100%}
.image-viewer{display:block;max-width:100%;max-height:75vh;margin:auto;object-fit:contain}
.pdf-viewer{width:100%;height:74vh;border:0}
.folder-tree{border:1px solid #ddd;border-radius:7px;min-height:320px;max-height:60vh;overflow:auto;padding:4px}
.folder-tree-row{height:30px;display:flex;align-items:center;gap:5px;padding:0 6px;border-radius:5px;cursor:pointer;font-size:13px}
.folder-tree-row:hover{background:rgba(240,90,0,.07)}
.folder-tree-row.selected{background:rgba(240,90,0,.11);color:#A63E00}
.folder-tree-toggle{width:18px;text-align:center;color:#777}
.folder-tree-children{margin-left:16px;display:none}
.folder-tree-children.open{display:block}
input[type=file]{display:none}
@media(max-width:520px){#fileGrid{grid-template-columns:repeat(auto-fill,minmax(78px,1fr));gap:6px}.file-icon{font-size:20px}}
button:focus-visible,input:focus-visible,.file-card:focus-visible{outline:2px solid #F05A00;outline-offset:2px}
</style>
</head>
<body>
<header>
  <div id="driveBreadcrumbs"></div>
  <div class="account-toolbar">__USERNAME__ · <a href="/logout">退出</a></div>
</header>
<main id="fileWorkspace">
  <div id="fileGrid"></div>
</main>
<div id="selectionMarquee"></div>
<div id="contextMenu"></div>
<div id="toastMessage"></div>
<div id="busyIndicator">处理中…</div>
<div id="selectionIndicator"></div>
<div id="dialogOverlay" class="dialog-overlay"></div>
<input id="fileUploadInput" type="file" multiple>
<input id="folderUploadInput" type="file" webkitdirectory directory multiple>

<script>
// -----------------------------------------------------------------------------
// DOM 与页面状态
// -----------------------------------------------------------------------------
const query = selector => document.querySelector(selector);
const fileGrid = query("#fileGrid");
const fileWorkspace = query("#fileWorkspace");
const contextMenu = query("#contextMenu");
const selectionMarquee = query("#selectionMarquee");
const fileUploadInput = query("#fileUploadInput");
const folderUploadInput = query("#folderUploadInput");
const dialogOverlay = query("#dialogOverlay");
const selectionIndicator = query("#selectionIndicator");

const state = {
  path: "",
  items: [],
  selected: new Set(),
  anchor: null,
  draggingPaths: [],
  marquee: null,
  suppressClickUntil: 0,
};

// -----------------------------------------------------------------------------
// 通用工具
// -----------------------------------------------------------------------------
function showToast(message) {
  const toastBox = query("#toastMessage");
  toastBox.textContent = message;
  toastBox.style.display = "block";
  clearTimeout(window.__tt);
  window.__tt = setTimeout(() => {
    toastBox.style.display = "none";
  }, 2200);
}

function setBusy(visible) {
  query("#busyIndicator").style.display = visible ? "block" : "none";
}

function formatFileSize(size) {
  if (size == null) return "";

  const units = ["B", "KB", "MB", "GB", "TB"];
  let unitIndex = 0;

  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }

  return `${size.toFixed(unitIndex ? 1 : 0)} ${units[unitIndex]}`;
}

async function requestApi(url, options = {}) {
  setBusy(true);

  try {
    const response = await fetch(url, options);
    const contentType = response.headers.get("content-type") || "";
    let data = null;

    if (contentType.includes("json")) {
      data = await response.json();
    }

    if (!response.ok) {
      throw new Error((data && data.detail) || `HTTP ${response.status}`);
    }

    return data || response;
  } finally {
    setBusy(false);
  }
}

async function postJson(url, payload) {
  return requestApi(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function getItemIcon(item) {
  if (item.type === "folder") return "📁";
  if (item.preview_type === "text") return "📝";
  if (item.preview_type === "image") return "🖼️";
  if (item.preview_type === "video") return "🎬";
  if (item.preview_type === "audio") return "🎵";
  if (item.preview_type === "pdf") return "📕";
  return "📄";
}

function getSelectedPaths() {
  return [...state.selected];
}

// -----------------------------------------------------------------------------
// 选择状态
// -----------------------------------------------------------------------------
function refreshSelection() {
  document.querySelectorAll(".file-card").forEach(element => {
    element.classList.toggle(
      "selected",
      state.selected.has(element.dataset.path),
    );
  });

  selectionIndicator.textContent = `已选择 ${state.selected.size} 项`;
  selectionIndicator.style.display = state.selected.size ? "block" : "none";
}

function clearSelection() {
  state.selected.clear();
  state.anchor = null;
  refreshSelection();
}

function selectOnly(path) {
  state.selected = new Set([path]);
  state.anchor = path;
  refreshSelection();
}

function toggleSelection(path) {
  if (state.selected.has(path)) {
    state.selected.delete(path);
  } else {
    state.selected.add(path);
  }

  state.anchor = path;
  refreshSelection();
}

function selectRange(path, additive = false) {
  const itemPaths = state.items.map(item => item.path);
  const anchorIndex = itemPaths.indexOf(state.anchor);
  const targetIndex = itemPaths.indexOf(path);

  if (anchorIndex < 0 || targetIndex < 0) {
    selectOnly(path);
    return;
  }

  const nextSelection = additive
    ? new Set(state.selected)
    : new Set();

  for (
    let index = Math.min(anchorIndex, targetIndex);
    index <= Math.max(anchorIndex, targetIndex);
    index += 1
  ) {
    nextSelection.add(itemPaths[index]);
  }

  state.selected = nextSelection;
  refreshSelection();
}

// -----------------------------------------------------------------------------
// 文件列表与面包屑
// -----------------------------------------------------------------------------
async function loadFileList(path = state.path) {
  try {
    const data = await requestApi(
      "/api/list?path=" + encodeURIComponent(path),
    );

    state.path = data.path;
    state.items = data.items;
    state.selected.clear();
    state.anchor = null;

    renderBreadcrumbs();
    renderFileGrid();
  } catch (error) {
    showToast(error.message);
  }
}

function renderBreadcrumbs() {
  const breadcrumbs = query("#driveBreadcrumbs");
  breadcrumbs.innerHTML = "";

  const crumbs = [{label: "根目录", path: ""}];
  let accumulatedPath = "";

  state.path
    .split("/")
    .filter(Boolean)
    .forEach(part => {
      accumulatedPath = accumulatedPath
        ? accumulatedPath + "/" + part
        : part;
      crumbs.push({label: part, path: accumulatedPath});
    });

  crumbs.forEach((crumb, index) => {
    const button = document.createElement("button");
    button.className = "breadcrumb-button";
    button.textContent = crumb.label;
    button.onclick = () => loadFileList(crumb.path);
    attachDropTarget(button, crumb.path);
    breadcrumbs.appendChild(button);

    if (index < crumbs.length - 1) {
      const separator = document.createElement("span");
      separator.className = "breadcrumb-separator";
      separator.textContent = "/";
      breadcrumbs.appendChild(separator);
    }
  });
}

function renderFileGrid() {
  fileGrid.innerHTML = "";

  if (!state.items.length) {
    const empty = document.createElement("div");
    empty.className = "file-empty-state";
    empty.textContent =
      "空目录 · 右键上传/新建 · 可拖入文件或文件夹 · 空白处拖框多选";
    fileGrid.appendChild(empty);
    refreshSelection();
    return;
  }

  state.items.forEach(item => {
    const card = document.createElement("div");
    card.className = "file-card";
    card.dataset.path = item.path;
    card.draggable = true;

    card.innerHTML = `
      ${item.shared ? '<span class="share-badge">分享</span>' : ''}
      <div class="file-icon">${getItemIcon(item)}</div>
      <div class="file-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
      <div class="file-meta">
        ${item.type === "folder" ? (item.child_count ?? 0) + " 项" : formatFileSize(item.size)}
      </div>
    `;

    card.onclick = event => {
      if (Date.now() < state.suppressClickUntil) return;

      // Shift / Ctrl / Command 只用于多选；普通左键：文件夹进入，文件直接下载。
      if (event.shiftKey) {
        selectRange(item.path, event.ctrlKey || event.metaKey);
        return;
      }

      if (event.ctrlKey || event.metaKey) {
        toggleSelection(item.path);
        return;
      }

      clearSelection();
      if (item.type === "folder") {
        loadFileList(item.path);
      } else {
        downloadFile(item);
      }
    };

    card.oncontextmenu = event => {
      event.preventDefault();
      event.stopPropagation();

      if (!state.selected.has(item.path)) {
        selectOnly(item.path);
      }

      showContextMenu(event.clientX, event.clientY, item);
    };

    card.ondragstart = event => {
      if (!state.selected.has(item.path)) {
        selectOnly(item.path);
      }

      state.draggingPaths = getSelectedPaths();
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", "internal");
      card.classList.add("dragging");
    };

    card.ondragend = () => {
      state.draggingPaths = [];
      state.suppressClickUntil = Date.now() + 250;
      card.classList.remove("dragging");
      document.querySelectorAll(".drop-over").forEach(element => {
        element.classList.remove("drop-over");
      });
    };

    if (item.type === "folder") {
      attachDropTarget(card, item.path);
    }

    fileGrid.appendChild(card);
  });

  refreshSelection();
}

// -----------------------------------------------------------------------------
// 打开、下载、弹窗
// -----------------------------------------------------------------------------
function downloadFile(item) {
  location.href = "/api/download?path=" + encodeURIComponent(item.path);
}

function openFile(item) {
  const encodedPath = encodeURIComponent(item.path);

  if (item.preview_type === "text") {
    window.open(`/editor?path=${encodedPath}`, "_blank", "noopener");
    return;
  }

  if (["image", "video", "audio", "pdf"].includes(item.preview_type)) {
    window.open(`/viewer?path=${encodedPath}`, "_blank", "noopener");
    return;
  }

  location.href = "/api/download?path=" + encodedPath;
}

function openModal(title, body, wide = false, buttons = []) {
  dialogOverlay.innerHTML = `
    <div class="dialog-panel ${wide ? "wide" : ""}">
      <div class="dialog-header">
        <div class="dialog-title">${escapeHtml(title)}</div>
        <button class="dialog-close-button">×</button>
      </div>
      <div class="dialog-body">${body}</div>
      <div class="dialog-footer"></div>
    </div>
  `;

  dialogOverlay.classList.add("show");
  dialogOverlay.querySelector(".dialog-close-button").onclick = closeModal;

  const footer = dialogOverlay.querySelector(".dialog-footer");
  const modalButtons = buttons.length
    ? buttons
    : [{text: "关闭", fn: closeModal}];

  modalButtons.forEach(buttonConfig => {
    const button = document.createElement("button");
    button.className = "dialog-button " + (buttonConfig.primary ? "primary" : "");
    button.textContent = buttonConfig.text;
    button.onclick = buttonConfig.fn;
    footer.appendChild(button);
  });
}

function closeModal() {
  dialogOverlay.classList.remove("show");
  dialogOverlay.innerHTML = "";
}

dialogOverlay.onclick = event => {
  if (event.target === dialogOverlay) {
    closeModal();
  }
};

// -----------------------------------------------------------------------------
// 右键菜单
// -----------------------------------------------------------------------------
function addMenuItem(text, handler, danger = false) {
  const item = document.createElement("div");
  item.className = "context-menu-item" + (danger ? " danger" : "");
  item.textContent = text;
  item.onclick = () => {
    contextMenu.style.display = "none";
    handler();
  };
  contextMenu.appendChild(item);
}

function addMenuSeparator() {
  const separator = document.createElement("div");
  separator.className = "context-menu-separator";
  contextMenu.appendChild(separator);
}

function showContextMenu(x, y, item = null) {
  contextMenu.innerHTML = "";
  const selectedPaths = getSelectedPaths();

  if (!item) {
    addMenuItem("新建文件夹", createFolder);
    addMenuItem("上传文件", () => {
      fileUploadInput.value = "";
      fileUploadInput.click();
    });
    addMenuItem("上传文件夹", () => {
      folderUploadInput.value = "";
      folderUploadInput.click();
    });
    addMenuItem("刷新", () => loadFileList());

    if (selectedPaths.length) {
      addMenuSeparator();
      addMenuItem(
        `下载所选 (${selectedPaths.length})`,
        () => downloadTargets(selectedPaths),
      );
      addMenuItem(
        `移动所选 (${selectedPaths.length})`,
        () => openMoveDialog(selectedPaths),
      );
      if (selectedPaths.length === 1) {
        addMenuItem("分享所选", () => createShareLink(selectedPaths[0]));
      }
      addMenuItem(
        `删除所选 (${selectedPaths.length})`,
        () => deleteItems(selectedPaths),
        true,
      );
      addMenuItem("取消选择", clearSelection);
    }

    addMenuSeparator();
    addMenuItem("分享管理", openShareManager);
    addMenuItem("退出登录", () => location.href = "/logout");
  } else {
    if (selectedPaths.length === 1) {
      if (item.type === "folder") {
        addMenuItem("打开", () => loadFileList(item.path));
        addMenuSeparator();
      } else if (item.preview_type !== "none") {
        addMenuItem(
          item.preview_type === "text" ? "在线编辑" : "在线预览",
          () => openFile(item),
        );
        addMenuSeparator();
      }
    }

    addMenuItem(
      selectedPaths.length > 1 ? `下载 ${selectedPaths.length} 项` : "下载",
      () => downloadTargets(selectedPaths),
    );
    addMenuItem(
      selectedPaths.length > 1 ? `移动 ${selectedPaths.length} 项到…` : "移动到…",
      () => openMoveDialog(selectedPaths),
    );

    if (selectedPaths.length === 1) {
      addMenuItem("分享", () => createShareLink(selectedPaths[0]));
      addMenuItem("重命名", () => renameItem(item));
    }

    addMenuItem(
      selectedPaths.length > 1 ? `删除 ${selectedPaths.length} 项` : "删除",
      () => deleteItems(selectedPaths),
      true,
    );
  }

  contextMenu.style.display = "block";
  const rect = contextMenu.getBoundingClientRect();
  contextMenu.style.left = Math.max(5, Math.min(x, innerWidth - rect.width - 6)) + "px";
  contextMenu.style.top = Math.max(5, Math.min(y, innerHeight - rect.height - 6)) + "px";
}

fileWorkspace.oncontextmenu = event => {
  if (event.target.closest(".file-card")) return;
  event.preventDefault();
  showContextMenu(event.clientX, event.clientY);
};

document.addEventListener("click", event => {
  if (!event.target.closest("#contextMenu")) {
    contextMenu.style.display = "none";
  }
});

document.addEventListener("keydown", event => {
  if (event.key === "Escape") {
    contextMenu.style.display = "none";
    closeModal();
  }

  if (
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "a" &&
    !event.target.matches("input,textarea")
  ) {
    event.preventDefault();
    state.selected = new Set(state.items.map(item => item.path));
    refreshSelection();
  }

  if (event.key === "Delete" && state.selected.size) {
    event.preventDefault();
    deleteItems(getSelectedPaths());
  }
});

// -----------------------------------------------------------------------------
// 文件操作
// -----------------------------------------------------------------------------
async function createFolder() {
  const name = prompt("新文件夹名称");
  if (!name) return;

  try {
    await postJson("/api/folder", {path: state.path, name});
    await loadFileList();
  } catch (error) {
    showToast(error.message);
  }
}

async function renameItem(item) {
  const newName = prompt("新名称", item.name);
  if (!newName || newName === item.name) return;

  try {
    await postJson("/api/rename", {
      path: item.path,
      new_name: newName,
    });
    await loadFileList();
  } catch (error) {
    showToast(error.message);
  }
}

async function deleteItems(paths) {
  if (
    !paths.length ||
    !confirm(`确认删除 ${paths.length} 项？\n文件夹内容也会一并删除。`)
  ) {
    return;
  }

  try {
    const result = await postJson("/api/delete", {paths});
    showToast(`已删除 ${result.deleted.length} 项`);
    await loadFileList();
  } catch (error) {
    showToast(error.message);
  }
}

async function moveItems(paths, destination) {
  try {
    const result = await postJson("/api/move", {
      paths,
      dst_dir: destination,
    });
    showToast(`移动完成：${result.moved.length}，跳过：${result.skipped.length}`);
    await loadFileList();
  } catch (error) {
    showToast(error.message);
  }
}

function downloadTargets(paths) {
  if (paths.length === 1) {
    location.href = "/api/download?path=" + encodeURIComponent(paths[0]);
    return;
  }

  fetch("/api/download/batch", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({paths}),
  })
    .then(async response => {
      if (!response.ok) {
        let errorData = {};
        try {
          errorData = await response.json();
        } catch {}
        throw Error(errorData.detail || "下载失败");
      }

      const blob = await response.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "download.7z";
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 4000);
    })
    .catch(error => showToast(error.message));
}

// -----------------------------------------------------------------------------
// 上传与拖放
// -----------------------------------------------------------------------------
async function uploadFiles(files, target = state.path, folder = false) {
  files = [...files];
  if (!files.length) return;

  const formData = new FormData();
  formData.append("path", target);

  const relativePaths = [];
  files.forEach(file => {
    formData.append("files", file, file.name);
    relativePaths.push(
      folder && file.webkitRelativePath
        ? file.webkitRelativePath
        : file.name,
    );
  });

  formData.append("relative_paths", JSON.stringify(relativePaths));

  try {
    const result = await requestApi("/api/upload", {
      method: "POST",
      body: formData,
    });
    showToast(`已上传 ${result.count} 个文件`);
    await loadFileList();
  } catch (error) {
    showToast(error.message);
  }
}

fileUploadInput.onchange = () => {
  uploadFiles(fileUploadInput.files, state.path, false);
};

folderUploadInput.onchange = () => {
  uploadFiles(folderUploadInput.files, state.path, true);
};

async function collectDroppedEntries(entry, prefix, output) {
  if (entry.isFile) {
    await new Promise(resolve => {
      entry.file(file => {
        output.push({file, path: prefix + file.name});
        resolve();
      }, resolve);
    });
    return;
  }

  if (entry.isDirectory) {
    const reader = entry.createReader();

    while (true) {
      const batch = await new Promise(resolve => reader.readEntries(resolve));
      if (!batch.length) break;

      for (const child of batch) {
        await collectDroppedEntries(
          child,
          prefix + entry.name + "/",
          output,
        );
      }
    }
  }
}

async function uploadDataTransfer(dataTransfer, target) {
  const transferItems = [...dataTransfer.items];

  if (transferItems.length && transferItems[0].webkitGetAsEntry) {
    const entries = [];

    for (const transferItem of transferItems) {
      const entry = transferItem.webkitGetAsEntry();
      if (entry) {
        await collectDroppedEntries(entry, "", entries);
      }
    }

    if (entries.length) {
      const formData = new FormData();
      formData.append("path", target);

      entries.forEach(entry => {
        formData.append("files", entry.file, entry.file.name);
      });
      formData.append(
        "relative_paths",
        JSON.stringify(entries.map(entry => entry.path)),
      );

      try {
        const result = await requestApi("/api/upload", {
          method: "POST",
          body: formData,
        });
        showToast(`已上传 ${result.count} 个文件`);
        await loadFileList();
      } catch (error) {
        showToast(error.message);
      }
      return;
    }
  }

  await uploadFiles(dataTransfer.files, target, false);
}

function attachDropTarget(element, destination) {
  element.addEventListener("dragover", event => {
    if (
      state.draggingPaths.length ||
      event.dataTransfer.types.includes("Files")
    ) {
      event.preventDefault();
      element.classList.add("drop-over");
      event.dataTransfer.dropEffect = event.dataTransfer.types.includes("Files")
        ? "copy"
        : "move";
    }
  });

  element.addEventListener("dragleave", () => {
    element.classList.remove("drop-over");
  });

  element.addEventListener("drop", async event => {
    event.preventDefault();
    event.stopPropagation();
    element.classList.remove("drop-over");

    if (event.dataTransfer.types.includes("Files")) {
      await uploadDataTransfer(event.dataTransfer, destination);
      return;
    }

    if (state.draggingPaths.length) {
      await moveItems(state.draggingPaths, destination);
    }
  });
}

fileWorkspace.ondragover = event => {
  if (event.dataTransfer.types.includes("Files")) {
    event.preventDefault();
    fileWorkspace.classList.add("external-over");
  }
};

fileWorkspace.ondragleave = event => {
  if (!fileWorkspace.contains(event.relatedTarget)) {
    fileWorkspace.classList.remove("external-over");
  }
};

fileWorkspace.ondrop = event => {
  if (event.dataTransfer.types.includes("Files")) {
    event.preventDefault();
    fileWorkspace.classList.remove("external-over");
    uploadDataTransfer(event.dataTransfer, state.path);
  }
};

// -----------------------------------------------------------------------------
// 任意方向拖框多选
// -----------------------------------------------------------------------------
function rectanglesIntersect(a, b) {
  return (
    a.left < b.right &&
    a.right > b.left &&
    a.top < b.bottom &&
    a.bottom > b.top
  );
}

function beginMarqueeSelection(event) {
  if (
    event.button !== 0 ||
    event.target.closest(".file-card") ||
    event.target.closest("#contextMenu") ||
    event.target.closest(".dialog-panel")
  ) {
    return;
  }

  const additive = event.ctrlKey || event.metaKey || event.shiftKey;

  state.marquee = {
    startX: event.clientX,
    startY: event.clientY,
    moved: false,
    additive,
    baseSelected: new Set(additive ? state.selected : []),
  };

  if (!state.marquee.additive) {
    state.selected.clear();
    refreshSelection();
  }

  selectionMarquee.style.display = "none";
  selectionMarquee.style.width = "0";
  selectionMarquee.style.height = "0";
  event.preventDefault();
}

function moveMarqueeSelection(event) {
  if (!state.marquee) return;

  const marquee = state.marquee;
  const deltaX = event.clientX - marquee.startX;
  const deltaY = event.clientY - marquee.startY;

  if (!marquee.moved && Math.hypot(deltaX, deltaY) < 4) return;
  marquee.moved = true;

  const left = Math.min(marquee.startX, event.clientX);
  const top = Math.min(marquee.startY, event.clientY);
  const right = Math.max(marquee.startX, event.clientX);
  const bottom = Math.max(marquee.startY, event.clientY);

  selectionMarquee.style.display = "block";
  selectionMarquee.style.left = left + "px";
  selectionMarquee.style.top = top + "px";
  selectionMarquee.style.width = right - left + "px";
  selectionMarquee.style.height = bottom - top + "px";

  const selectionRect = {left, top, right, bottom};
  const nextSelection = new Set(marquee.baseSelected);

  fileGrid.querySelectorAll(".file-card").forEach(element => {
    if (rectanglesIntersect(selectionRect, element.getBoundingClientRect())) {
      nextSelection.add(element.dataset.path);
    }
  });

  state.selected = nextSelection;
  refreshSelection();
  event.preventDefault();
}

function endMarqueeSelection() {
  if (!state.marquee) return;

  const moved = state.marquee.moved;
  const additive = state.marquee.additive;
  state.marquee = null;

  selectionMarquee.style.display = "none";
  selectionMarquee.style.width = "0";
  selectionMarquee.style.height = "0";

  if (!moved && !additive) {
    clearSelection();
  } else {
    refreshSelection();
  }
}

fileWorkspace.addEventListener("mousedown", beginMarqueeSelection);
document.addEventListener("mousemove", moveMarqueeSelection);
document.addEventListener("mouseup", endMarqueeSelection);

// -----------------------------------------------------------------------------
// 移动目录选择树
// -----------------------------------------------------------------------------
async function openMoveDialog(paths) {
  let destination = "";

  openModal(
    "移动到…",
    '<div class="folder-tree" id="tree"></div>',
    false,
    [
      {text: "取消", fn: closeModal},
      {
        text: "移动",
        primary: true,
        fn: () => {
          closeModal();
          moveItems(paths, destination);
        },
      },
    ],
  );

  const tree = query("#tree");
  const rootRow = document.createElement("div");
  rootRow.className = "folder-tree-row selected";
  rootRow.innerHTML =
    '<span class="folder-tree-toggle">▾</span><span>📁</span><span>根目录</span>';
  tree.appendChild(rootRow);

  rootRow.onclick = () => {
    tree.querySelectorAll(".folder-tree-row").forEach(row => {
      row.classList.remove("selected");
    });
    rootRow.classList.add("selected");
    destination = "";
  };

  const rootChildren = document.createElement("div");
  rootChildren.className = "folder-tree-children open";
  tree.appendChild(rootChildren);

  async function loadFolderTreeChildren(container, path) {
    container.innerHTML = '<div class="folder-tree-row">加载中…</div>';

    try {
      const data = await requestApi(
        "/api/folders/children?path=" + encodeURIComponent(path),
      );
      container.innerHTML = "";

      data.folders.forEach(folder => {
        const wrapper = document.createElement("div");
        const row = document.createElement("div");
        const children = document.createElement("div");

        row.className = "folder-tree-row";
        children.className = "folder-tree-children";
        row.innerHTML = `
          <span class="folder-tree-toggle">${folder.has_children ? "▸" : ""}</span>
          <span>📁</span>
          <span>${escapeHtml(folder.name)}</span>
        `;

        wrapper.append(row, children);
        container.appendChild(wrapper);

        row.onclick = event => {
          event.stopPropagation();
          tree.querySelectorAll(".folder-tree-row").forEach(treeRow => {
            treeRow.classList.remove("selected");
          });
          row.classList.add("selected");
          destination = folder.path;
        };

        row.querySelector(".folder-tree-toggle").onclick = async event => {
          event.stopPropagation();
          if (!folder.has_children) return;

          if (children.classList.contains("open")) {
            children.classList.remove("open");
            event.target.textContent = "▸";
            return;
          }

          if (!children.dataset.loaded) {
            await loadFolderTreeChildren(children, folder.path);
            children.dataset.loaded = "1";
          }

          children.classList.add("open");
          event.target.textContent = "▾";
        };
      });
    } catch (error) {
      container.textContent = error.message;
    }
  }

  await loadFolderTreeChildren(rootChildren, "");
}

// -----------------------------------------------------------------------------
// 分享
// -----------------------------------------------------------------------------
async function createShareLink(path) {
  try {
    const result = await postJson("/api/share/create", {path});
    const url = new URL(result.share_url, location.href).href;

    try {
      await navigator.clipboard.writeText(url);
      showToast("分享链接已复制");
    } catch {
      prompt("分享链接", url);
    }

    await loadFileList();
  } catch (error) {
    showToast(error.message);
  }
}

function openShareManager() {
  window.open(
    "/shares",
    "fastapi_drive_share_manager",
    "width=880,height=620,resizable=yes,scrollbars=yes",
  );
}

loadFileList("");
</script>
</body>
</html>"""
# -----------------------------------------------------------------------------
# 分享管理页面
# -----------------------------------------------------------------------------
SHARES_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>分享管理 - FastAPI Drive</title>
<style>
*{box-sizing:border-box}
:root{--orange:#F05A00;--dark:rgb(60,0,0);--bg:#fff8f3;--line:#efd5c5;--muted:#8a6552;--danger:#B32600}
html,body{margin:0;min-height:100%;font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--dark)}
body{padding:0}
.share-manager{width:100%;min-height:100vh;margin:0;background:#fff;overflow:hidden}
.share-manager-toolbar{height:40px;display:flex;align-items:center;gap:7px;padding:0 12px;border-bottom:1px solid var(--line);background:#fffaf7}
.share-manager-title{font-size:13px;font-weight:800;white-space:nowrap}
.share-count{font-size:10px;color:var(--muted);flex:1}
.share-user{font-size:10px;color:var(--muted);white-space:nowrap}
.share-action-button{height:25px;border:1px solid #df9b73;background:#fff;color:var(--dark);border-radius:5px;padding:0 8px;font-size:10px;cursor:pointer;white-space:nowrap}
.share-action-button:hover{border-color:var(--orange);background:rgba(240,90,0,.07)}
.share-action-button.danger{border-color:#dc8c6d;color:var(--danger)}
.share-table-header,.share-row{display:grid;grid-template-columns:minmax(170px,1.2fr) minmax(300px,2.8fr) 125px 190px;column-gap:8px;align-items:center}
.share-table-header{min-height:32px;padding:0 12px;border-bottom:1px solid var(--line);background:#fffdfb;color:var(--muted);font-size:10px;font-weight:700}
.share-list{padding:0 12px 8px}
.share-row{min-height:46px;padding:5px 0;border-bottom:1px solid #f3e4da}
.share-row:last-child{border-bottom:0}
.share-row:hover{background:rgba(240,90,0,.035)}
.share-location{min-width:0;font-size:11px;font-weight:650;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.share-location.source-missing{color:#9b7464;text-decoration:line-through}
.share-link{min-width:0;color:#A63E00;font-size:10px;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.share-link:hover{text-decoration:underline}
.share-created-at{color:var(--muted);font-size:10px;white-space:nowrap}
.share-actions{display:flex;justify-content:flex-end;gap:4px}
.share-empty-state{padding:34px 10px;text-align:center;color:var(--muted);font-size:11px}
.share-toast{position:fixed;left:50%;bottom:12px;transform:translateX(-50%);background:var(--dark);color:#fff;border-radius:6px;padding:6px 9px;font-size:10px;display:none;z-index:20}
button:focus-visible,a:focus-visible{outline:2px solid var(--orange);outline-offset:2px}
@media(max-width:720px){body{padding:0}.share-user{display:none}.share-table-header{display:none}.share-row{grid-template-columns:1fr;gap:4px;padding:8px 2px}.share-actions{justify-content:flex-start}.share-created-at{white-space:normal}}
</style>
</head>
<body>
<div class="share-manager">
  <div class="share-manager-toolbar">
    <div class="share-manager-title">分享管理</div>
    <div class="share-count" id="shareCount">加载中…</div>
    <div class="share-user">__USERNAME__</div>
    <button class="share-action-button" id="refreshSharesButton">刷新</button>
    <button class="share-action-button" id="closeSharesButton">关闭</button>
  </div>
  <div class="share-table-header">
    <div>分享位置</div>
    <div>超链接</div>
    <div>创建时间</div>
    <div style="text-align:right">操作</div>
  </div>
  <div class="share-list" id="shareList"></div>
</div>
<div class="share-toast" id="shareToast"></div>

<script>
const shareList = document.getElementById("shareList");
const shareCount = document.getElementById("shareCount");
const toastBox = document.getElementById("shareToast");

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function showToast(message) {
  toastBox.textContent = message;
  toastBox.style.display = "block";
  clearTimeout(window.__toast);
  window.__toast = setTimeout(() => {
    toastBox.style.display = "none";
  }, 1600);
}

async function requestApi(url, options = {}) {
  const response = await fetch(url, options);
  let data = {};

  try {
    data = await response.json();
  } catch {}

  if (!response.ok) {
    throw new Error(data.detail || "请求失败");
  }

  return data;
}

async function copyShareLink(url) {
  try {
    await navigator.clipboard.writeText(url);
    showToast("链接已复制");
  } catch {
    prompt("复制分享链接", url);
  }
}

async function cancelShare(shareId, path) {
  if (!confirm(`取消分享「${path}」？`)) return;

  try {
    await requestApi("/api/share/cancel", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({share_id: shareId}),
    });
    showToast("已取消分享");
    await loadShares();
  } catch (error) {
    showToast(error.message);
  }
}

function renderShareRow(share) {
  const url = new URL(share.share_url, location.href).href;
  const locationText = share.rel_path || "/";
  const row = document.createElement("div");
  row.className = "share-row";
  row.innerHTML = `
    <div class="share-location ${share.exists ? "" : "source-missing"}" title="${escapeHtml(locationText)}">
      ${escapeHtml(locationText)}${share.exists ? "" : "（源已不存在）"}
    </div>
    <a class="share-link" href="${escapeHtml(url)}" target="_blank" rel="noopener" title="${escapeHtml(url)}">${escapeHtml(url)}</a>
    <div class="share-created-at">${escapeHtml(share.created_at || "")}</div>
    <div class="share-actions"></div>
  `;

  const actions = row.querySelector(".share-actions");

  const openButton = document.createElement("button");
  openButton.className = "share-action-button";
  openButton.textContent = "打开";
  openButton.onclick = () => window.open(url, "_blank", "noopener");

  const copyButton = document.createElement("button");
  copyButton.className = "share-action-button";
  copyButton.textContent = "复制";
  copyButton.onclick = () => copyShareLink(url);

  const cancelButton = document.createElement("button");
  cancelButton.className = "share-action-button danger";
  cancelButton.textContent = "取消分享";
  cancelButton.onclick = () => cancelShare(share.id, locationText);

  actions.append(openButton, copyButton, cancelButton);
  return row;
}

async function loadShares() {
  shareCount.textContent = "加载中…";
  shareList.innerHTML = "";

  try {
    const data = await requestApi("/api/share/list");
    shareCount.textContent = `${data.shares.length} 条`;

    if (!data.shares.length) {
      shareList.innerHTML = '<div class="share-empty-state">暂无分享链接</div>';
      return;
    }

    data.shares.forEach(share => {
      shareList.appendChild(renderShareRow(share));
    });
  } catch (error) {
    shareCount.textContent = "加载失败";
    shareList.innerHTML = `<div class="share-empty-state">${escapeHtml(error.message)}</div>`;
  }
}

document.getElementById("refreshSharesButton").onclick = loadShares;
document.getElementById("closeSharesButton").onclick = () => window.close();

loadShares();
</script>
</body>
</html>"""
# -----------------------------------------------------------------------------
# 在线文本编辑页面
# -----------------------------------------------------------------------------
EDITOR_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__FILE_NAME__ - 在线文本</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;height:100%;font-family:system-ui,-apple-system,"Segoe UI",sans-serif}
body{display:flex;flex-direction:column;overflow:hidden;background:#fffdfb}
header{
  height:32px;min-height:32px;
  border-bottom:1px solid #F05A00;
  background:#fff8f3;
  display:flex;align-items:center;gap:6px;
  padding:0 7px
}
.editor-file-name{
  flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:12px;font-weight:700;color:rgb(60,0,0)
}
.editor-meta,.editor-status{font-size:10px;color:rgb(60,0,0);white-space:nowrap}
.editor-toolbar-button{
  border:1px solid #F05A00;background:#fff;color:rgb(60,0,0);
  border-radius:5px;padding:2px 7px;font-size:11px;line-height:18px;cursor:pointer
}
#textEditor{
  flex:1;width:100%;border:0;outline:0;resize:none;
  background:#fffdfb;color:rgb(60,0,0);
  padding:12px 15px;
  font:13px/1.6 ui-monospace,SFMono-Regular,Consolas,"Liberation Mono",monospace;
  tab-size:4
}
#textEditor::selection{background:#FFD700;color:rgb(60,0,0)}
#textEditor::-moz-selection{background:#FFD700;color:rgb(60,0,0)}
#textEditor[readonly]{cursor:text}
button:focus-visible,#textEditor:focus-visible{outline:2px solid #F05A00;outline-offset:-2px}
@media(max-width:650px){
  header{height:30px;min-height:30px;gap:4px;padding:0 5px}
  .editor-meta{display:none}
  #textEditor{padding:10px 12px;font-size:12px}
}
</style>
</head>
<body>
<header class="editor-toolbar">
  <div class="editor-file-name">__FILE_NAME__</div>
  <div id="encodingLabel" class="editor-meta">编码检测中…</div>
  <div id="editorStatus" class="editor-status"></div>
  <button id="saveTextButton" class="editor-toolbar-button">保存</button>
  <button id="closeEditorButton" class="editor-toolbar-button">关闭</button>
</header>
<textarea id="textEditor" spellcheck="false" disabled></textarea>

<script>
const FILE_PATH = __FILE_PATH__;
const LOAD_URL = __LOAD_URL__;
const SAVE_URL = __SAVE_URL__;
const READ_ONLY = __READ_ONLY__;

const editor = document.getElementById("textEditor");
const encodingLabel = document.getElementById("encodingLabel");
const statusLabel = document.getElementById("editorStatus");
const saveButton = document.getElementById("saveTextButton");

let encoding = "utf-8";
let dirty = false;
let saving = false;

async function requestApi(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json();

  if (!response.ok) {
    throw new Error(data.detail || "请求失败");
  }

  return data;
}

async function loadText() {
  try {
    const data = await requestApi(LOAD_URL);
    encoding = data.encoding || "utf-8";
    editor.value = data.content || "";
    editor.disabled = false;
    editor.readOnly = READ_ONLY;
    editor.focus();
    encodingLabel.textContent = "编码：" + encoding;

    if (READ_ONLY) {
      statusLabel.textContent = "分享只读";
      saveButton.style.display = "none";
    } else {
      statusLabel.textContent = "Ctrl+S 保存";
    }
  } catch (error) {
    statusLabel.textContent = error.message;
  }
}

async function saveText() {
  if (READ_ONLY || saving || editor.disabled) return;

  saving = true;
  saveButton.disabled = true;
  statusLabel.textContent = "保存中…";

  try {
    const data = await requestApi(SAVE_URL, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        path: FILE_PATH,
        content: editor.value,
        encoding,
      }),
    });

    encoding = data.encoding || encoding;
    encodingLabel.textContent = "编码：" + encoding;
    statusLabel.textContent = data.converted_to_utf8
      ? "已保存 · 已转 UTF-8"
      : "已保存";
    dirty = false;
  } catch (error) {
    statusLabel.textContent = "保存失败：" + error.message;
  } finally {
    saving = false;
    saveButton.disabled = false;
  }
}

editor.addEventListener("input", () => {
  if (READ_ONLY) return;
  dirty = true;
  statusLabel.textContent = "未保存";
});

document.addEventListener("keydown", event => {
  if (
    !READ_ONLY &&
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "s"
  ) {
    event.preventDefault();
    saveText();
  }
});

saveButton.onclick = saveText;
document.getElementById("closeEditorButton").onclick = () => window.close();

window.addEventListener("beforeunload", event => {
  if (!READ_ONLY && dirty) {
    event.preventDefault();
    event.returnValue = "";
  }
});

loadText();
</script>
</body>
</html>"""

# -----------------------------------------------------------------------------
# 图片 / 视频 / 音频 / PDF 查看页面
# -----------------------------------------------------------------------------
MEDIA_VIEW_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__FILE_NAME__ - 在线预览</title>
<style>
*{box-sizing:border-box}
html,body{
  margin:0;
  width:100%;
  height:100%;
  font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;
  background:#fff8f3;
  color:rgb(60,0,0)
}
body{display:flex;flex-direction:column;overflow:hidden}
header{
  height:34px;
  min-height:34px;
  display:flex;
  align-items:center;
  gap:7px;
  padding:0 8px;
  border-bottom:1px solid #F05A00;
  background:#fffaf7
}
.viewer-file-name{
  flex:1;
  min-width:0;
  overflow:hidden;
  white-space:nowrap;
  text-overflow:ellipsis;
  font-size:12px;
  font-weight:700
}
.viewer-media-kind{font-size:10px;color:#8a6552;white-space:nowrap}
.viewer-toolbar-button{
  height:24px;
  border:1px solid #F05A00;
  background:#fff;
  color:rgb(60,0,0);
  border-radius:5px;
  padding:0 8px;
  font-size:10px;
  cursor:pointer
}
.viewer-toolbar-button:hover{background:rgba(240,90,0,.07)}
.image-zoom-controls{
  display:none;
  align-items:center;
  gap:3px;
  margin-left:auto
}
body.image-mode .image-zoom-controls{display:flex}
.image-zoom-button{
  min-width:22px;
  height:22px;
  border:1px solid #df9b73;
  background:#fff;
  color:rgb(60,0,0);
  border-radius:4px;
  padding:0 5px;
  font-size:10px;
  line-height:20px;
  cursor:pointer
}
.image-zoom-button:hover{
  border-color:#F05A00;
  background:rgba(240,90,0,.07)
}
.image-zoom-value{
  min-width:34px;
  text-align:center;
  font-size:9px;
  color:#8a6552;
  user-select:none
}
main{
  flex:1;
  min-height:0;
  display:flex;
  align-items:center;
  justify-content:center;
  overflow:auto;
  padding:10px
}
.preview-image{
  display:block;
  max-width:none;
  max-height:none;
  object-fit:contain
}
body.image-mode main{overflow:auto}
.preview-video{
  display:block;
  width:100%;
  height:100%;
  max-width:100%;
  max-height:100%;
  object-fit:contain;
  background:#000;
  border:0;
  outline:0
}
body.video-mode main{
  padding:2px;
  overflow:hidden
}
.audio-player-panel{
  width:min(92vw,720px);
  padding:18px;
  background:#fff;
  border:1px solid #efd5c5;
  border-radius:8px
}
.preview-audio{display:block;width:100%}
.preview-pdf{
  display:block;
  width:100%;
  height:100%;
  min-height:0;
  border:0;
  background:#fff
}
body.pdf-mode main{
  padding:0;
  align-items:stretch;
  justify-content:stretch;
  overflow:hidden
}
button:focus-visible{
  outline:2px solid #F05A00;
  outline-offset:2px
}
@media(max-width:650px){
  header{height:32px;min-height:32px;padding:0 5px;gap:4px}
  .viewer-media-kind{display:none}
  main{padding:6px}
}
</style>
</head>
<body class="__BODY_CLASS__">
<header class="viewer-toolbar">
  <div class="viewer-file-name" title="__FILE_NAME__">__FILE_NAME__</div>
  <div class="viewer-media-kind">__MEDIA_LABEL__</div>
  <div class="image-zoom-controls" id="imageZoomControls">
    <button class="image-zoom-button" id="zoomOutButton" title="缩小">−</button>
    <span class="image-zoom-value" id="zoomPercentage">100%</span>
    <button class="image-zoom-button" id="zoomInButton" title="放大">+</button>
    <button class="image-zoom-button" id="zoomFitButton" title="适应窗口">适应</button>
  </div>
  <button class="viewer-toolbar-button" id="downloadMediaButton">下载</button>
  <button class="viewer-toolbar-button" id="closeViewerButton">关闭</button>
</header>
<main id="mediaViewport">__MEDIA_BODY__</main>
<script>
const DOWNLOAD_URL = __DOWNLOAD_URL__;
const MEDIA_KIND = __MEDIA_KIND__;

document.getElementById("downloadMediaButton").onclick = () => {
  location.href = DOWNLOAD_URL;
};

document.getElementById("closeViewerButton").onclick = () => window.close();

if (MEDIA_KIND === "image") {
  const image = document.querySelector(".preview-image");
  const zoomValue = document.getElementById("zoomPercentage");

  let zoom = 1;

  function applyZoom() {
    if (!image) return;

    image.style.width = `${image.naturalWidth * zoom}px`;
    image.style.height = "auto";
    zoomValue.textContent = `${Math.round(zoom * 100)}%`;
  }

  function fitImage() {
    if (!image || !image.naturalWidth || !image.naturalHeight) return;

    const main = document.getElementById("mediaViewport");
    const availableWidth = Math.max(1, main.clientWidth - 20);
    const availableHeight = Math.max(1, main.clientHeight - 20);

    zoom = Math.min(
      1,
      availableWidth / image.naturalWidth,
      availableHeight / image.naturalHeight
    );

    applyZoom();
  }

  image.addEventListener("load", fitImage);

  if (image.complete) {
    fitImage();
  }

  document.getElementById("zoomOutButton").onclick = () => {
    zoom = Math.max(0.1, zoom - 0.1);
    applyZoom();
  };

  document.getElementById("zoomInButton").onclick = () => {
    zoom = Math.min(5, zoom + 0.1);
    applyZoom();
  };

  document.getElementById("zoomFitButton").onclick = fitImage;
}
</script>
</body>
</html>"""

# -----------------------------------------------------------------------------
# 公开分享页面
# -----------------------------------------------------------------------------
PUBLIC_SHARE_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__SHARE_NAME__ - 分享</title>
<style>
*{box-sizing:border-box}
html,body{margin:0;height:100%;font-family:system-ui,-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#f7f7f8;color:#222}
body{display:flex;flex-direction:column;overflow:hidden}
header{height:44px;min-height:44px;background:#fff;border-bottom:1px solid #ddd;display:flex;align-items:center;padding:0 10px;gap:5px}
#shareBreadcrumbs{display:flex;align-items:center;gap:4px;min-width:0;flex:1;overflow:auto;white-space:nowrap}
.share-breadcrumb-button{border:0;background:transparent;padding:5px 6px;border-radius:6px;cursor:pointer}
.share-breadcrumb-button:hover{background:rgba(240,90,0,.08)}
.share-download-button{border:1px solid #F05A00;background:#fff;color:#A63E00;border-radius:6px;padding:5px 8px;cursor:pointer;font-size:12px}
main{position:relative;flex:1;overflow:auto;padding:8px}
#shareFileGrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(86px,104px));gap:7px;align-content:start;justify-content:start;min-height:100%}
.share-file-card{aspect-ratio:1;background:#fff;border:1px solid #ddd;border-radius:7px;padding:6px;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;user-select:none}
.share-file-card:hover{border-color:#F05A00}
.share-file-card.selected{background:rgba(240,90,0,.10);border-color:#F05A00;box-shadow:0 0 0 1px #F05A00 inset}
.share-file-icon{font-size:22px}
.share-file-name{width:100%;min-height:27px;font-size:11px;line-height:1.22;text-align:center;white-space:normal;overflow:hidden;word-break:break-all;display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;margin-top:5px}
.share-file-meta{font-size:9px;color:#888;margin-top:2px}
#shareSelectionMarquee{position:fixed;display:none;pointer-events:none;z-index:50;border:1px solid #F05A00;background:rgba(240,90,0,.14)}
#shareContextMenu{position:fixed;display:none;z-index:80;min-width:160px;background:#fff;border:1px solid #ddd;border-radius:7px;padding:5px;box-shadow:0 10px 24px #0002}
.share-context-menu-item{padding:7px 9px;border-radius:5px;font-size:12px;cursor:pointer}
.share-context-menu-item:hover{background:rgba(240,90,0,.08)}
.share-dialog-overlay{position:fixed;inset:0;background:#0005;display:none;align-items:center;justify-content:center;padding:14px;z-index:100}
.share-dialog-overlay.show{display:flex}
.share-dialog{width:min(96vw,1000px);max-height:90vh;background:#fff;border-radius:9px;overflow:hidden}
.share-dialog-header{height:40px;border-bottom:1px solid #eee;padding:0 10px;display:flex;align-items:center;justify-content:space-between}
.share-dialog-body{padding:10px;max-height:80vh;overflow:auto}
.share-media-player{width:100%;max-height:75vh;background:#000}
.share-image-preview{display:block;max-width:100%;max-height:75vh;margin:auto}
.share-pdf-preview{width:100%;height:75vh;border:0}
.share-text-preview{white-space:pre-wrap;word-break:break-word;font:12px/1.55 ui-monospace,monospace}
#shareSelectionIndicator{position:fixed;left:10px;bottom:10px;background:#fff;border:1px solid #ddd;border-radius:999px;padding:5px 9px;font-size:11px;display:none}
</style>
</head>
<body>
<header>
  <div id="shareBreadcrumbs"></div>
  <button class="share-download-button" id="downloadCurrentButton">下载当前</button>
</header>
<main id="shareWorkspace">
  <div id="shareFileGrid"></div>
</main>
<div id="shareSelectionMarquee"></div>
<div id="shareContextMenu"></div>
<div id="shareDialogOverlay" class="share-dialog-overlay"></div>
<div id="shareSelectionIndicator"></div>

<script>
const TOKEN = __TOKEN__;
const SHARE_NAME = "__SHARE_NAME__";

let currentSubpath = "";
let items = [];
let selectedPaths = new Set();
let selectionAnchor = null;
let marqueeState = null;

const shareFileGrid = document.getElementById("shareFileGrid");
const shareWorkspace = document.getElementById("shareWorkspace");
const shareBreadcrumbs = document.getElementById("shareBreadcrumbs");
const shareDialogOverlay = document.getElementById("shareDialogOverlay");
const shareSelectionMarquee = document.getElementById("shareSelectionMarquee");
const shareContextMenu = document.getElementById("shareContextMenu");
const shareSelectionIndicator = document.getElementById("shareSelectionIndicator");

// -----------------------------------------------------------------------------
// 通用工具
// -----------------------------------------------------------------------------
function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

function getItemIcon(item) {
  if (item.type === "folder") return "📁";
  if (item.preview_type === "text") return "📝";
  if (item.preview_type === "image") return "🖼️";
  if (item.preview_type === "video") return "🎬";
  if (item.preview_type === "audio") return "🎵";
  if (item.preview_type === "pdf") return "📕";
  return "📄";
}

async function requestApi(url, options = {}) {
  const response = await fetch(url, options);
  const contentType = response.headers.get("content-type") || "";
  let data = null;

  if (contentType.includes("json")) {
    data = await response.json();
  }

  if (!response.ok) {
    throw new Error(data?.detail || "请求失败");
  }

  return data || response;
}

// -----------------------------------------------------------------------------
// 选择状态
// -----------------------------------------------------------------------------
function refreshSelection() {
  document.querySelectorAll(".share-file-card").forEach(element => {
    element.classList.toggle(
      "selected",
      selectedPaths.has(element.dataset.path),
    );
  });

  shareSelectionIndicator.textContent = `已选择 ${selectedPaths.size} 项`;
  shareSelectionIndicator.style.display = selectedPaths.size ? "block" : "none";
}

function clearSelection() {
  selectedPaths.clear();
  selectionAnchor = null;
  refreshSelection();
}

function selectOnly(path) {
  selectedPaths = new Set([path]);
  selectionAnchor = path;
  refreshSelection();
}

function toggleSelection(path) {
  if (selectedPaths.has(path)) {
    selectedPaths.delete(path);
  } else {
    selectedPaths.add(path);
  }

  selectionAnchor = path;
  refreshSelection();
}

function selectRange(path, additive = false) {
  const itemPaths = items.map(item => item.path);
  const anchorIndex = itemPaths.indexOf(selectionAnchor);
  const targetIndex = itemPaths.indexOf(path);

  if (anchorIndex < 0 || targetIndex < 0) {
    selectOnly(path);
    return;
  }

  const nextSelection = additive
    ? new Set(selectedPaths)
    : new Set();

  for (
    let index = Math.min(anchorIndex, targetIndex);
    index <= Math.max(anchorIndex, targetIndex);
    index += 1
  ) {
    nextSelection.add(itemPaths[index]);
  }

  selectedPaths = nextSelection;
  refreshSelection();
}

// -----------------------------------------------------------------------------
// 目录与文件列表
// -----------------------------------------------------------------------------
function renderBreadcrumbs() {
  shareBreadcrumbs.innerHTML = "";

  let accumulatedPath = "";
  const crumbs = [{name: SHARE_NAME, path: ""}];

  currentSubpath
    .split("/")
    .filter(Boolean)
    .forEach(part => {
      accumulatedPath = accumulatedPath
        ? accumulatedPath + "/" + part
        : part;
      crumbs.push({name: part, path: accumulatedPath});
    });

  crumbs.forEach((crumb, index) => {
    const button = document.createElement("button");
    button.className = "share-breadcrumb-button";
    button.textContent = crumb.name;
    button.onclick = () => loadSharePath(crumb.path);
    shareBreadcrumbs.appendChild(button);

    if (index < crumbs.length - 1) {
      const separator = document.createElement("span");
      separator.textContent = "/";
      shareBreadcrumbs.appendChild(separator);
    }
  });
}

async function loadSharePath(path = "") {
  const data = await requestApi(
    `/s/${TOKEN}/api/list?subpath=${encodeURIComponent(path)}`,
  );

  currentSubpath = data.subpath || "";
  items = data.items || [];
  selectedPaths.clear();
  selectionAnchor = null;
  renderBreadcrumbs();
  shareFileGrid.innerHTML = "";

  if (data.item_type === "file" && data.current) {
    openItem(data.current);
    return;
  }

  items.forEach(item => {
    const card = document.createElement("div");
    card.className = "share-file-card";
    card.dataset.path = item.path;
    card.innerHTML = `
      <div class="share-file-icon">${getItemIcon(item)}</div>
      <div class="share-file-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</div>
      <div class="share-file-meta">${item.type === "folder" ? "文件夹" : ""}</div>
    `;

    card.onclick = event => {
      if (event.shiftKey) {
        selectRange(item.path, event.ctrlKey || event.metaKey);
        return;
      }

      if (event.ctrlKey || event.metaKey) {
        toggleSelection(item.path);
        return;
      }

      clearSelection();
      if (item.type === "folder") {
        loadSharePath(item.path);
      } else {
        downloadItem(item);
      }
    };

    card.oncontextmenu = event => {
      event.preventDefault();
      if (!selectedPaths.has(item.path)) {
        selectOnly(item.path);
      }
      showContextMenu(event.clientX, event.clientY, item);
    };

    shareFileGrid.appendChild(card);
  });

  refreshSelection();
}

// -----------------------------------------------------------------------------
// 打开与下载
// -----------------------------------------------------------------------------
function downloadItem(item) {
  location.href =
    `/s/${TOKEN}/download?subpath=${encodeURIComponent(item.path || "")}`;
}

async function openItem(item) {
  if (item.type === "folder") {
    loadSharePath(item.path);
    return;
  }

  const encodedPath = encodeURIComponent(item.path || "");

  if (item.preview_type === "text") {
    window.open(
      `/s/${TOKEN}/view?subpath=${encodedPath}`,
      "_blank",
      "noopener",
    );
    return;
  }

  if (["image", "video", "audio", "pdf"].includes(item.preview_type)) {
    window.open(
      `/s/${TOKEN}/viewer?subpath=${encodedPath}`,
      "_blank",
      "noopener",
    );
    return;
  }

  location.href = `/s/${TOKEN}/download?subpath=${encodedPath}`;
}

function openModal(title, body) {
  shareDialogOverlay.innerHTML = `
    <div class="share-dialog">
      <div class="share-dialog-header">
        <b>${escapeHtml(title)}</b>
        <button id="shareDialogCloseButton">×</button>
      </div>
      <div class="share-dialog-body">${body}</div>
    </div>
  `;
  shareDialogOverlay.classList.add("show");
  document.getElementById("shareDialogCloseButton").onclick = closeModal;
}

function closeModal() {
  shareDialogOverlay.classList.remove("show");
  shareDialogOverlay.innerHTML = "";
}

shareDialogOverlay.onclick = event => {
  if (event.target === shareDialogOverlay) {
    closeModal();
  }
};

// -----------------------------------------------------------------------------
// 右键菜单
// -----------------------------------------------------------------------------
function showContextMenu(x, y, item) {
  shareContextMenu.innerHTML = "";
  const currentSelection = [...selectedPaths];

  const addMenuItem = (text, handler) => {
    const row = document.createElement("div");
    row.className = "share-context-menu-item";
    row.textContent = text;
    row.onclick = () => {
      shareContextMenu.style.display = "none";
      handler();
    };
    shareContextMenu.appendChild(row);
  };

  if (
    currentSelection.length === 1 &&
    item &&
    item.type === "folder"
  ) {
    addMenuItem("打开", () => loadSharePath(item.path));
  }

  if (
    currentSelection.length === 1 &&
    item &&
    item.type === "file" &&
    item.preview_type !== "none"
  ) {
    addMenuItem(
      item.preview_type === "text" ? "新页面查看" : "在线预览",
      () => openItem(item),
    );
  }

  addMenuItem(
    currentSelection.length > 1
      ? `下载所选 ${currentSelection.length} 项为 7z`
      : "下载",
    () => downloadSelected(currentSelection),
  );

  shareContextMenu.style.display = "block";
  const rect = shareContextMenu.getBoundingClientRect();
  shareContextMenu.style.left = Math.max(5, Math.min(x, innerWidth - rect.width - 6)) + "px";
  shareContextMenu.style.top = Math.max(5, Math.min(y, innerHeight - rect.height - 6)) + "px";
}

document.addEventListener("click", event => {
  if (!event.target.closest("#shareContextMenu")) {
    shareContextMenu.style.display = "none";
  }
});

shareWorkspace.oncontextmenu = event => {
  if (event.target.closest(".share-file-card")) return;
  event.preventDefault();

  if (selectedPaths.size) {
    showContextMenu(event.clientX, event.clientY, null);
  }
};

function downloadSelected(paths) {
  if (!paths.length) return;

  if (paths.length === 1) {
    location.href =
      `/s/${TOKEN}/download?subpath=${encodeURIComponent(paths[0])}`;
    return;
  }

  fetch(`/s/${TOKEN}/download/batch`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({paths}),
  })
    .then(async response => {
      if (!response.ok) {
        let errorData = {};
        try {
          errorData = await response.json();
        } catch {}
        throw new Error(errorData.detail || "下载失败");
      }

      const blob = await response.blob();
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "share-selected.7z";
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 4000);
    })
    .catch(error => alert(error.message));
}

// -----------------------------------------------------------------------------
// 任意方向拖框多选
// -----------------------------------------------------------------------------
function rectanglesIntersect(a, b) {
  return (
    a.left < b.right &&
    a.right > b.left &&
    a.top < b.bottom &&
    a.bottom > b.top
  );
}

shareWorkspace.addEventListener("mousedown", event => {
  if (
    event.button !== 0 ||
    event.target.closest(".share-file-card") ||
    event.target.closest("#shareContextMenu") ||
    event.target.closest(".share-dialog")
  ) {
    return;
  }

  const additive = event.ctrlKey || event.metaKey || event.shiftKey;

  marqueeState = {
    startX: event.clientX,
    startY: event.clientY,
    moved: false,
    additive,
    baseSelected: new Set(additive ? selectedPaths : []),
  };

  if (!additive) {
    selectedPaths.clear();
    refreshSelection();
  }

  event.preventDefault();
});

document.addEventListener("mousemove", event => {
  if (!marqueeState) return;

  const deltaX = event.clientX - marqueeState.startX;
  const deltaY = event.clientY - marqueeState.startY;

  if (!marqueeState.moved && Math.hypot(deltaX, deltaY) < 4) return;
  marqueeState.moved = true;

  const left = Math.min(marqueeState.startX, event.clientX);
  const top = Math.min(marqueeState.startY, event.clientY);
  const right = Math.max(marqueeState.startX, event.clientX);
  const bottom = Math.max(marqueeState.startY, event.clientY);

  Object.assign(shareSelectionMarquee.style, {
    display: "block",
    left: left + "px",
    top: top + "px",
    width: right - left + "px",
    height: bottom - top + "px",
  });

  const selectionRect = {left, top, right, bottom};
  const nextSelection = new Set(marqueeState.baseSelected);

  shareFileGrid.querySelectorAll(".share-file-card").forEach(element => {
    if (rectanglesIntersect(selectionRect, element.getBoundingClientRect())) {
      nextSelection.add(element.dataset.path);
    }
  });

  selectedPaths = nextSelection;
  refreshSelection();
  event.preventDefault();
});

document.addEventListener("mouseup", () => {
  if (!marqueeState) return;

  const moved = marqueeState.moved;
  const additive = marqueeState.additive;
  marqueeState = null;

  shareSelectionMarquee.style.display = "none";
  shareSelectionMarquee.style.width = "0";
  shareSelectionMarquee.style.height = "0";

  if (!moved && !additive) {
    clearSelection();
  }
});

document.addEventListener("keydown", event => {
  if (
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "a"
  ) {
    event.preventDefault();
    selectedPaths = new Set(items.map(item => item.path));
    refreshSelection();
  }

  if (event.key === "Escape") {
    clearSelection();
    closeModal();
  }
});

document.getElementById("downloadCurrentButton").onclick = () => {
  location.href =
    `/s/${TOKEN}/download?subpath=${encodeURIComponent(currentSubpath)}`;
};

loadSharePath("");
</script>
</body>
</html>"""


def main() -> None:
    try:
        import uvicorn
    except ImportError as exc:
        raise SystemExit("缺少 uvicorn，请先执行：pip install uvicorn") from exc

    print("=" * 56)
    print("FastAPI Drive")
    print(f"Local : http://127.0.0.1:{PORT}")
    print(f"Host  : {HOST}")
    print(f"Port  : {PORT}")
    print("=" * 56)

    uvicorn.run(
        app,
        host=HOST,
        port=5000,
        log_level=LOG_LEVEL,
    )


if __name__ == "__main__":
    main()
