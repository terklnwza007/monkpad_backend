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


#ดู transaction ทั้งหมดของ user_id โดย join tags เพื่อดู type ของ tag  เเละชื่อ tag 
@router.get("/{user_id}")
def get_transactions_by_user(user_id: int, db: Session = Depends(get_db)):
    transactions = db.execute(
        text('SELECT t.id, t.tag_id, t.value, t.date, t.time, tg.type, tg.tag , t.note FROM "transactions" t JOIN "tags" tg ON t.tag_id = tg.id WHERE t.user_id = :uid ORDER BY t.date DESC, t.time DESC'),
        {"uid": user_id}
    ).fetchall()
    result = [dict(row._mapping) for row in transactions]
    return {"transactions": result}


# แก้ไช transaction โดยสามารถเเก้ไข value, time, date, note ,tag ได้
@router.put("/update/{transaction_id}")
def update_transaction(transaction_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    value = data.get("value")
    time_str = data.get("time")
    date_str = data.get("date")
    note = data.get("note")
    tag_id = data.get("tag_id")

    if value is not None and value <= 0:
        raise HTTPException(status_code=400, detail="value must be positive")

    time_obj = None
    if time_str:
        try:
            time_obj = datetime.strptime(time_str, "%H:%M").time()
        except ValueError:
            raise HTTPException(status_code=400, detail="time must be in HH:MM format")

    date_obj = None
    if date_str:
        try:
            date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(status_code=400, detail="date must be in YYYY-MM-DD format")

    # ตรวจสอบว่า transaction มีอยู่จริงไหม
    tr = db.execute(
        text('SELECT id, user_id, tag_id, value, date FROM "transactions" WHERE id = :tid'),
        {"tid": transaction_id}
    ).fetchone()
    if not tr:
        raise HTTPException(status_code=404, detail="Transaction not found")

    tr_data = tr._mapping
    user_id = tr_data["user_id"]
    old_tag_id = tr_data["tag_id"]
    old_value = tr_data["value"]
    old_date = tr_data["date"]
    old_month = old_date.month
    old_year = old_date.year

    new_tag_id = tag_id if tag_id is not None else old_tag_id
    new_value = value if value is not None else old_value
    new_date = date_obj if date_obj is not None else old_date
    new_month = new_date.month
    new_year = new_date.year

    # หา type ของแท็กเก่า
    old_tag_row = db.execute(
        text('SELECT type FROM "tags" WHERE id = :tid AND user_id = :uid'),
        {"tid": old_tag_id, "uid": user_id}
    ).fetchone()
    if not old_tag_row:
        raise HTTPException(status_code=400, detail="Old Tag ID does not exist for this user")
    old_tag_type = old_tag_row._mapping["type"]

    # หา type ของแท็กใหม่ (ถ้าเปลี่ยนแท็ก)
    if new_tag_id != old_tag_id:
        new_tag_row = db.execute(
            text('SELECT type FROM "tags" WHERE id = :tid AND user_id = :uid'),
            {"tid": new_tag_id, "uid": user_id}
        ).fetchone()
        if not new_tag_row:
            raise HTTPException(status_code=400, detail="New Tag ID does not exist for this user")
        new_tag_type = new_tag_row._mapping["type"]
    else:
        new_tag_type = old_tag_type
    # อัพเดต transaction
    db.execute(
        text('''
            UPDATE "transactions"
            SET tag_id = :new_tid,
                value = :v,
                time = COALESCE(:ti, time),
                date = COALESCE(:d, date),
                note = COALESCE(:n, note)
            WHERE id = :tid
        '''),
        {"new_tid": new_tag_id, "v": new_value, "ti": time_obj, "d": new_date, "n": note, "tid": transaction_id}
    )
    # อัพเดตยอดใน tags และ month_results
    if old_tag_id == new_tag_id:
        # ถ้าแท็กไม่เปลี่ยนแปลง แค่ปรับยอดตามค่าที่เปลี่ยน
        diff = new_value - old_value
        if diff != 0:
            db.execute(
                text('UPDATE "tags" SET value = value + :diff WHERE id = :tid AND user_id = :uid'),
                {"diff": diff, "tid": old_tag_id, "uid": user_id}
            )
            # อัพเดต month_results
            if old_tag_type == "income":
                mr = db.execute(
                    text('SELECT id, income FROM "month_results" WHERE user_id = :uid AND month = :m AND year = :y'),
                    {"uid": user_id, "m": old_month, "y": old_year}
                ).fetchone()
                if mr:
                    new_income = mr.income + diff
                    if new_income < 0:
                        new_income = 0
                    db.execute(
                        text('UPDATE "month_results" SET income = :val WHERE id = :id'),
                        {"val": new_income, "id": mr.id}
                    )
            else:  # expense
                mr = db.execute(
                    text('SELECT id, expense FROM "month_results" WHERE user_id = :uid AND month = :m AND year = :y'),
                    {"uid": user_id, "m": old_month, "y": old_year}
                ).fetchone()
                if mr:
                    new_expense = mr.expense + diff
                    if new_expense < 0:
                        new_expense = 0
                    db.execute(
                        text('UPDATE "month_results" SET expense = :val WHERE id = :id'),
                        {"val": new_expense, "id": mr.id}
                    )
    else:
        # ถ้าแท็กเปลี่ยนแปลง ต้องลดยอดจากแท็กเก่าและเดือนเก่า
        db.execute(
            text('UPDATE "tags" SET value = value - :v WHERE id = :tid AND user_id = :uid'),
            {"v": old_value, "tid": old_tag_id, "uid": user_id}
        )
        if old_tag_type == "income":
            mr = db.execute(
                text('SELECT id, income FROM "month_results" WHERE user_id = :uid AND month = :m AND year = :y'),
                {"uid": user_id, "m": old_month, "y": old_year}
            ).fetchone()
            if mr:
                new_income = mr.income - old_value
                if new_income < 0:
                    new_income = 0
                db.execute(
                    text('UPDATE "month_results" SET income = :val WHERE id = :id'),
                    {"val": new_income, "id": mr.id}
                )
        else:  # expense
            mr = db.execute(
                text('SELECT id, expense FROM "month_results" WHERE user_id = :uid AND month = :m AND year = :y'),
                {"uid": user_id, "m": old_month, "y": old_year}
            ).fetchone()
            if mr:
                new_expense = mr.expense - old_value
                if new_expense < 0:
                    new_expense = 0
                db.execute(
                    text('UPDATE "month_results" SET expense = :val WHERE id = :id'),
                    {"val": new_expense, "id": mr.id}
                )
        # แล้วเพิ่มยอดให้แท็กใหม่และเดือนใหม่
        db.execute(
            text('UPDATE "tags" SET value = value + :v WHERE id = :tid AND user_id = :uid'),
            {"v": new_value, "tid": new_tag_id, "uid": user_id}
        )
        if new_tag_type == "income":
            mr = db.execute(
                text('SELECT id, income FROM "month_results" WHERE user_id = :uid AND month = :m AND year = :y'),
                {"uid": user_id, "m": new_month, "y": new_year}
            ).fetchone()
            if mr:
                new_income = mr.income + new_value
                db.execute(
                    text('UPDATE "month_results" SET income = :val WHERE id = :id'),
                    {"val": new_income, "id": mr.id}
                )
            else:
                db.execute(
                    text('INSERT INTO "month_results" (user_id, month, year, income, expense) VALUES (:uid, :m, :y, :inc, 0)'),
                    {"uid": user_id, "m": new_month, "y": new_year, "inc": new_value}
                )
        else:  # expense
            mr = db.execute(
                text('SELECT id, expense FROM "month_results" WHERE user_id = :uid AND month = :m AND year = :y'),
                {"uid": user_id, "m": new_month, "y": new_year}
            ).fetchone()
            if mr:
                new_expense = mr.expense + new_value
                db.execute(
                    text('UPDATE "month_results" SET expense = :val WHERE id = :id'),
                    {"val": new_expense, "id": mr.id}
                )
            else:
                db.execute(
                    text('INSERT INTO "month_results" (user_id, month, year, income, expense) VALUES (:uid, :m, :y, 0, :exp)'),
                    {"uid": user_id, "m": new_month, "y": new_year, "exp": new_value}
                )
    db.commit()
    return {"message": "Transaction updated successfully"}
# ================================================
