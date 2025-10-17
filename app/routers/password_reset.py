# app/routers/password_reset.py
from fastapi import APIRouter, Depends, HTTPException, Body, status
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import smtplib
import bcrypt
import secrets
import logging
import os

from app.database import get_db

log = logging.getLogger(__name__)
router = APIRouter(prefix="/password", tags=["Password Reset"])

# ---------- Email (SMTP) ----------
SMTP_HOST   = os.getenv("SMTP_HOST")
SMTP_PORT   = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER   = os.getenv("SMTP_USER")
SMTP_PASS   = os.getenv("SMTP_PASS")
SMTP_SENDER = os.getenv("SMTP_SENDER", SMTP_USER)

def _send_email_smtp(to_email: str, subject: str, html_body: str, text_body: str = None):
    if not all([SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_SENDER]):
        log.error("SMTP env not configured")
        raise HTTPException(status_code=500, detail="Email service not configured")

    msg = EmailMessage()
    msg["From"] = SMTP_SENDER
    msg["To"] = to_email
    msg["Subject"] = subject
    if text_body:
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")
    else:
        msg.set_content(html_body, subtype="html")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
    except Exception as e:
        log.exception("Failed to send email: %s", e)
        raise HTTPException(status_code=500, detail="Failed to send email")

# ---------- OTP helpers ----------
OTP_TTL_MINUTES = 10
OTP_MIN_INTERVAL_SECONDS = 60  # ขอใหม่ได้ถี่สุดทุก 60 วินาที

def _now_utc():
    return datetime.now(timezone.utc)

def _gen_otp_code() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"  # 000000-999999

def _hash_code(code: str) -> str:
    return bcrypt.hashpw(code.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

# =======================================================
# POST /password/forgot  -> ขอรหัส OTP ส่งไปอีเมล
# Body: { "email": "me@example.com" }
# =======================================================
@router.post("/forgot", status_code=status.HTTP_200_OK)
def forgot_password_request(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    email = (payload.get("email") or "").strip().lower()
    if not email:
        raise HTTPException(status_code=422, detail="email is required")

    # หา user ตามอีเมล
    user_row = db.execute(
        text('SELECT id, email, username FROM "users" WHERE email = :e'),
        {"e": email}
    ).fetchone()

    # เพื่อความปลอดภัย ตอบ 200 เสมอ (ไม่เปิดเผยว่ามีอีเมลหรือไม่)
    if not user_row:
        return {"message": "If the email exists, an OTP has been sent."}

    uid = user_row._mapping["id"]

    # rate-limit: ต้องห่างอย่างน้อย OTP_MIN_INTERVAL_SECONDS จากคำขอล่าสุด
    last_req = db.execute(
        text('SELECT created_at FROM "password_resets" WHERE user_id = :uid ORDER BY id DESC LIMIT 1'),
        {"uid": uid}
    ).fetchone()
    if last_req:
        last_created = last_req._mapping["created_at"]
        if (_now_utc() - last_created).total_seconds() < OTP_MIN_INTERVAL_SECONDS:
            raise HTTPException(status_code=429, detail="Please wait a bit before requesting another code")

    # gen code + hash + expiry
    code = _gen_otp_code()
    code_hash = _hash_code(code)
    expires_at = _now_utc() + timedelta(minutes=OTP_TTL_MINUTES)

    try:
        db.execute(
            text('''
                INSERT INTO "password_resets" (user_id, code_hash, expires_at, request_ip)
                VALUES (:uid, :ch, :exp, :ip)
            '''),
            {"uid": uid, "ch": code_hash, "exp": expires_at, "ip": None}
        )
        db.commit()
    except Exception as e:
        db.rollback()
        log.exception("Failed to insert password_resets: %s", e)
        raise HTTPException(status_code=500, detail="Failed to start password reset")

    # ส่งอีเมล
    subject = "Your Monkpad password reset code"
    text_body = (
        f"Hi {user_row._mapping['username']},\n\n"
        f"Your password reset code is: {code}\n"
        f"This code expires in {OTP_TTL_MINUTES} minutes.\n\n"
        "If you didn’t request this, you can ignore this email."
    )
    html_body = f"""
    <p>Hi <b>{user_row._mapping['username']}</b>,</p>
    <p>Your password reset code is:</p>
    <h2 style="letter-spacing:3px;">{code}</h2>
    <p>This code expires in <b>{OTP_TTL_MINUTES} minutes</b>.</p>
    <p>If you didn’t request this, you can safely ignore this email.</p>
    """

    _send_email_smtp(email, subject, html_body, text_body)
    return {"message": "If the email exists, an OTP has been sent."}

# =======================================================
# POST /password/reset  -> ยืนยัน OTP + ตั้งรหัสใหม่
# Body: { "email": "...", "code": "123456", "new_password": "NewPass123!" }
# =======================================================
@router.post("/reset", status_code=status.HTTP_200_OK)
def reset_password_with_otp(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
):
    email = (payload.get("email") or "").strip().lower()
    code  = (payload.get("code") or "").strip()
    new_password = payload.get("new_password") or ""

    if not email or not code or not new_password:
        raise HTTPException(status_code=422, detail="email, code and new_password are required")
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")

    # หา user
    user_row = db.execute(
        text('SELECT id FROM "users" WHERE email = :e'),
        {"e": email}
    ).fetchone()
    if not user_row:
        # ซ่อนรายละเอียด
        raise HTTPException(status_code=400, detail="Invalid code or expired")

    uid = user_row._mapping["id"]

    # ดึง OTP ล่าสุดที่ยังไม่หมดอายุและยังไม่ใช้
    otp_row = db.execute(
        text('''
            SELECT id, code_hash, expires_at, used_at
            FROM "password_resets"
            WHERE user_id = :uid
              AND used_at IS NULL
              AND expires_at > NOW()
            ORDER BY id DESC
            LIMIT 1
        '''),
        {"uid": uid}
    ).fetchone()

    if not otp_row:
        raise HTTPException(status_code=400, detail="Invalid code or expired")

    # ตรวจรหัส
    if not bcrypt.checkpw(code.encode("utf-8"), otp_row._mapping["code_hash"].encode("utf-8")):
        raise HTTPException(status_code=400, detail="Invalid code or expired")

    # อัปเดตรหัสผ่านใหม่
    new_hash = bcrypt.hashpw(new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    try:
        # mark used ของตัวล่าสุด
        db.execute(
            text('UPDATE "password_resets" SET used_at = NOW() WHERE id = :id'),
            {"id": otp_row._mapping["id"]}
        )
        # อัปเดต user
        db.execute(
            text('UPDATE "users" SET password = :p WHERE id = :uid'),
            {"p": new_hash, "uid": uid}
        )
        # (ออปชัน) ปิด OTP อื่น ๆ ที่ยังค้างของ user นี้
        db.execute(
            text('UPDATE "password_resets" SET used_at = NOW() WHERE user_id = :uid AND used_at IS NULL'),
            {"uid": uid}
        )

        db.commit()
        return {"message": "Password has been reset successfully"}
    except Exception as e:
        db.rollback()
        log.exception("Failed to reset password: %s", e)
        raise HTTPException(status_code=500, detail="Failed to reset password")
