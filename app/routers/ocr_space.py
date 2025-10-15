# app/routers/ocr_space.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
import httpx, re
import os
from dotenv import load_dotenv
load_dotenv()

API_KEY = os.getenv("OCR_SPACE_API_KEY")  # ← ดึงจาก ENV
if not API_KEY:
    raise HTTPException(status_code=500, detail="Missing OCR_SPACE_API_KEY")

router = APIRouter(prefix="/ocr", tags=["ocr"])

# ---------- Helpers ----------
TH_MONTHS = {
    "ม.ค.": 1, "ก.พ.": 2, "มี.ค.": 3, "เม.ย.": 4, "พ.ค.": 5, "มิ.ย.": 6,
    "ก.ค.": 7, "ส.ค.": 8, "ก.ย.": 9, "ต.ค.": 10, "พ.ย.": 11, "ธ.ค.": 12,
    "มกราคม": 1, "กุมภาพันธ์": 2, "มีนาคม": 3, "เมษายน": 4, "พฤษภาคม": 5, "มิถุนายน": 6,
    "กรกฎาคม": 7, "สิงหาคม": 8, "กันยายน": 9, "ตุลาคม": 10, "พฤศจิกายน": 11, "ธันวาคม": 12,
}
def _pad2(n: int) -> str:
    return str(n).zfill(2)

def _normalize_amount(s: str | None) -> str | None:
    if not s:
        return None
    # เก็บเฉพาะตัวเลข เครื่องหมายลบ จุด และคอมมา แล้วลบคอมมาออก
    z = re.sub(r"[^\d\.,-]", "", s).replace(",", "")
    return z if re.fullmatch(r"-?\d+(\.\d+)?", z) else None

def extract_amount(text: str) -> str | None:
    # ดึง candidate ตัวเลขเงินทั้งหมด แล้วเลือกค่าที่ "มีนัยว่าเป็นจำนวนเงินที่สุด" (ใหญ่มากสุดโดยปกติ)
    cands = []
    for m in re.finditer(r"-?\d{1,3}(?:[ ,]?\d{3})*(?:\.\d+)?|-?\d+\.\d+", text):
        n = _normalize_amount(m.group(0))
        if n:
            cands.append(n)
    if not cands:
        return None
    best = cands[0]
    best_num = abs(float(best))
    for n in cands[1:]:
        try:
            v = abs(float(n))
            if v > best_num:
                best, best_num = n, v
        except:
            pass
    return best

def _from_ddmmyyyy(dd: str, mm: str, yyyy: str) -> str | None:
    try:
        y = int(yyyy); m = int(mm); d = int(dd)
        return f"{y:04d}-{m:02d}-{d:02d}"
    except:
        return None

def extract_date_iso(text: str) -> str | None:
    # 1) DD/MM/YYYY หรือ DD-MM-YYYY หรือ DD.MM.YYYY
    m1 = re.search(r"\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})\b", text)
    if m1:
        return _from_ddmmyyyy(m1.group(1), m1.group(2), m1.group(3))

    # 2) ไทย: "16 ก.ย. 2025" / "16 กันยายน 2568"
    month_alt = "|".join(re.escape(k) for k in TH_MONTHS.keys())
    m2 = re.search(rf"(\d{{1,2}})\s*({month_alt})\s*(\d{{4}})", text)
    if m2:
        d = int(m2.group(1))
        mon_txt = m2.group(2)
        y = int(m2.group(3))
        m = TH_MONTHS.get(mon_txt)
        if not m:
            return None
        # ถ้าเป็น พ.ศ. (> 2400) แปลงเป็น ค.ศ.
        if y > 2400:
            y -= 543
        return f"{y:04d}-{m:02d}-{d:02d}"

    # 3) ISO อยู่แล้ว: YYYY-MM-DD
    m3 = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    if m3:
        return m3.group(0)

    return None

def extract_time_hhmm(text: str) -> str | None:
    # 14:32 หรือ 14.32
    m1 = re.search(r"\b(\d{2})[:.](\d{2})\b", text)
    if m1:
        return f"{m1.group(1)}:{m1.group(2)}"
    # 1432
    m2 = re.search(r"\b(\d{2})(\d{2})\b", text)
    if m2:
        return f"{m2.group(1)}:{m2.group(2)}"
    return None

class OCRParsed(BaseModel):
    amount: str | None = None   # "1234.50"
    date:   str | None = None   # "YYYY-MM-DD"
    time:   str | None = None   # "HH:MM"
    text:   str | None = None   # raw text เผื่อ debug

# ---------- Endpoint ----------
@router.post("/parse", response_model=OCRParsed)
async def parse_ocr(file: UploadFile = File(...)):
    API_KEY = "YOUR_FREE_OCR_SPACE_KEY"  # <-- ใส่คีย์จริง
    content = await file.read()

    files = {"filename": (file.filename or "image.jpg", content, file.content_type or "image/jpeg")}
    data = {
        "apikey": API_KEY,
        "language": "eng+tha",  # รองรับไทย + อังกฤษ
        "isTable": "true",      # ช่วยจัดรูปแบบตาราง/บิล
    }

    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post("https://api.ocr.space/parse/image", data=data, files=files)

    if r.status_code != 200:
        raise HTTPException(status_code=502, detail=f"OCR.space HTTP {r.status_code}")

    j = r.json()
    if j.get("IsErroredOnProcessing"):
        # บางครั้ง ErrorMessage เป็น list
        detail = j.get("ErrorMessage") or j.get("ErrorDetails") or "OCR failed"
        if isinstance(detail, list):
            detail = "; ".join(detail)
        raise HTTPException(status_code=400, detail=detail)

    results = j.get("ParsedResults") or []
    # OCR.space อาจคืนหลาย page: รวมข้อความทั้งหมด
    full_text = "\n".join((res.get("ParsedText") or "") for res in results).strip()

    # ---- แยกฟิลด์ ----
    amount = extract_amount(full_text)
    date   = extract_date_iso(full_text)
    time   = extract_time_hhmm(full_text)

    return OCRParsed(amount=amount, date=date, time=time, text=full_text)
