from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
import fitz  # PyMuPDF
from PyQt6.QtGui import QImage

@dataclass
class LoadedMap:
    qimage: QImage
    source_path: str
    is_pdf: bool = False
    pdf_page: int = 0
    dpi: int = 150

def pil_to_qimage(im: Image.Image) -> QImage:
    if im.mode not in ("RGBA", "RGB"):
        im = im.convert("RGBA")
    if im.mode == "RGB":
        w, h = im.size
        data = im.tobytes("raw", "RGB")
        return QImage(data, w, h, 3*w, QImage.Format.Format_RGB888).copy()
    w, h = im.size
    data = im.tobytes("raw", "RGBA")
    return QImage(data, w, h, 4*w, QImage.Format.Format_RGBA8888).copy()

def load_image(path: str) -> QImage:
    im = Image.open(path)
    try:
        from PIL import ImageOps
        im = ImageOps.exif_transpose(im)
    except Exception:
        pass
    return pil_to_qimage(im)

def render_pdf_page(path: str, page_index: int = 0, dpi: int = 150) -> QImage:
    doc = fitz.open(path)
    page_index = max(0, min(page_index, len(doc)-1))
    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=True)
    q = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGBA8888).copy()
    doc.close()
    return q

def load_map(path: str, pdf_page: int = 0, pdf_dpi: int = 150) -> LoadedMap:
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        qimg = render_pdf_page(path, pdf_page, pdf_dpi)
        return LoadedMap(qimage=qimg, source_path=str(Path(path).resolve()), is_pdf=True, pdf_page=pdf_page, dpi=pdf_dpi)
    qimg = load_image(path)
    return LoadedMap(qimage=qimg, source_path=str(Path(path).resolve()), is_pdf=False)


def resolve_user_path_portable(p: str) -> str:
    """Return an absolute path for a user-provided path.
    Keeps absolute paths; otherwise resolves relative to current working directory.
    (Portable-friendly helper; safe no-op unless you call it.)
    """
    pp = Path(p)
    if pp.is_absolute():
        return str(pp)
    return str((Path.cwd() / pp).resolve())
