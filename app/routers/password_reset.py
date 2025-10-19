# app/routers/password_reset.py
from fastapi import APIRouter, Depends, HTTPException, Body, status, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta, timezone
import bcrypt
import secrets
import logging
import os
import smtplib
from email.message import EmailMessage
import jwt  # pip install PyJWT

from app.database import get_db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/password", tags=["Password Reset (SMTP)"])

# ---------- CONFIG ----------
OTP_LIFETIME_SECONDS = 60  # ลบ OTP ใน 60 วิตามข้อกำหนด
RESET_TOKEN_TTL_MINUTES = 15

# SMTP
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "1") == "1"
SMTP_SENDER = os.getenv("SMTP_SENDER", "MonkPad <no-reply@monkpad.app>")

# JWT สำหรับ reset token
RESET_JWT_SECRET = os.getenv("RESET_JWT_SECRET", "change-me")
RESET_JWT_ALG = os.getenv("RESET_JWT_ALG", "HS256")


def _now_utc():
    return datetime.now(timezone.utc)


def _gen_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"  # 000000-999999


def _hash_code(code: str) -> str:
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _send_email_smtp(to_email: str, subject: str, html_body: str, text_body: str = ""):
    if not SMTP_HOST or not SMTP_PORT or not SMTP_SENDER:
        raise HTTPException(status_code=500, detail="SMTP is not configured")

    msg = EmailMessage()
    # แกะ display name กับอีเมลผู้ส่ง ถ้าต้องการ
    msg["From"] = SMTP_SENDER
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(text_body or " ")
    msg.add_alternative(html_body, subtype="html")

    try:
        if SMTP_USE_TLS:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                s.starttls()
                if SMTP_USER and SMTP_PASS:
                    s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
        else:
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as s:
                if SMTP_USER and SMTP_PASS:
                    s.login(SMTP_USER, SMTP_PASS)
                s.send_message(msg)
    except Exception as e:
        log.exception("SMTP send error: %s", e)
        raise HTTPException(status_code=500, detail="Failed to send email")


def _schedule_delete_otp(background: BackgroundTasks, db: Session, otp_id: int):
    """
    ลบ row OTP อัตโนมัติใน 60 วินาที โดยไม่ต้องเก็บเวลาในตาราง
    """
    def _delete_later(otp_id_inner: int):
        # ใช้ session ใหม่ต่อดีสุด แต่ตรงนี้ใช้ connection เดิมเพื่อความง่าย
        try:
            db.execute(text('DELETE FROM "password_resets" WHERE id = :id'), {"id": otp_id_inner})
            db.commit()
        except Exception as e:
            db.rollback()
            log.exception("Failed to delete OTP id=%s: %s", otp_id_inner, e)

    background.add_task(lambda: (_delete_later(otp_id)) , )


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


# =======================================================
# POST /password/forgot -> ขอรหัส OTP ส่งไปอีเมล (SMTP)
# Body: { "email": "me@example.com" }
# ถ้าไม่พบอีเมล -> 404 เพื่อให้ front แจ้งเตือนได้ชัดเจน (ตามข้อ 2)
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
        # เปลี่ยนจากตอบ 200 เสมอ -> เป็น 404 เพื่อ "แจ้งเตือนและไม่ทำอะไร"
        raise HTTPException(status_code=404, detail="email not registered")

    uid = user_row._mapping["id"]

    # gen code + insert (ตารางมีแค่ id, user_id, otp_hash)
    code = _gen_otp_code()
    code_hash = _hash_code(code)

    try:
        result = db.execute(
            text('INSERT INTO "password_resets" (user_id, otp_hash) VALUES (:uid, :h) RETURNING id'),
            {"uid": uid, "h": code_hash},
        )
        otp_id = result.fetchone()[0]
        db.commit()
    except Exception as e:
        db.rollback()
        log.exception("Failed to insert password_resets: %s", e)
        raise HTTPException(status_code=500, detail="Failed to start password reset")

    # ตั้ง task ลบแถวนี้ใน 60 วินาที
    if background:
        background.add_task(_del_after, db, otp_id)
    else:
        _schedule_delete_otp(background, db, otp_id)  # เผื่อบางกรณี

    # ส่งอีเมล
    subject = "Your MonkPad password reset code"
    text_body = (
        f"Hi {user_row._mapping['username']},\n\n"
        f"Your password reset code is: {code}\n"
        f"This code will be valid for about {OTP_LIFETIME_SECONDS} seconds.\n\n"
        "If you didn’t request this, you can ignore this email."
    )
    html_body = f"""
    <p>Hi <b>{user_row._mapping['username']}</b>,</p>
    <p>Your password reset code is:</p>
    <h2 style="letter-spacing:3px; font-size: 24px;">{code}</h2>
    <p>This code will be valid for about <b>{OTP_LIFETIME_SECONDS} seconds</b>.</p>
    <p>If you didn’t request this, you can safely ignore this email.</p>
    """
    _send_email_smtp(email, subject, html_body, text_body)

    return {"message": "OTP sent"}


def _del_after(db: Session, otp_id: int):
    import time
    time.sleep(OTP_LIFETIME_SECONDS)
    try:
        db.execute(text('DELETE FROM "password_resets" WHERE id = :id'), {"id": otp_id})
        db.commit()
    except Exception as e:
        db.rollback()
        log.exception("Failed to auto-delete OTP id=%s: %s", otp_id, e)


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

    # ดึง OTP ล่าสุด (ไม่มี expires column -> ถ้าโดน auto-delete แล้ว จะไม่เจอเอง)
    otp_row = db.execute(
        text('SELECT id, otp_hash FROM "password_resets" WHERE user_id = :uid ORDER BY id DESC LIMIT 1'),
        {"uid": uid},
    ).fetchone()

    if not otp_row:
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    if not bcrypt.checkpw(code.encode("utf-8"), otp_row._mapping["otp_hash"].encode("utf-8")):
        raise HTTPException(status_code=400, detail="Invalid or expired code")

    # ผ่าน -> ออก reset_token และลบ OTP เพื่อปิดใช้ซ้ำ
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
        log.exception("Failed to set new password: %s", e)
        raise HTTPException(status_code=500, detail="Failed to reset password")
