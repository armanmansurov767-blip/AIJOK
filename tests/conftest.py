import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import llm
from app.config import Settings
from app.db import now
from app.main import create_app
from app.security import hash_password

ADMIN_PASSWORD = "Admin-Pass-2026"
STAFF_PASSWORD = "Staff-Pass-2026"
H = {"X-Requested-With": "DocAgent"}


def F(value, confidence="high"):
    return {"value": value, "confidence": confidence}


GOOD = {
    "doc_kind": "заявление",
    "type": "Пересдача экзамена",
    "type_confidence": "high",
    "fields": {
        "fio": F("Садыков Нурлан Ерболатович"), "group": F("ИС-24/2"), "course": F("2"),
        "purpose": F("в связи с совпадением двух экзаменов"), "date": F("09.11.2026"), "sign": F("есть"),
    },
    "summary": "Студент просит пересдачу экзамена.",
    "warnings": [],
}

SAMPLE_TEXT = ("Декану факультета\nот студента группы ИС-24/2, 2 курса\nСадыкова Нурлана Ерболатовича\n\nЗАЯВЛЕНИЕ\n"
               "Прошу разрешить мне пересдачу экзамена по дисциплине «Операционные системы» в связи с совпадением "
               "двух экзаменов по расписанию.\n\nДата: 09.11.2026        Подпись: Н. Садыков")


class FakeReader:
    def __init__(self):
        self.calls = []
        self.response = GOOD
        self.error = None

    def __call__(self, settings, docs, text_input):
        self.calls.append({"docs": docs, "text": text_input})
        if self.error:
            raise self.error
        r = self.response
        return r(docs, text_input) if callable(r) else r


@pytest.fixture
def reader(monkeypatch):
    fake = FakeReader()
    monkeypatch.setattr(llm, "read_documents", fake)
    return fake


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", ai_enabled=True, sync_processing=True,
                    public_url="http://test", smtp_host="", smtp_from="", org_name="Тестовый колледж")


def _add_user(db, login, password, role):
    with db.tx() as con:
        con.execute("INSERT INTO users(login, name, password_hash, role, created_at) VALUES (?, ?, ?, ?, ?)",
                    (login, login.capitalize(), hash_password(password), role, now()))


@pytest.fixture
def app(settings, reader):
    a = create_app(settings)
    _add_user(a.state.db, "admin", ADMIN_PASSWORD, "admin")
    _add_user(a.state.db, "staff", STAFF_PASSWORD, "staff")
    return a


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def staff(app):
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"login": "staff", "password": STAFF_PASSWORD}, headers=H)
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture
def admin(app):
    with TestClient(app) as c:
        r = c.post("/api/auth/login", json={"login": "admin", "password": ADMIN_PASSWORD}, headers=H)
        assert r.status_code == 200, r.text
        yield c


def submit(client, text="", files=None, email="", name="", consent="on"):
    data = {"text": text, "email": email, "name": name, "consent": consent}
    return client.post("/api/applications", data=data, files=files or [])


def app_id_from(client_or_app, token):
    db = client_or_app.state.db
    return db.one("SELECT id FROM applications WHERE public_token = ?", (token,))["id"]


def make_docx(text):
    import docx

    d = docx.Document()
    for line in text.split("\n"):
        d.add_paragraph(line)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def make_odt(text):
    buf = io.BytesIO()
    paras = "".join(f"<text:p>{line}</text:p>" for line in text.split("\n"))
    content = ('<?xml version="1.0" encoding="UTF-8"?><office:document-content '
               'xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
               'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"><office:body><office:text>'
               f"{paras}</office:text></office:body></office:document-content>")
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text", compress_type=zipfile.ZIP_STORED)
        z.writestr("content.xml", content)
    return buf.getvalue()


def make_pdf(text="Zayavlenie test PDF"):
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET".encode()
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(out)


PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
           b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")
