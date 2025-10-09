from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.routers.auth import require_user

from app.database import get_db

router = APIRouter(prefix="/tags", tags=["Tags"] , dependencies=[Depends(require_user)])

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

# # add value to tag by user_id and tag_id
# #value = old valuse + new value
# # ตัวอย่าง JSON
# """
# {
#     "user_id": 1,
#     "tag_id": 2,
#     "value": 150.75              
# }
# """
# @router.post("/update/")
# def update_tag_value(data: dict = Body(...), db: Session = Depends(get_db)):
#     user_id = data.get("user_id")
#     tag_id = data.get("tag_id")
#     value = data.get("value")

#     if user_id is None or tag_id is None or value is None:
#         raise HTTPException(status_code=422, detail="user_id, tag_id, and value are required")
#     if not isinstance(value, (int, float)):
#         raise HTTPException(status_code=422, detail="value must be a number")

#     try:
#         value = float(value)
#     except Exception:
#         raise HTTPException(status_code=422, detail="value must be a number")

#     # ตรวจ user
#     if not db.execute(text('SELECT id FROM "users" WHERE id = :uid'), {"uid": user_id}).fetchone():
#         raise HTTPException(status_code=400, detail="User ID does not exist")

#     # ตรวจ tag ของ user เดียวกัน
#     tag = db.execute(
#         text('SELECT id, value FROM "tags" WHERE id = :tid AND user_id = :uid'),
#         {"tid": tag_id, "uid": user_id}
#     ).fetchone()
#     if not tag:
#         raise HTTPException(status_code=400, detail="Tag ID does not exist for this user")

#     old_value = tag._mapping["value"]
#     new_value = old_value + value

#     db.execute(
#         text('UPDATE "tags" SET value = :v WHERE id = :tid AND user_id = :uid'),
#         {"v": new_value, "tid": tag_id, "uid": user_id}
#     )
#     db.commit()
#     return {"message": "Tag value updated successfully", "new_value": new_value}

#delete tag by tag_id and change tag in transactions to "รายจ่ายอื่นๆ" or "รายรับอื่นๆ" depending on type of tag before delete
@router.delete("/delete/{tag_id}/{user_id}")
def delete_tag(tag_id: int, user_id: int, db: Session = Depends(get_db)):
    # ตรวจ tag ของ user เดียวกัน
    tag = db.execute(
        text('SELECT id, tag, type FROM "tags" WHERE id = :tid AND user_id = :uid'),
        {"tid": tag_id, "uid": user_id}
    ).fetchone()
    if not tag:
        raise HTTPException(status_code=400, detail="Tag ID does not exist for this user")

    tag_data = tag._mapping
    tag_type = tag_data["type"]

    # หา tag สำรอง
    if tag_type == "income":
        backup_tag = db.execute(
            text('SELECT id FROM "tags" WHERE user_id = :uid AND tag = :t'),
            {"uid": user_id, "t": "รายรับอื่นๆ"}
        ).fetchone()
    else:
        backup_tag = db.execute(
            text('SELECT id FROM "tags" WHERE user_id = :uid AND tag = :t'),
            {"uid": user_id, "t": "รายจ่ายอื่นๆ"}
        ).fetchone()

    if not backup_tag:
        raise HTTPException(status_code=400, detail="Backup tag does not exist. Please create it first.")

    backup_tag_id = backup_tag._mapping["id"]

    # อัพเดต transactions ให้ใช้ tag สำรอง
    db.execute(
        text('UPDATE "transactions" SET tag_id = :btid WHERE tag_id = :tid AND user_id = :uid'),
        {"btid": backup_tag_id, "tid": tag_id, "uid": user_id}
    )

    # ลบ tag
    db.execute(
        text('DELETE FROM "tags" WHERE id = :tid AND user_id = :uid'),
        {"tid": tag_id, "uid": user_id}
    )

    db.commit()
    return {"message": "Tag deleted successfully and transactions updated to backup tag"}