"""Senhas (Argon2), sessão (JWT em cookie HttpOnly), MFA (TOTP) e criptografia de segredos em repouso."""
import base64
import hashlib
import io
import re
import secrets
from datetime import datetime, timedelta, timezone

import jwt
import pyotp
import qrcode
import qrcode.image.svg
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from .config import settings

COOKIE = "docops_session"
ENC_PREFIX = "enc:v1:"
_ph = PasswordHasher()


def _fernet() -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_secret(value: str | None) -> str | None:
    if not value:
        return value
    if value.startswith(ENC_PREFIX):
        return value
    return ENC_PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_secret(value: str | None) -> str | None:
    if not value or not value.startswith(ENC_PREFIX):
        return value
    try:
        return _fernet().decrypt(value[len(ENC_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None


def hash_password(p: str) -> str:
    return _ph.hash(p)


def verify_password(h: str, p: str) -> bool:
    try:
        return _ph.verify(h, p)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_problems(p: str) -> list[str]:
    out = []
    if len(p) < settings.min_password_length:
        out.append(f"mínimo de {settings.min_password_length} caracteres")
    if not re.search(r"[A-Za-z]", p):
        out.append("ao menos uma letra")
    if not re.search(r"\d", p):
        out.append("ao menos um número")
    if not re.search(r"[^A-Za-z0-9]", p):
        out.append("ao menos um símbolo")
    return out


def temp_password() -> str:
    return secrets.token_urlsafe(12) + "9!"


def make_session(user_id: int, version: int) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(user_id), "v": version, "iat": now, "exp": now + timedelta(hours=settings.session_hours)},
                      settings.secret_key, algorithm="HS256")


def read_session(token: str) -> tuple[int, int] | None:
    try:
        d = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        return int(d["sub"]), int(d.get("v", 0))
    except (jwt.PyJWTError, KeyError, ValueError):
        return None


def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_ok(secret: str, code: str) -> bool:
    raw = decrypt_secret(secret)
    return bool(raw) and pyotp.TOTP(raw).verify((code or "").strip().replace(" ", ""), valid_window=1)


def totp_qr_svg(secret: str, email: str) -> tuple[str, str]:
    uri = pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name=settings.app_name)
    img = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return uri, "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()
