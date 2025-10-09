# app/routers/users.py
from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
import bcrypt
from app.routers.auth import require_user
from app.database import get_db

router = APIRouter(prefix="/users", tags=["Users"])

# ================= ตัวอย่าง JSON =================
"""
{
    "username": "koonteirk",
    "password": "Teirk@089404xxxx",
    "email": "tanawat.pxx@ku.th"
}
"""
# ===============================================
@router.post("/add/")
def create_user(user: dict = Body(...), db: Session = Depends(get_db)):
    username = user.get("username")
    email = user.get("email")
    password = user.get("password")

    # ตรวจค่าว่างแบบง่าย ๆ (เพราะไม่ใช้ Pydantic)
    if not username or not email or not password:
        raise HTTPException(status_code=422, detail="username, email, password are required")

    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    # duplicate checks
    if db.execute(text('SELECT id FROM "users" WHERE username = :u'), {"u": username}).fetchone():
        raise HTTPException(status_code=400, detail="Username already registered")
    if db.execute(text('SELECT id FROM "users" WHERE email = :e'), {"e": email}).fetchone():
        raise HTTPException(status_code=400, detail="Email already registered")

    # ใช้ทรานแซคชันเดียว: สร้าง user และ seed แท็กเริ่มต้น
    try:
        with db.begin():
            # 1) สร้างผู้ใช้ใหม่ + คืน id
            row = db.execute(
                text('INSERT INTO "users" (username, password, email) VALUES (:u, :p, :e) RETURNING id'),
                {"u": username, "p": hashed_password, "e": email}
            ).fetchone()
            uid = row._mapping["id"]

            # 2) สร้างแท็กเริ่มต้น 2 ตัว หากยังไม่มี (กันซ้ำเผื่อถูกเรียกซ้ำ)
            # รายรับอื่นๆ
            db.execute(
                text(
                    '''
                    INSERT INTO "tags" (user_id, tag, type, value)
                    SELECT :uid, :t, :ty, 0
                    WHERE NOT EXISTS (
                        SELECT 1 FROM "tags" WHERE user_id = :uid AND tag = :t
                    )
                    '''
                ),
                {"uid": uid, "t": "รายรับอื่นๆ", "ty": "income"}
            )

            # รายจ่ายอื่นๆ
            db.execute(
                text(
                    '''
                    INSERT INTO "tags" (user_id, tag, type, value)
                    SELECT :uid, :t, :ty, 0
                    WHERE NOT EXISTS (
                        SELECT 1 FROM "tags" WHERE user_id = :uid AND tag = :t
                    )
                    '''
                ),
                {"uid": uid, "t": "รายจ่ายอื่นๆ", "ty": "expense"}
            )

        # ออกจาก with แล้วจะ commit ให้อัตโนมัติหากไม่ error
        return {"message": "User created successfully", "user_id": uid}

    except Exception as e:
        # ให้ error ละเอียดขึ้นใน dev/log; ฝั่ง API ตอบ 500 แบบสั้น
        raise HTTPException(status_code=500, detail="Failed to create user and default tags")

@router.get("/all/" , dependencies=[Depends(require_user)])
def read_users(db: Session = Depends(get_db)):
    rows = db.execute(text('SELECT id, username, email FROM "users"')).fetchall()
    return [dict(r._mapping) for r in rows]

@router.get("/{user_id}" , dependencies=[Depends(require_user)])
def read_user(user_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text('SELECT id, username, email FROM "users" WHERE id = :id'),
        {"id": user_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(row._mapping)
