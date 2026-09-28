import hashlib
import warnings
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError
from pypdf import PdfReader

from app.errors import DomainError


async def save_upload(upload, root, limit):
    root.mkdir(parents=True, exist_ok=True)
    target = root / (uuid4().hex + ".upload")
    size, checksum = 0, hashlib.sha256()
    try:
        with target.open("xb") as stream:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise DomainError("file_too_large", "上传文件超过允许大小", status=413)
                checksum.update(chunk)
                stream.write(chunk)
        if not size:
            raise DomainError("invalid_file", "不能上传空文件")
        return target, checksum.hexdigest(), size
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def validate_pdf(path, filename, max_pages):
    if Path(filename).suffix.lower() != ".pdf":
        raise DomainError("invalid_pdf", "请选择 PDF 文件")
    try:
        with path.open("rb") as stream:
            if not stream.read(1024).lstrip().startswith(b"%PDF-"):
                raise ValueError("header")
        reader = PdfReader(path, strict=True)
        if reader.is_encrypted:
            raise DomainError("encrypted_pdf", "请上传已解除加密的 PDF")
        count = len(reader.pages)
        if not 1 <= count <= max_pages:
            raise DomainError("page_limit", f"PDF 页数须为 1～{max_pages}")
        return count
    except DomainError:
        raise
    except Exception as error:
        raise DomainError("invalid_pdf", "PDF 已损坏或无法读取") from error


def validate_image(path):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as picture:
                kind, dimensions = picture.format, picture.size
                if kind not in {"JPEG", "PNG"} or picture.width * picture.height > 40_000_000:
                    raise ValueError("format or dimensions")
                picture.verify()
        return {"mime_type": "image/jpeg" if kind == "JPEG" else "image/png",
                "extension": ".jpg" if kind == "JPEG" else ".png", "width": dimensions[0], "height": dimensions[1]}
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as error:
        raise DomainError("invalid_image", "需要完整 JPEG/PNG 图片，且不超过 4000 万像素") from error
