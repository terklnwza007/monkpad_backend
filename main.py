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
@app.post("/users/add/" , tags=["Users"])
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

# Get All Users
@app.get("/users/all/" , tags=["Users"])
def read_users(db: Session = Depends(get_db)):
    rows = db.execute(text('SELECT id, username, email FROM "users"')).fetchall()
    return [dict(row._mapping) for row in rows]


# Get User by ID 
@app.get("/users/{user_id}" , tags=["Users"])
def read_user(user_id: int, db: Session = Depends(get_db)):
    row = db.execute(
        text('SELECT id, username, email FROM "users" WHERE id = :user_id'),
        {"user_id": user_id}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="User not found")
    return dict(row._mapping)

# ===============================================

# ================= ตัวอย่าง JSON =================
"""
{
  "user_id": 1,
  "tag": "ค่าอาหาร",
  "type": "expense"
}
"""
# ===============================================

# Create tag by user_id
@app.post("/tags/add/" , tags=["Tags"])
def create_tag(tag_data: dict, db: Session = Depends(get_db)):
    user_id = tag_data.get("user_id")
    tag_name = tag_data.get("tag")
    tag_type = tag_data.get("type")

    # check user_id
    if not db.execute(
        text('SELECT id FROM "users" WHERE id = :user_id'),
        {"user_id": user_id}
    ).fetchone():
        raise HTTPException(status_code=400, detail="User ID does not exist")

    # insert tag
    db.execute(
        text('INSERT INTO "tags" (user_id, tag, type, value) VALUES (:user_id, :tag, :type, :value)'),
        {"user_id": user_id, "tag": tag_name, "type": tag_type, "value": 0}
    )
    db.commit()

    return {"message": "Tag created successfully"}

# Get All Tags 
@app.get("/tags/all/" , tags=["Tags"])
def read_tags(db: Session = Depends(get_db)):
    rows = db.execute(text('SELECT id, user_id, tag, type, value FROM "tags"')).fetchall()
    return [dict(row._mapping) for row in rows]

# Get Tag by user_id
@app.get("/tags/{user_id}" , tags=["Tags"])
def read_tag(user_id: int, db: Session = Depends(get_db)):
    rows = db.execute(
        text('SELECT id, user_id, tag, type, value FROM "tags" WHERE user_id = :user_id'),
        {"user_id": user_id}
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No tags found for this user")
    return [dict(row._mapping) for row in rows]








