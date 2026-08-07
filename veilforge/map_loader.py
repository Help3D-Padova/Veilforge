from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path

from PIL import Image
import fitz  # PyMuPDF
from PyQt6.QtGui import QImage

@dataclass
class LoadedMap:
    qimage: QImage = None
    source_path: str = ""
    is_pdf: bool = False
    pdf_page: int = 0
    dpi: int = 150
    is_video: bool = False  # Ajout d'un attribut pour savoir si c'est une vidéo

def pil_to_qimage(im: Image.Image) -> QImage:
    # Convertit une image PIL en QImage  
    if im.mode not in ("RGBA", "RGB"):
        im = im.convert("RGBA")
    if im.mode == "RGB":
        w, h = im.size  
        data = im.tobytes("raw", "RGB")
        return QImage(data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    w, h = im.size  
    data = im.tobytes("raw", "RGBA")
    return QImage(data, w, h, 4 * w, QImage.Format.Format_RGBA8888).copy()

def load_image(path: str) -> QImage:
    # Charge une image à partir du chemin spécifié  
    im = Image.open(path)
    try:
        from PIL import ImageOps  
        im = ImageOps.exif_transpose(im)  # Corrige l'orientation de l'image  
    except Exception:
        pass  
    return pil_to_qimage(im)

def render_pdf_page(path: str, page_index: int = 0, dpi: int = 150) -> QImage:
    # Rendu d'une page PDF en tant que QImage
    doc = fitz.open(path)
    page_index = max(0, min(page_index, len(doc) - 1))
    page = doc.load_page(page_index)
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat, alpha=True)
    q = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGBA8888).copy()
    doc.close()
    return q


def load_map(path: str, pdf_page: int = 0, pdf_dpi: int = 150) -> LoadedMap:
    # Charge une carte (image/PDF/vidéo/audio) selon son type
    #
    # Pour les vidéos et les fichiers audio, nous ne rendons pas d'image de
    # prévisualisation. L'appelant doit ouvrir le flux média via QMediaPlayer
    # en utilisant `LoadedMap.source_path`.
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Map file not found: {path}")
    ext = p.suffix.lower()
    video_exts = {".mp4", ".webm", ".m4a", ".mkv", ".mov", ".avi", ".flv", ".m2ts", ".ts", ".3gp"}
    if ext == ".pdf":
        qimg = render_pdf_page(path, pdf_page, pdf_dpi)
        return LoadedMap(qimage=qimg, source_path=str(p.resolve()), is_pdf=True, pdf_page=pdf_page, dpi=pdf_dpi)
    elif ext in video_exts:
        return LoadedMap(source_path=str(p.resolve()), is_video=True)
    qimg = load_image(path)
    return LoadedMap(qimage=qimg, source_path=str(p.resolve()), is_pdf=False)

def resolve_user_path_portable(p: str) -> str:
    """Retourne un chemin absolu pour un chemin fourni par l'utilisateur.
    Garde les chemins absolus ; sinon, résout par rapport au répertoire de travail actuel.
    (Fonction d'aide portable ; opération sûre sauf si vous l'appelez.)
    """
    pp = Path(p)
    if pp.is_absolute():
        return str(pp)
    return str((Path.cwd() / pp).resolve())
