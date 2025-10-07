from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text
from datetime import datetime
from app.routers.auth import require_user
from app.database import get_db

router = APIRouter(prefix="/transactions", tags=["Transactions"]  , dependencies=[Depends(require_user)])

## ================= ตัวอย่าง JSON =================
"""
{
  "user_id": 4,
  "tag_id": 4,
  "value": 150000.3,
  "time": "12:30:30",
  "date": "2024-06-16",
  "note": "เงินเดือนฮิอิ"
}
"""
@router.post("/add/")
def create_transaction(data: dict = Body(...), db: Session = Depends(get_db)):
    user_id = data.get("user_id")
    tag_id = data.get("tag_id")
    value = data.get("value")
    time_str = data.get("time")
    date_str = data.get("date")
    note = data.get("note", "")

    # ตรวจสอบค่าที่จำเป็น
    if not user_id or not tag_id or value is None or not time_str or not date_str:
        raise HTTPException(status_code=422, detail="user_id, tag_id, value, time, and date are required")

    if value <= 0:
        raise HTTPException(status_code=400, detail="value must be positive")

    try:
        time_obj = datetime.strptime(time_str, "%H:%M").time()
    except ValueError:
        raise HTTPException(status_code=400, detail="time must be in HH:MM format")

    try:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be in YYYY-MM-DD format")

    # ตรวจสอบว่าผู้ใช้มีอยู่จริงไหม
    user_exists = db.execute(
        text('SELECT id FROM "users" WHERE id = :uid'),
        {"uid": user_id}
    ).fetchone()
    if not user_exists:
        raise HTTPException(status_code=400, detail="User ID does not exist")

    # ตรวจสอบว่า tag มีอยู่จริงไหม และเป็นของ user นั้นไหม
    tag_row = db.execute(
        text('SELECT id, type FROM "tags" WHERE id = :tid AND user_id = :uid'),
        {"tid": tag_id, "uid": user_id}
    ).fetchone()
    if not tag_row:
        raise HTTPException(status_code=400, detail="Tag ID does not exist for this user")
    tag_type = tag_row._mapping["type"]

    # insert transaction
    db.execute(
        text('INSERT INTO "transactions" (user_id, tag_id, value, time, date, note) VALUES (:uid, :tid, :v, :ti, :d, :n)'),
        {"uid": user_id, "tid": tag_id, "v": value, "ti": time_obj, "d": date_obj, "n": note}
    )

    # update ยอดใน tags
    if tag_type == "income":
        db.execute(
            text('UPDATE "tags" SET value = value + :v WHERE id = :tid AND user_id = :uid'),
            {"v": value, "tid": tag_id, "uid": user_id}
        )
        # update ยอดใน month_results
        month = date_obj.month
        year = date_obj.year
        mr = db.execute(
            text('SELECT id, income FROM "month_results" WHERE user_id = :uid AND month = :m AND year = :y'),
            {"uid": user_id, "m": month, "y": year}
        ).fetchone()
        if mr:
            new_income = mr.income + value
            db.execute(
                text('UPDATE "month_results" SET income = :val WHERE id = :id'),
                {"val": new_income, "id": mr.id}
            )
        else:
            # ถ้าไม่มี record ใน month_results ให้สร้างใหม่
            db.execute(
                text('INSERT INTO "month_results" (user_id, month, year, income, expense) VALUES (:uid, :m, :y, :inc, 0)'),
                {"uid": user_id, "m": month, "y": year, "inc": value}
            )
    else:  # expense
        db.execute(
            text('UPDATE "tags" SET value = value + :v WHERE id = :tid AND user_id = :uid'),
            {"v": value, "tid": tag_id, "uid": user_id}
        )
        # update ยอดใน month_results
        month = date_obj.month
        year = date_obj.year
        mr = db.execute(
            text('SELECT id, expense FROM "month_results" WHERE user_id = :uid AND month = :m AND year = :y'),
            {"uid": user_id, "m": month, "y": year}
        ).fetchone()
        if mr:
            new_expense = mr.expense + value
            db.execute(
                text('UPDATE "month_results" SET expense = :val WHERE id = :id'),
                {"val": new_expense, "id": mr.id}
            )
        else:
            # ถ้าไม่มี record ใน month_results ให้สร้างใหม่
            db.execute(
                text('INSERT INTO "month_results" (user_id, month, year, income, expense) VALUES (:uid, :m, :y, 0, :exp)'),
                {"uid": user_id, "m": month, "y": year, "exp": value}
            )
    db.commit()
    return {"message": "Transaction created successfully"}
# ================================================


#if delete transaction by transaction_id
@router.delete("/delete/{transaction_id}")
def delete_transaction(transaction_id: int, db: Session = Depends(get_db)):
    # ตรวจสอบว่า transaction มีอยู่จริงไหม
    tr = db.execute(
        text('SELECT id, user_id, tag_id, value, date FROM "transactions" WHERE id = :tid'),
        {"tid": transaction_id}
    ).fetchone()
    if not tr:
        raise HTTPException(status_code=404, detail="Transaction not found")

    tr_data = tr._mapping
    user_id = tr_data["user_id"]
    tag_id = tr_data["tag_id"]
    value = tr_data["value"]
    date_obj = tr_data["date"]
    month = date_obj.month
    year = date_obj.year

    # หา type ของ tag
    tag_row = db.execute(
        text('SELECT type FROM "tags" WHERE id = :tid AND user_id = :uid'),
        {"tid": tag_id, "uid": user_id}
    ).fetchone()
    if not tag_row:
        raise HTTPException(status_code=400, detail="Tag ID does not exist for this user")
    tag_type = tag_row._mapping["type"]

    # ลบ transaction
    db.execute(
        text('DELETE FROM "transactions" WHERE id = :tid'),
        {"tid": transaction_id}
    )

    # ลดยอดใน tags
    db.execute(
        text('UPDATE "tags" SET value = value - :v WHERE id = :tid AND user_id = :uid'),
        {"v": value, "tid": tag_id, "uid": user_id}
    )

    # ลดยอดใน month_results
    mr = db.execute(
        text('SELECT id, income, expense FROM "month_results" WHERE user_id = :uid AND month = :m AND year = :y'),
        {"uid": user_id, "m": month, "y": year}
    ).fetchone()
    if mr:
        if tag_type == "income":
            new_income = mr.income - value
            if new_income < 0:
                new_income = 0
            db.execute(
                text('UPDATE "month_results" SET income = :val WHERE id = :id'),
                {"val": new_income, "id": mr.id}
            )
        else:  # expense
            new_expense = mr.expense - value
            if new_expense < 0:
                new_expense = 0
            db.execute(
                text('UPDATE "month_results" SET expense = :val WHERE id = :id'),
                {"val": new_expense, "id": mr.id}
            )
    db.commit()
    return {"message": "Transaction deleted successfully"}
# ================================================