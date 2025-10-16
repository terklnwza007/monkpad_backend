from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import os
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")  # ควรมาจาก Dashboard ตรง ๆ

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,        # เช็ค connection ตายแล้วรีไซเคิล
    pool_size=2,               # อย่าตั้งใหญ่ ถ้าใช้ pooler
    max_overflow=0,            # กันล้นเกิน quota ของ pooler
    pool_recycle=300,          # รีไซเคิลบ้างกัน connection ค้าง
    connect_args={"sslmode": "require"}  # บังคับ SSL
)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
