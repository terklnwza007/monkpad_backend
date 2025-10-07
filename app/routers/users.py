from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
import bcrypt
from app.routers.auth import require_user
from app.database import get_db

router = APIRouter(prefix="/users", tags=["Users"] )

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

    db.execute(
        text('INSERT INTO "users" (username, password, email) VALUES (:u, :p, :e)'),
        {"u": username, "p": hashed_password, "e": email}
    )
    db.commit()
    return {"message": "User created successfully"}

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
