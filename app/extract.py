"""Приём файлов: проверка формата по содержимому и извлечение текста."""
from __future__ import annotations

import html
import io
import re
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from xml.etree import ElementTree

# расширение -> (вид, MIME)
FORMATS = {
    ".pdf": ("pdf", "application/pdf"),
    ".docx": ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ".odt": ("odt", "application/vnd.oasis.opendocument.text"),
    ".rtf": ("rtf", "application/rtf"),
    ".txt": ("text", "text/plain"),
    ".md": ("text", "text/plain"),
    ".csv": ("text", "text/plain"),
    ".html": ("html", "text/html"),
    ".htm": ("html", "text/html"),
    ".xlsx": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".png": ("image", "image/png"),
    ".webp": ("image", "image/webp"),
    ".gif": ("image", "image/gif"),
}

UNSUPPORTED_HINTS = {
    ".doc": "Старый формат Word (.doc) не поддерживается. Сохраните файл как .docx или PDF.",
    ".xls": "Старый формат Excel (.xls) не поддерживается. Сохраните файл как .xlsx или PDF.",
    ".heic": "Формат HEIC не поддерживается. Сохраните фото как JPG или PNG (на iPhone: Настройки → Камера → Форматы → Наиболее совместимый).",
    ".heif": "Формат HEIF не поддерживается. Сохраните фото как JPG или PNG.",
    ".pages": "Формат Pages не поддерживается. Экспортируйте документ в PDF или DOCX.",
    ".zip": "Архивы не принимаются. Загрузите сами документы.",
    ".rar": "Архивы не принимаются. Загрузите сами документы.",
}

ACCEPT = sorted(FORMATS)


class FileRejected(ValueError):
    pass


@dataclass
class Detected:
    kind: str
    mime: str
    ext: str


def _ext(name: str) -> str:
    m = re.search(r"(\.[A-Za-z0-9]{1,6})$", name or "")
    return m.group(1).lower() if m else ""


def safe_filename(name: str) -> str:
    name = (name or "файл").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", "_", name).strip(" .") or "файл"
    return name[:120]


def _zip_has(data: bytes, member: str) -> bool:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return member in z.namelist()
    except zipfile.BadZipFile:
        return False


def _odt_mimetype(data: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            return z.read("mimetype").decode("ascii", "ignore").strip()
    except (zipfile.BadZipFile, KeyError):
        return ""


def _looks_textual(data: bytes) -> bool:
    sample = data[:4096]
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
        return True
    except UnicodeDecodeError:
        try:
            sample.decode("cp1251")
            return True
        except UnicodeDecodeError:
            return False


def detect(name: str, data: bytes) -> Detected:
    """Определяет формат по расширению и проверяет, что содержимое ему соответствует."""
    ext = _ext(name)
    if ext in UNSUPPORTED_HINTS:
        raise FileRejected(UNSUPPORTED_HINTS[ext])
    if ext not in FORMATS:
        raise FileRejected(f"Формат файла «{safe_filename(name)}» не поддерживается. Подойдут: PDF, DOCX, ODT, RTF, TXT, XLSX, JPG, PNG, WEBP.")
    if not data:
        raise FileRejected(f"Файл «{safe_filename(name)}» пустой.")
    kind, mime = FORMATS[ext]
    ok = True
    if kind == "pdf":
        ok = data[:1024].lstrip().startswith(b"%PDF-")
    elif kind == "docx":
        ok = data[:2] == b"PK" and _zip_has(data, "word/document.xml")
    elif kind == "xlsx":
        ok = data[:2] == b"PK" and _zip_has(data, "xl/workbook.xml")
    elif kind == "odt":
        ok = data[:2] == b"PK" and _odt_mimetype(data) == "application/vnd.oasis.opendocument.text"
    elif kind == "rtf":
        ok = data[:5] == b"{\\rtf"
    elif kind == "image":
        if mime == "image/jpeg":
            ok = data[:3] == b"\xff\xd8\xff"
        elif mime == "image/png":
            ok = data[:8] == b"\x89PNG\r\n\x1a\n"
        elif mime == "image/gif":
            ok = data[:6] in (b"GIF87a", b"GIF89a")
        elif mime == "image/webp":
            ok = data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    elif kind in ("text", "html"):
        ok = _looks_textual(data)
    if not ok:
        raise FileRejected(f"Файл «{safe_filename(name)}» повреждён или его содержимое не совпадает с расширением {ext}.")
    return Detected(kind=kind, mime=mime, ext=ext)


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


class _HTMLText(HTMLParser):
    BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _odt_text(data: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        root = ElementTree.fromstring(z.read("content.xml"))
    ns_text = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    out = []
    for el in root.iter():
        if el.tag in (f"{{{ns_text}}}p", f"{{{ns_text}}}h"):
            out.append("".join(el.itertext()))
    return "\n".join(out)


def _docx_text(data: bytes) -> str:
    import docx  # python-docx

    d = docx.Document(io.BytesIO(data))
    out = [p.text for p in d.paragraphs]
    for table in d.tables:
        for row in table.rows:
            cells = []
            for c in row.cells:
                t = c.text.strip()
                if t and (not cells or cells[-1] != t):   # объединённые ячейки повторяются
                    cells.append(t)
            if cells:
                out.append(" | ".join(cells))
    for section in d.sections:
        for p in section.header.paragraphs:
            if p.text.strip():
                out.insert(0, p.text)
    return "\n".join(out)


def _xlsx_text(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = []
    try:
        for ws in wb.worksheets:
            out.append(f"[Лист: {ws.title}]")
            for row in ws.iter_rows(values_only=True):
                vals = [str(v) for v in row if v is not None and str(v).strip()]
                if vals:
                    out.append(" | ".join(vals))
    finally:
        wb.close()
    return "\n".join(out)


def _pdf_text(data: bytes) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:  # noqa: BLE001
            raise FileRejected("PDF защищён паролем. Загрузите файл без пароля.") from e
    pages = len(reader.pages)
    out = []
    for page in reader.pages:
        try:
            out.append(page.extract_text() or "")
        except Exception:  # noqa: BLE001 - битая страница не должна ронять приём
            out.append("")
    return "\n".join(out), pages


def clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace(" ", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_text(kind: str, data: bytes) -> tuple[str, int | None]:
    """Возвращает (текст, число страниц для PDF). Для изображений текст пустой: их читает модель."""
    if kind == "pdf":
        text, pages = _pdf_text(data)
        return clean_text(text), pages
    if kind == "docx":
        return clean_text(_docx_text(data)), None
    if kind == "odt":
        return clean_text(_odt_text(data)), None
    if kind == "rtf":
        from striprtf.striprtf import rtf_to_text

        return clean_text(rtf_to_text(_decode(data), errors="ignore")), None
    if kind == "xlsx":
        return clean_text(_xlsx_text(data)), None
    if kind == "html":
        p = _HTMLText()
        p.feed(_decode(data))
        return clean_text(html.unescape("".join(p.parts))), None
    if kind == "text":
        return clean_text(_decode(data)), None
    return "", None
