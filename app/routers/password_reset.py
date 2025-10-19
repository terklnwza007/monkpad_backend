# app/routers/password_reset.py
from fastapi import APIRouter, Depends, HTTPException, Body, status, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta, timezone
import bcrypt
import secrets
import logging
import os
import jwt  # pip install PyJWT
import resend  # pip install resend

from app.database import get_db


import re

_FROM_RE = re.compile(
    r"^(?:[^<>@]+ <[^<>\s@]+@[^<>\s@]+\.[^<>\s@]+>|[^<>\s@]+@[^<>\s@]+\.[^<>\s@]+)$"
)

def _clean_from(value: str) -> str:
    # ตัดช่องว่าง/บรรทัดใหม่/quote ที่หลงมา
    v = (value or "").strip().strip("'").strip('"')
    # ตัดช่องว่างก่อน '>' ถ้ามี
    v = re.sub(r"\s+>", ">", v)
    return v

def _valid_from_or_fallback(env_from: str) -> str:
    v = _clean_from(env_from)
    if not _FROM_RE.match(v):
        # fallback ปลอดภัยสุดของ Resend
        return "onboarding@resend.dev"
    return v

log = logging.getLogger(__name__)
router = APIRouter(prefix="/password", tags=["Password Reset (Resend)"])

# ---------- CONFIG ----------
OTP_LIFETIME_SECONDS = 60           # อายุ OTP ~60s (จะลบแถวอัตโนมัติ)
RESET_TOKEN_TTL_MINUTES = 15        # อายุ reset token

# Resend
RESEND_API_KEY = os.getenv("RESEND_API_KEY")  # ต้องมี
SMTP_SENDER = os.getenv("SMTP_SENDER")  # sender ของ Resend

# JWT สำหรับ reset token
RESET_JWT_SECRET = os.getenv("RESET_JWT_SECRET")
RESET_JWT_ALG = os.getenv("RESET_JWT_ALG")


# ---------- Helpers ----------
def _now_utc():
    return datetime.now(timezone.utc)


def _gen_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"  


def _hash_code(code: str) -> str:
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _init_resend():
    if not RESEND_API_KEY:
        raise HTTPException(status_code=500, detail="RESEND_API_KEY is not configured")
    resend.api_key = RESEND_API_KEY


def _send_email_resend(to_email: str, subject: str, html_body: str, text_body: str = ""):
    _init_resend()
    from_addr = _valid_from_or_fallback(os.getenv("SMTP_SENDER"))
    try:
        resend.Emails.send({
            "from": from_addr,
            "to": to_email,
            "subject": subject,
            "html": html_body,
        })
    except Exception as e:
        log.exception("Resend API error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to send email")



def _mint_reset_token(user_id: int):
    payload = {
        "sub": str(user_id),
        "typ": "reset",
        "exp": _now_utc() + timedelta(minutes=RESET_TOKEN_TTL_MINUTES),
        "iat": _now_utc(),
    }
    return jwt.encode(payload, RESET_JWT_SECRET, algorithm=RESET_JWT_ALG)


def _parse_reset_token(token: str) -> int:
    try:
        data = jwt.decode(token, RESET_JWT_SECRET, algorithms=[RESET_JWT_ALG])
        if data.get("typ") != "reset":
            raise HTTPException(status_code=400, detail="Invalid reset token")
        return int(data["sub"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=400, detail="Reset token expired")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid reset token")


def _del_after(db: Session, otp_id: int):
    """ลบ row OTP อัตโนมัติใน ~60 วินาที"""
    import time
    time.sleep(OTP_LIFETIME_SECONDS)
    try:
        db.execute(text('DELETE FROM "password_resets" WHERE id = :id'), {"id": otp_id})
        db.commit()
    except Exception as e:
        db.rollback()
        log.exception("Failed to auto-delete OTP id=%s: %s", otp_id, e)


# =======================================================
# POST /password/forgot -> ขอรหัส OTP ส่งไปอีเมล (Resend)
# Body: { "email": "me@example.com" }
# ถ้าไม่พบอีเมล -> 404
# ลอจิก: สร้างโค้ด -> ส่งเมล (สำเร็จเท่านั้น) -> INSERT -> schedule ลบ
# =======================================================
@router.post("/forgot", status_code=status.HTTP_200_OK)
def forgot_password_request(payload: dict = Body(...),
                            background: BackgroundTasks = None,
                            db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=422, detail="email is required")

    user_row = db.execute(
        text('SELECT id, email, username FROM "users" WHERE email = :e'),
        {"e": email},
    ).fetchone()

    if not user_row:
        raise HTTPException(status_code=404, detail="email not registered")

    uid = user_row._mapping["id"]
    username = user_row._mapping.get("username") or email.split("@")[0]

    # 1) สร้างรหัส (แต่ยังไม่บันทึก)
    code = _gen_otp_code()
    code_hash = _hash_code(code)

    # 2) ส่งอีเมลก่อน — ถ้าล้มเหลวจะไม่บันทึก OTP
    subject = "Your MonkPad password reset code"
    text_body = (
        f"Hi {username},\n\n"
        f"Your password reset code is: {code}\n"
        f"This code will be valid for about {OTP_LIFETIME_SECONDS} seconds.\n\n"
        "If you didn’t request this, you can ignore this email."
    )
    html_body = f"""
    <div style="font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; color:#111827">
      <p>Hi <b>{username}</b>,</p>
      <p>Your password reset code is</p>
      <div style="margin:12px 0 16px; font-size:28px; letter-spacing:6px; font-weight:800;">{code}</div>
      <p>This code will be valid for about <b>{OTP_LIFETIME_SECONDS} seconds</b>.</p>
      <p style="color:#6b7280; font-size:12px;">If you didn’t request this, you can safely ignore this email.</p>
    </div>
    """
    _send_email_resend(email, subject, html_body, text_body)

    # 3) ส่งสำเร็จแล้ว -> INSERT OTP
    otp_id = None
    try:
        result = db.execute(
            text('INSERT INTO "password_resets" (user_id, otp_hash) VALUES (:uid, :h) RETURNING id'),
            {"uid": uid, "h": code_hash},
        )
        otp_id = result.fetchone()[0]
        db.commit()
    except Exception as e:
        # ล้มเหลวรอบแรก: ลอง retry 1 ครั้ง (กันเคส race/connection)
        log.warning("Insert OTP failed once, retrying: %s", e)
        db.rollback()
        try:
            result = db.execute(
                text('INSERT INTO "password_resets" (user_id, otp_hash) VALUES (:uid, :h) RETURNING id'),
                {"uid": uid, "h": code_hash},
            )
            otp_id = result.fetchone()[0]
            db.commit()
        except Exception as e2:
            db.rollback()
            log.exception("Failed to insert password_resets after resend succeeded: %s", e2)
            # ณ จุดนี้ผู้ใช้ได้รับรหัสไปแล้วแต่ DB ไม่รู้จัก -> ให้ผู้ใช้กดขอรหัสใหม่
            raise HTTPException(status_code=500, detail="Failed to save OTP, please request a new code")

    # 4) ตั้ง task ลบแถวนี้ภายใน ~60s
    if background:
        background.add_task(_del_after, db, otp_id)

    return {"message": "OTP sent"}


# =======================================================
# POST /password/verify -> ตรวจ OTP และออก reset_token
# Body: { "email": "...", "code": "123456" }
# ถ้าใช้ได้: คืน { reset_token }
# =======================================================
@router.post("/verify", status_code=status.HTTP_200_OK)
def verify_otp(payload: dict = Body(...), db: Session = Depends(get_db)):
    email = (payload.get("email") or "").strip().lower()
    code = (payload.get("code") or "").strip()
    if not email or not code:
        raise HTTPException(status_code=422, detail="email and code are required")

    user_row = db.execute(
        text('SELECT id FROM "users" WHERE email = :e'),
        {"e": email},
    ).fetchone()
    if not user_row:
        raise HTTPException(status_code=404, detail="email not registered")

    uid = user_row._mapping["id"]

    # ดึง OTP ล่าสุด (หากถูก auto-delete ไปแล้วจะไม่พบ)
    otp_row = db.execute(
        text('SELECT id, otp_hash FROM "password_resets" WHERE user_id = :uid ORDER BY id DESC LIMIT 1'),
        {"uid": uid},
    ).fetchone()

    if not otp_row:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    if not bcrypt.checkpw(code.encode("utf-8"), otp_row._mapping["otp_hash"].encode("utf-8")):
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    # ผ่าน -> ออก reset_token และลบ OTP ป้องกันใช้ซ้ำ
    token = _mint_reset_token(uid)
    try:
        db.execute(text('DELETE FROM "password_resets" WHERE id = :id'), {"id": otp_row._mapping["id"]})
        db.commit()
    except Exception as e:
        db.rollback()
        log.exception("Failed to delete OTP after verify: %s", e)

    return {"reset_token": token, "expires_in_minutes": RESET_TOKEN_TTL_MINUTES}


# =======================================================
# POST /password/set -> ใช้ reset_token ตั้งรหัสใหม่
# Body: { "reset_token": "...", "new_password": "NewPass123!" }
# =======================================================
@router.post("/set", status_code=status.HTTP_200_OK)
def set_new_password(payload: dict = Body(...), db: Session = Depends(get_db)):
    reset_token = payload.get("reset_token") or ""
    new_password = payload.get("new_password") or ""

    if not reset_token or not new_password:
        raise HTTPException(status_code=422, detail="reset_token and new_password are required")
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")

    uid = _parse_reset_token(reset_token)

    new_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    try:
        db.execute(text('UPDATE "users" SET password = :p WHERE id = :uid'),
                   {"p": new_hash, "uid": uid})
        db.commit()
        return {"message": "Password has been reset successfully"}
    except Exception as e:
        db.rollback()
        log.exception("Failed to reset password: %s", e)
        raise HTTPException(status_code=500, detail="Failed to reset password")
