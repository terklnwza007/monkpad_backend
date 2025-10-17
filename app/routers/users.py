# app/routers/users.py
from fastapi import APIRouter, Depends, HTTPException, Body, status
from sqlalchemy.orm import Session
from sqlalchemy import text
import bcrypt
import logging
import re

from app.models import User  # เผื่อที่อื่น import ใช้งาน
from app.routers.auth import require_user
from app.database import get_db

log = logging.getLogger(__name__)

router = APIRouter(prefix="/users", tags=["Users"])


# ----------------- helpers -----------------
def _uid_of(current_user):
    """
    รองรับได้ทั้ง object ที่มี attr id / user_id หรือ dict
    """
    if current_user is None:
        return None
    return (
        getattr(current_user, "id", None)
        or getattr(current_user, "user_id", None)
        or (current_user.get("id") if isinstance(current_user, dict) else None)
        or (current_user.get("user_id") if isinstance(current_user, dict) else None)
    )

def _validate_username(name: str):
    if not name or not (3 <= len(name) <= 24):
        raise HTTPException(status_code=422, detail="username length must be 3-24")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
        raise HTTPException(status_code=422, detail="username can contain only letters, numbers, _ . -")

def _validate_email(email: str):
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=422, detail="invalid email format")

def _validate_new_password(pw: str):
    if not pw or len(pw) < 8:
        raise HTTPException(status_code=422, detail="password must be at least 8 characters")

# =======================================================
# สมัครสมาชิก (ไม่ต้อง auth)
# ================= ตัวอย่าง JSON สมัคร =================
"""
{
    "username": "koonteirk",
    "password": "Teirk@089404xxxx",
    "email": "tanawat.pxx@ku.th"
}
"""
# =======================================================
@router.post("/add/", status_code=status.HTTP_201_CREATED)
def create_user(user: dict = Body(...), db: Session = Depends(get_db)):
    username = (user.get("username") or "").strip()
    email = (user.get("email") or "").strip()
    password = user.get("password") or ""

    if not username or not email or not password:
        raise HTTPException(status_code=422, detail="username, email, password are required")

    _validate_username(username)
    _validate_email(email)
    _validate_new_password(password)

    # duplicate checks
    if db.execute(text('SELECT 1 FROM "users" WHERE username = :u'), {"u": username}).fetchone():
        raise HTTPException(status_code=400, detail="Username already registered")
    if db.execute(text('SELECT 1 FROM "users" WHERE email = :e'), {"e": email}).fetchone():
        raise HTTPException(status_code=400, detail="Email already registered")

    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    try:
        # insert user
        row = db.execute(
            text('INSERT INTO "users" (username, password, email) VALUES (:u, :p, :e) RETURNING id'),
            {"u": username, "p": hashed_password, "e": email}
        ).fetchone()
        uid = row._mapping["id"]

        # seed แท็กเริ่มต้น (กันซ้ำด้วย NOT EXISTS)
        db.execute(
            text('''
                INSERT INTO "tags" (user_id, tag, type, value)
                SELECT :uid, :t, :ty, 0
                WHERE NOT EXISTS (SELECT 1 FROM "tags" WHERE user_id = :uid AND tag = :t)
            '''), {"uid": uid, "t": "รายรับอื่นๆ", "ty": "income"}
        )
        db.execute(
            text('''
                INSERT INTO "tags" (user_id, tag, type, value)
                SELECT :uid, :t, :ty, 0
                WHERE NOT EXISTS (SELECT 1 FROM "tags" WHERE user_id = :uid AND tag = :t)
            '''), {"uid": uid, "t": "รายจ่ายอื่นๆ", "ty": "expense"}
        )

        db.commit()
        return {"message": "User created successfully", "user_id": uid}

    except Exception as e:
        db.rollback()
        log.exception("Failed to create user and default tags: %s", e)
        raise HTTPException(status_code=500, detail="Failed to create user and default tags")

# =======================================================
# อ่าน users (ต้องล็อกอิน)
# =======================================================
@router.get("/all/", dependencies=[Depends(require_user)])
def read_users(db: Session = Depends(get_db)):
    rows = db.execute(text('SELECT id, username, email FROM "users"')).fetchall()
    return [dict(r._mapping) for r in rows]

@router.get("/{user_id}", dependencies=[Depends(require_user)])
def read_user(user_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text('SELECT id, username, email FROM "users" WHERE id = :id'),
        {"id": user_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(row._mapping)

# =======================================================
# โปรไฟล์ของตัวเอง (ต้องล็อกอิน)
# =======================================================
@router.get("/me", dependencies=[Depends(require_user)])
def read_me(db: Session = Depends(get_db), current_user = Depends(require_user)):
    uid = _uid_of(current_user)
    row = db.execute(
        text('SELECT id, username, email FROM "users" WHERE id = :id'),
        {"id": uid}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(row._mapping)

# =======================================================
# เปลี่ยนรหัสผ่านของตัวเอง
# Body: { "old_password": "...", "new_password": "..." }
# =======================================================
@router.patch("/me/password", status_code=status.HTTP_200_OK)
def change_my_password(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user = Depends(require_user),
):
    uid = _uid_of(current_user)
    old_pw = payload.get("old_password")
    new_pw = payload.get("new_password")

    if not old_pw or not new_pw:
        raise HTTPException(status_code=422, detail="old_password and new_password are required")
    _validate_new_password(new_pw)

    row = db.execute(text('SELECT password FROM "users" WHERE id = :id'), {"id": uid}).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    current_hash = row._mapping["password"]

    if not bcrypt.checkpw(old_pw.encode("utf-8"), current_hash.encode("utf-8")):
        raise HTTPException(status_code=400, detail="old_password is incorrect")

    if bcrypt.checkpw(new_pw.encode("utf-8"), current_hash.encode("utf-8")):
        raise HTTPException(status_code=400, detail="new_password must be different from old password")

    new_hash = bcrypt.hashpw(new_pw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    try:
        db.execute(text('UPDATE "users" SET password = :p WHERE id = :id'), {"p": new_hash, "id": uid})
        db.commit()
        return {"message": "Password updated"}
    except Exception as e:
        db.rollback()
        log.exception("Failed to change password: %s", e)
        raise HTTPException(status_code=500, detail="Failed to change password")

# =======================================================
# เปลี่ยน username ของตัวเอง
# Body: { "new_username": "...", "password": "..." }
# =======================================================
@router.patch("/me/username", status_code=status.HTTP_200_OK)
def change_my_username(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user = Depends(require_user),
):
    uid = _uid_of(current_user)
    new_username = (payload.get("new_username") or "").strip()
    password = payload.get("password")

    if not new_username or not password:
        raise HTTPException(status_code=422, detail="new_username and password are required")
    _validate_username(new_username)

    row_pwd = db.execute(text('SELECT password FROM "users" WHERE id = :id'), {"id": uid}).fetchone()
    if not row_pwd:
        raise HTTPException(status_code=404, detail="User not found")
    if not bcrypt.checkpw(password.encode("utf-8"), row_pwd._mapping["password"].encode("utf-8")):
        raise HTTPException(status_code=400, detail="password is incorrect")

    dup = db.execute(
        text('SELECT 1 FROM "users" WHERE username = :u AND id <> :id'),
        {"u": new_username, "id": uid}
    ).fetchone()
    if dup:
        raise HTTPException(status_code=400, detail="Username already taken")

    try:
        db.execute(text('UPDATE "users" SET username = :u WHERE id = :id'), {"u": new_username, "id": uid})
        db.commit()
        return {"message": "Username updated", "username": new_username}
    except Exception as e:
        db.rollback()
        log.exception("Failed to change username: %s", e)
        raise HTTPException(status_code=500, detail="Failed to change username")

# =======================================================
# เปลี่ยนอีเมลของตัวเอง
# Body: { "new_email": "...", "password": "..." }
# =======================================================
@router.patch("/me/email", status_code=status.HTTP_200_OK)
def change_my_email(
    payload: dict = Body(...),
    db: Session = Depends(get_db),
    current_user = Depends(require_user),
):
    uid = _uid_of(current_user)
    new_email = (payload.get("new_email") or "").strip()
    password = payload.get("password")

    if not new_email or not password:
        raise HTTPException(status_code=422, detail="new_email and password are required")
    _validate_email(new_email)

    row_pwd = db.execute(text('SELECT password FROM "users" WHERE id = :id'), {"id": uid}).fetchone()
    if not row_pwd:
        raise HTTPException(status_code=404, detail="User not found")
    if not bcrypt.checkpw(password.encode("utf-8"), row_pwd._mapping["password"].encode("utf-8")):
        raise HTTPException(status_code=400, detail="password is incorrect")

    dup = db.execute(
        text('SELECT 1 FROM "users" WHERE email = :e AND id <> :id'),
        {"e": new_email, "id": uid}
    ).fetchone()
    if dup:
        raise HTTPException(status_code=400, detail="Email already registered")

    try:
        db.execute(text('UPDATE "users" SET email = :e WHERE id = :id'), {"e": new_email, "id": uid})
        db.commit()
        return {"message": "Email updated", "email": new_email}
    except Exception as e:
        db.rollback()
        log.exception("Failed to change email: %s", e)
        raise HTTPException(status_code=500, detail="Failed to change email")
