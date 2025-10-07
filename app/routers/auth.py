# app/routers/auth.py
from fastapi import APIRouter, Depends, HTTPException, Body
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import get_db
from app.security import create_access_token, decode_token, verify_password

router = APIRouter(prefix="/auth", tags=["Auth"])
security = HTTPBearer(auto_error=True)

@router.post("/login")
def login(payload: dict = Body(...), db: Session = Depends(get_db)):
    username = payload.get("username")
    password = payload.get("password")
    if not username or not password:
        raise HTTPException(status_code=422, detail="username and password are required")

    row = db.execute(
        text('SELECT id, username, password FROM "users" WHERE username = :u'),
        {"u": username}
    ).fetchone()
    if not row:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    user = dict(row._mapping)
    if not verify_password(password, user["password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_access_token({"sub": user["username"], "uid": user["id"]})
    return {"access_token": token, "token_type": "bearer"}

def require_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    token = credentials.credentials
    try:
        payload = decode_token(token)
        uid = payload.get("uid")
        if not uid:
            raise HTTPException(status_code=401, detail="Invalid token")
        row = db.execute(
            text('SELECT id, username, email FROM "users" WHERE id = :id'),
            {"id": uid}
        ).fetchone()
        if not row:
            raise HTTPException(status_code=401, detail="User not found")
        return dict(row._mapping)  # {id, username, email}
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
