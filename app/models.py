from sqlalchemy import Column, Integer, String, Float, Date, Time, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship, declarative_base

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True, comment="รหัสผู้ใช้ (Primary Key)")
    username = Column(String(50), unique=True, nullable=False, comment="ชื่อผู้ใช้ (ใช้ล็อกอิน)")
    password = Column(String(255), nullable=False, comment="รหัสผ่านที่เข้ารหัสแล้ว")
    email = Column(String(255), unique=True, nullable=False, comment="อีเมลของผู้ใช้")

    tags = relationship("Tag", back_populates="user", cascade="all, delete")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete")
    month_results = relationship("MonthResult", back_populates="user", cascade="all, delete")


class Tag(Base):
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True, comment="รหัสแท็ก")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="ผู้ใช้เจ้าของแท็ก")
    tag = Column(String(100), nullable=False, comment="ชื่อแท็ก เช่น อาหาร / เงินเดือน")
    type = Column(String(20), nullable=False, comment="ประเภทของแท็ก: income หรือ expense")
    value = Column(Float, default=0, comment="ยอดรวมสะสมของแท็กนี้")

    user = relationship("User", back_populates="tags")
    transactions = relationship("Transaction", back_populates="tag")

    __table_args__ = (
        UniqueConstraint("user_id", "tag", name="uq_user_tag"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True, comment="รหัสธุรกรรม")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="เจ้าของธุรกรรม")
    tag_id = Column(Integer, ForeignKey("tags.id", ondelete="SET NULL"), comment="แท็กที่ธุรกรรมนี้เกี่ยวข้อง")
    value = Column(Float, nullable=False, comment="จำนวนเงินของธุรกรรม")
    time = Column(Time, nullable=False, comment="เวลาที่เกิดธุรกรรม (HH:MM)")
    date = Column(Date, nullable=False, comment="วันที่ของธุรกรรม (YYYY-MM-DD)")
    note = Column(String(255), default="", comment="หมายเหตุเพิ่มเติม")

    user = relationship("User", back_populates="transactions")
    tag = relationship("Tag", back_populates="transactions")


class MonthResult(Base):
    __tablename__ = "month_results"

    id = Column(Integer, primary_key=True, index=True, comment="รหัสสรุปเดือน")
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="เจ้าของสรุปเดือน")
    month = Column(Integer, nullable=False, comment="เดือน (1–12)")
    year = Column(Integer, nullable=False, comment="ปี ค.ศ.")
    income = Column(Float, default=0, comment="ยอดรายรับรวมของเดือนนั้น")
    expense = Column(Float, default=0, comment="ยอดรายจ่ายรวมของเดือนนั้น")

    user = relationship("User", back_populates="month_results")

    __table_args__ = (
        UniqueConstraint("user_id", "month", "year", name="uq_user_month_year"),
    )
