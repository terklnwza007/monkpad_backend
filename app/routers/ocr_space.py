# app/routers/ocr_space.py
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
import httpx, re, os
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
    z = re.sub(r"[^\d\.,-]", "", s).replace(",", "")
    return z if re.fullmatch(r"-?\d+(\.\d+)?", z) else None

# --- คีย์เวิร์ดช่วยตัดสินใจจำนวนเงิน ---
AMOUNT_KEYWORDS = [
    "จำนวนเงิน", "ยอดชำระ", "ยอดรวม", "ยอดสุทธิ", "รวมทั้งสิ้น",
    "amount", "total", "paid", "payment", "grand total", "subtotal"
]
CURRENCY_TOKENS = ["บาท", "thb", "฿"]
NEGATIVE_KEYWORDS = [
    "รหัสอ้างอิง", "อ้างอิง", "reference", "ref", "เลขที่", "เลขอ้างอิง",
    "transaction", "txid", "customer", "client", "invoice no", "เลขที่ใบ",
    "รหัสลูกค้า"
]
_amount_num_pat = re.compile(r"-?\d{1,3}(?:[ ,]?\d{3})*(?:\.\d+)?|-?\d+\.\d+")

def _has_any(s: str, words: list[str]) -> bool:
    return any(w in s for w in words)

def extract_amount(text: str) -> str | None:
    """
    เลือกจำนวนเงินโดยให้คะแนนตามบริบทของบรรทัด:
      +10 ถ้าบรรทัดมีคีย์เวิร์ดจำนวนเงิน
      +6  ถ้าบรรทัดมีหน่วยสกุล (บาท/THB/฿)
      +4  ถ้าบรรทัดข้างเคียง (±1) มีคีย์เวิร์ดจำนวนเงิน
      +3  ถ้าตัวเลขมีทศนิยม
      -12 ถ้าบรรทัดมีคีย์เวิร์ดอ้างอิง/เลขที่
      -8  ถ้าเป็นเลขยาวมาก (>=9 หลัก) และไม่มีทศนิยม
      +1.5 ถ้าค่าอยู่ช่วงสมเหตุสมผล (0 < n < 10 ล้าน)
    จากนั้นเลือกคะแนนสูงสุด; ถ้าเสมอ เลือกที่มีทศนิยมก่อน
    """
    if not text:
        return None

    lines = [re.sub(r"\s+", " ", ln.strip().lower()) for ln in text.splitlines() if ln.strip()]
    candidates: list[tuple[str, float]] = []

    for i, ln in enumerate(lines):
        for m in _amount_num_pat.finditer(ln):
            raw = _normalize_amount(m.group(0))
            if not raw:
                continue

            has_decimal = "." in raw
            digits_only_len = len(re.sub(r"[^\d]", "", raw))

            score = 0.0
            if _has_any(ln, [w.lower() for w in AMOUNT_KEYWORDS]):
                score += 10
            if _has_any(ln, [w.lower() for w in CURRENCY_TOKENS]):
                score += 6

            for j in (i - 1, i + 1):
                if 0 <= j < len(lines):
                    if _has_any(lines[j], [w.lower() for w in AMOUNT_KEYWORDS]):
                        score += 4

            if _has_any(ln, [w.lower() for w in NEGATIVE_KEYWORDS]):
                score -= 12

            if has_decimal:
                score += 3

            if not has_decimal and digits_only_len >= 9:
                score -= 8

            try:
                n = abs(float(raw))
                if 0 < n < 10_000_000:
                    score += 1.5
            except:
                pass

            candidates.append((raw, score))

    if not candidates:
        return None

    # เรียงตาม (คะแนน, มีทศนิยมหรือไม่, ความยาวตัวเลข) แล้วเลือกตัวแรก
    candidates.sort(key=lambda x: (x[1], "." in x[0], -len(x[0])), reverse=True)
    best_raw, _ = candidates[0]

    # ถ้าตัวที่ได้ไม่มีทศนิยมและคะแนนไม่สูงมาก ลองหาตัวที่มีทศนิยมที่คะแนนดีสุดเป็น fallback
    if "." not in best_raw:
        with_decimal = [c for c in candidates if "." in c[0]]
        if with_decimal:
            best_raw = max(with_decimal, key=lambda x: x[1])[0]

    return best_raw

def _to_ce(y: int) -> int:
    """
    แปลงปีให้เป็น ค.ศ.:
    - ถ้าเป็น พ.ศ. (>= 2400) → ลบ 543
    - ถ้าเป็นปี 2 หลัก (0–99) สมมติเป็น พ.ศ. 25YY → แปลงเป็น ค.ศ. YY + 1957
      ตัวอย่าง: 68 → 2025
    - มิฉะนั้นคืนค่าเดิม (ถือเป็น ค.ศ. อยู่แล้ว)
    """
    if y >= 2400:
        return y - 543
    if 0 <= y <= 99:
        return y + 1957
    return y

def _from_ddmmyyyy(dd: str, mm: str, yyyy: str) -> str | None:
    try:
        y = int(yyyy); m = int(mm); d = int(dd)
        return f"{y:04d}-{m:02d}-{d:02d}"
    except:
        return None

def extract_date_iso(text: str) -> str | None:
    # 0) Normalize ข้อความเล็กน้อย
    t = text.replace(",", " ")

    # 1) DD/MM/YYYY หรือ DD-MM-YYYY หรือ DD.MM.YYYY (ปี 4 หลัก)
    m1 = re.search(r"\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{4})\b", t)
    if m1:
        y = _to_ce(int(m1.group(3)))
        return f"{y:04d}-{int(m1.group(2)):02d}-{int(m1.group(1)):02d}"

    # 1.1) DD/MM/YY (ปี 2 หลัก)
    m1b = re.search(r"\b(\d{1,2})[\/\-.](\d{1,2})[\/\-.](\d{2})\b", t)
    if m1b:
        y = _to_ce(int(m1b.group(3)))
        return f"{y:04d}-{int(m1b.group(2)):02d}-{int(m1b.group(1)):02d}"

    # 2) ไทย: "16 ก.ย. 2568" / "16 กันยายน 68" (รองรับปี 2 หรือ 4 หลัก, อาจมี 'พ.ศ.' แทรก)
    month_alt = "|".join(re.escape(k) for k in TH_MONTHS.keys())
    m2 = re.search(
        rf"\b(\d{{1,2}})\s*({month_alt})\s*(?:พ\.ศ\.\s*)?(\d{{2,4}})\b",
        t
    )
    if m2:
        d = int(m2.group(1))
        mon_txt = m2.group(2)
        y = _to_ce(int(m2.group(3)))
        m = TH_MONTHS.get(mon_txt)
        if m:
            return f"{y:04d}-{m:02d}-{d:02d}"

    # 3) ISO อยู่แล้ว: YYYY-MM-DD
    m3 = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", t)
    if m3:
        return m3.group(0)

    return None

def extract_time_hhmm(text: str) -> str | None:
    """
    ดึงเวลา HH:MM โดยหลีกเลี่ยงการอ่านทศนิยมของจำนวนเงินเป็นเวลา
    เกณฑ์:
      - ชั่วโมง 00–23, นาที 00–59
      - ให้คะแนนพิเศษถ้ามีคำว่า 'เวลา' หรือมีวันที่อยู่ในบรรทัด/บรรทัดข้างเคียง
      - ไม่รับรูปแบบมี '.' บนบรรทัดที่เป็นจำนวนเงิน/สกุลเงิน (เช่น 35.00 THB)
      - ให้ ':' ดีกว่า '.'
    """
    if not text:
        return None

    amount_kw = ["จำนวนเงิน", "ค่าธรรมเนียม", "baht", "บาท", "thb", "รวม", "ยอด"]
    time_kw = ["เวลา", "time"]
    # เดือนภาษาไทยเพื่อช่วยบอกว่าบรรทัดนี้คือวันที่
    month_alt = "|".join(re.escape(k) for k in TH_MONTHS.keys())
    date_pat_th = re.compile(rf"\b\d{{1,2}}\s*({month_alt})\s*(?:พ\.ศ\.\s*)?\d{{2,4}}\b")
    date_pat_num = re.compile(r"\b\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4}\b")

    # เตรียมบรรทัด
    raw_lines = [ln for ln in text.splitlines() if ln.strip()]
    lines = [re.sub(r"\s+", " ", ln.strip().lower()) for ln in raw_lines]

    candidates: list[tuple[str, float]] = []
    for i, ln in enumerate(lines):
        # ตรวจ flag บริบท
        is_amount_line = any(k in ln for k in amount_kw)
        has_time_kw = any(k in ln for k in time_kw)
        has_date_here = bool(date_pat_th.search(ln) or date_pat_num.search(ln))
        has_date_neighbor = False
        for j in (i - 1, i + 1):
            if 0 <= j < len(lines):
                if date_pat_th.search(lines[j]) or date_pat_num.search(lines[j]):
                    has_date_neighbor = True
                    break
        has_time_kw_neighbor = False
        for j in (i - 1, i + 1):
            if 0 <= j < len(lines):
                if any(k in lines[j] for k in time_kw):
                    has_time_kw_neighbor = True
                    break

        # หาเวลาแบบ HH:MM (ให้ความสำคัญ)
        for m in re.finditer(r"\b([01]?\d|2[0-3]):([0-5]\d)\b", ln):
            hh, mm = int(m.group(1)), int(m.group(2))
            score = 5.0  # base สำหรับ ':'
            if has_time_kw: score += 8
            if has_time_kw_neighbor: score += 5
            if has_date_here: score += 5
            if has_date_neighbor: score += 3
            if is_amount_line: score -= 6  # ถ้าบรรทัดพูดถึงจำนวนเงิน ไม่น่าใช่เวลา
            candidates.append((f"{hh:02d}:{mm:02d}", score))

        # หาเวลาแบบ HH.MM แต่ **ข้าม** บรรทัดเงิน
        if not is_amount_line:
            for m in re.finditer(r"\b([01]?\d|2[0-3])[.]([0-5]\d)\b", ln):
                hh, mm = int(m.group(1)), int(m.group(2))
                score = 2.0  # base สำหรับ '.'
                if has_time_kw: score += 8
                if has_time_kw_neighbor: score += 5
                if has_date_here: score += 5
                if has_date_neighbor: score += 3
                candidates.append((f"{hh:02d}:{mm:02d}", score))

    if not candidates:
        return None

    # เลือกคะแนนสูงสุด; ถ้าเท่ากัน เลือกแบบ ':' มาก่อน (เราให้ base สูงกว่าอยู่แล้ว)
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0]

# ---------- Endpoint ----------
@router.post("/parse")
async def parse_ocr(file: UploadFile = File(...)):
    API_KEY = os.getenv("OCR_SPACE_API_KEY") or "YOUR_FREE_OCR_SPACE_KEY"
    if not API_KEY or API_KEY == "YOUR_FREE_OCR_SPACE_KEY":
        raise HTTPException(status_code=500, detail="Missing OCR_SPACE_API_KEY")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")

    files = {
        
        "file": (file.filename or "image.jpg", content, file.content_type or "image/jpeg")
    }
    data = {
        
        "language": "tha",
        "isTable": "true",
        "OCREngine": 2,   
        "scale": "true",  
    }
    headers = {"apikey": API_KEY}

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.ocr.space/parse/image",
                data=data,
                files=files,
                headers=headers,
            )
    except httpx.ReadTimeout:
        raise HTTPException(status_code=504, detail="OCR upstream timed out")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OCR upstream error: {e}")

    if resp.status_code != 200:
        body = ""
        try:
            body = resp.text[:500]
        except:
            pass
        raise HTTPException(status_code=resp.status_code, detail=f"OCR.space HTTP {resp.status_code}: {body}")

    j = resp.json()
    if j.get("IsErroredOnProcessing"):
        detail = j.get("ErrorMessage") or j.get("ErrorDetails") or "OCR failed"
        if isinstance(detail, list):
            detail = "; ".join(detail)
        raise HTTPException(status_code=400, detail=detail)

    results = j.get("ParsedResults") or []
    full_text = "\n".join((r.get("ParsedText") or "") for r in results).strip()

    # ====== ดึง amount/date/time ตามที่เราทำไว้ก่อนหน้า (ย่อ) ======
    amount = extract_amount(full_text)
    date   = extract_date_iso(full_text)
    time   = extract_time_hhmm(full_text)

    return {"amount": amount, "date": date, "time": time, "text": full_text}