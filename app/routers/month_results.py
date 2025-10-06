from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.database import get_db

router = APIRouter(prefix="/month_results", tags=["Month Results"])

@router.get("/{user_id}")
def read_month_result(user_id: int, db: Session = Depends(get_db)):
    rows = db.execute(
        text('SELECT id, user_id, month, year, income, expense FROM "month_results" WHERE user_id = :uid'),
        {"uid": user_id}
    ).fetchall()
    if not rows:
        raise HTTPException(status_code=404, detail="No month results found for this user")
    return [dict(r._mapping) for r in rows]


# ================= ตัวอย่าง JSON =================
"""
{
    "user_id": 1,
    "month": 1,
    "year": 2024
}
"""
# ================================================

@router.post("/add/")
def create_month_result(data: dict = Body(...), db: Session = Depends(get_db)):
    user_id = data.get("user_id")
    month = data.get("month")
    year = data.get("year")

    # ตรวจสอบค่าที่จำเป็น
    if not user_id or not month or not year:
        raise HTTPException(status_code=422, detail="user_id, month, and year are required")

    if not (1 <= int(month) <= 12):
        raise HTTPException(status_code=400, detail="month must be 1..12")

    # ตรวจสอบว่าผู้ใช้มีอยู่จริงไหม
    user_exists = db.execute(
        text('SELECT id FROM "users" WHERE id = :uid'),
        {"uid": user_id}
    ).fetchone()
    if not user_exists:
        raise HTTPException(status_code=400, detail="User ID does not exist")

    # ตรวจสอบว่ามี record ของเดือนนั้นอยู่แล้วไหม
    existing = db.execute(
        text('SELECT id FROM "month_results" WHERE user_id = :uid AND month = :m AND year = :y'),
        {"uid": user_id, "m": month, "y": year}
    ).fetchone()
    if existing:
        raise HTTPException(status_code=400, detail="Month result already exists for this user/month/year")

    # insert income และ expense = 0
    db.execute(
        text('INSERT INTO "month_results" (user_id, month, year, income, expense) VALUES (:uid, :m, :y, 0, 0)'),
        {"uid": user_id, "m": month, "y": year}
    )
    db.commit()

    return {"message": "Month result created successfully", "user_id": user_id, "month": month, "year": year}

# ================= ตัวอย่าง JSON =================
"""
{
    "user_id": 1,
    "month": 1,
    "year": 2024,
    "amount": 5000,
    "type": "income"        (income or expense)
}
"""
# ================================================

@router.put("/update/")
def update_month_result(data: dict = Body(...), db: Session = Depends(get_db)):
    user_id = data.get("user_id")
    month = data.get("month")
    year = data.get("year")
    amount = data.get("amount", 0)
    typ = data.get("type")

    if not user_id or not month or not year or typ is None:
        raise HTTPException(status_code=422, detail="user_id, month, year, type are required")
    if typ not in ("income", "expense"):
        raise HTTPException(status_code=400, detail="type must be 'income' or 'expense'")
    try:
        amount = int(amount)
    except Exception:
        raise HTTPException(status_code=400, detail="amount must be an integer")
    if amount < 0:
        raise HTTPException(status_code=400, detail="amount must be >= 0")

    if not db.execute(text('SELECT id FROM "users" WHERE id = :uid'), {"uid": user_id}).fetchone():
        raise HTTPException(status_code=400, detail="User ID does not exist")

    mr = db.execute(
        text('SELECT id, income, expense FROM "month_results" WHERE user_id = :uid AND month = :m AND year = :y'),
        {"uid": user_id, "m": month, "y": year}
    ).fetchone()
    if not mr:
        raise HTTPException(status_code=404, detail="Month result not found")

    if typ == "income":
        new_income = mr.income + amount
        db.execute(text('UPDATE "month_results" SET income = :val WHERE id = :id'),
                   {"val": new_income, "id": mr.id})
    else:
        new_expense = mr.expense + amount
        db.execute(text('UPDATE "month_results" SET expense = :val WHERE id = :id'),
                   {"val": new_expense, "id": mr.id})

    db.commit()
    return {"message": "Month result updated successfully"}

# Exampe JSON Body
"""
{
    user_id:1,
    
}
"""