from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db

router = APIRouter(prefix="/tags", tags=["Tags"])

# ================= ตัวอย่าง JSON =================
"""
{
    "user_id": 1,
    "tag": "อาหาร",
    "type": "expense"
}
"""
# ================================================

@router.post("/add/")
def create_tag(tag_data: dict = Body(...), db: Session = Depends(get_db)):
    user_id = tag_data.get("user_id")
    tag_name = tag_data.get("tag")
    tag_type = tag_data.get("type")

    if not user_id or not tag_name or not tag_type:
        raise HTTPException(status_code=422, detail="user_id, tag, type are required")
    if tag_type not in ("income", "expense"):
        raise HTTPException(status_code=400, detail="type must be 'income' or 'expense'")

    if not db.execute(text('SELECT id FROM "users" WHERE id = :uid'), {"uid": user_id}).fetchone():
        raise HTTPException(status_code=400, detail="User ID does not exist")

    # กัน tag ซ้ำต่อ user
    if db.execute(
        text('SELECT id FROM "tags" WHERE user_id = :uid AND tag = :t'),
        {"uid": user_id, "t": tag_name}
    ).fetchone():
        raise HTTPException(status_code=400, detail="Tag already exists for this user")

    db.execute(
        text('INSERT INTO "tags" (user_id, tag, type, value) VALUES (:uid, :t, :ty, :v)'),
        {"uid": user_id, "t": tag_name, "ty": tag_type, "v": 0}
    )
    db.commit()
    return {"message": "Tag created successfully"}

@router.get("/all/")
def read_tags(db: Session = Depends(get_db)):
    rows = db.execute(text('SELECT id, user_id, tag, type, value FROM "tags"')).fetchall()
    return [dict(r._mapping) for r in rows]

@router.get("/{user_id}")
def read_tag(user_id: int, db: Session = Depends(get_db)):
    rows = db.execute(
        text('SELECT id, user_id, tag, type, value FROM "tags" WHERE user_id = :uid'),
        {"uid": user_id}
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No tags found for this user")
    return [dict(r._mapping) for r in rows]
