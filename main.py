from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text
import bcrypt
from database import SessionLocal

app = FastAPI()

# Dependency → เปิด session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ================= ตัวอย่าง JSON =================
"""
{
   "username": "koonteirk",
   "password": "Teirk@089404xxxx",
   "email": "tanawat.pxx@ku.th"
}
"""
# ===============================================

# Create User 
@app.post("/users/add/")
def create_user(user: dict, db: Session = Depends(get_db)):
    username = user.get("username")
    email = user.get("email")
    password = user.get("password")
    hashed_password = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
    hashed_password = hashed_password.decode("utf-8")

    # check duplicate username
    if db.execute(text('SELECT id FROM "users" WHERE username = :username'),
                  {"username": username}).fetchone():
        raise HTTPException(status_code=400, detail="Username already registered")

    # check duplicate email
    if db.execute(text('SELECT id FROM "users" WHERE email = :email'),
                  {"email": email}).fetchone():
        raise HTTPException(status_code=400, detail="Email already registered")

    # insert user
    db.execute(
        text('INSERT INTO "users" (username, password, email) VALUES (:username, :password, :email)'),
        {"username": username, "password": hashed_password, "email": email}
    )
    db.commit()

    return {"message": "User created successfully"}

# Get User by ID 
@app.get("/users/{user_id}")
def read_user(user_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text('SELECT id, username, email FROM "users" WHERE id = :user_id'),
        {"user_id": user_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(row._mapping)

# Get All Users 
@app.get("/users/all/")
def read_users(db: Session = Depends(get_db)):
    rows = db.execute(text('SELECT id, username, email FROM "users"')).fetchall()
    return [dict(row._mapping) for row in rows]
