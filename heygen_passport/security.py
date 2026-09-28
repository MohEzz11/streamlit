"""Password hashing and upload validation (standard library only)."""

import hashlib
import hmac
import secrets
import string

from . import config

PBKDF2_ITERATIONS = 390_000


class ValidationError(ValueError):
    """Raised for invalid user input. Message is safe to show to users."""


def hash_password(password):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password, stored):
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), hash_hex)
    except (ValueError, AttributeError):
        return False


def check_password_strength(password):
    if len(password) < 10:
        raise ValidationError("Password must be at least 10 characters.")
    classes = sum([any(c.islower() for c in password), any(c.isupper() for c in password),
                   any(c.isdigit() for c in password),
                   any(not c.isalnum() for c in password)])
    if classes < 3:
        raise ValidationError("Password must mix at least three of: lowercase, "
                              "uppercase, digits, symbols.")


def generate_password(length=14):
    alphabet = string.ascii_letters + string.digits + "!@#%*-_"
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        try:
            check_password_strength(pw)
            return pw
        except ValidationError:
            continue


_SIGNATURES = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"%PDF-", "application/pdf"),
]


def sniff_upload(data, images_only=False):
    """Return a safe MIME type based on file contents, or raise."""
    if not data:
        raise ValidationError("The file is empty.")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise ValidationError(f"File is too large (max {config.MAX_UPLOAD_BYTES // (1024*1024)} MB).")
    mime = None
    for sig, m in _SIGNATURES:
        if data.startswith(sig):
            mime = m
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        mime = "image/webp"
    if mime is None:
        raise ValidationError("Only JPEG, PNG, WebP images or PDF documents are accepted.")
    if images_only and not mime.startswith("image/"):
        raise ValidationError("Please upload an image (JPEG, PNG or WebP).")
    return mime


def clean_text(value, field, max_len=2000, required=False):
    value = (value or "").strip()
    if required and not value:
        raise ValidationError(f"{field} is required.")
    if len(value) > max_len:
        raise ValidationError(f"{field} must be at most {max_len} characters.")
    # Strip control characters other than newline/tab.
    value = "".join(ch for ch in value if ch in "\n\t" or ord(ch) >= 32)
    return value or None
