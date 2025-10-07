import re, difflib
from datetime import datetime
from PIL import Image
import pytesseract

# ======== CONFIG ========
# สำหรับ Windows Dev เท่านั้น (Render ไม่ต้องเซต)
# pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# ======== Regex Patterns ========
time_pattern = r"(?:[01]\d|2[0-3]):[0-5]\d"
money_pattern = r"\d{1,3}(?:,\d{3})*(?:\.\d{2})"
date_patterns = [
    r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
    r"\d{1,2}\s*[ก-๙]\s*\.?\s*[ก-๙]*\s*\.?\s*\d{2,4}",
    r"\d{1,2}\s*[ก-๙\u0E31-\u0E4C\.\: ]{2,10}\s*\d{2,4}",
]

thai_months = {
    "มค": 1, "กพ": 2, "มีค": 3, "เมย": 4, "พค": 5, "มิย": 6,
    "กค": 7, "สค": 8, "กย": 9, "ตค": 10, "พย": 11, "ธค": 12
}


def normalize_year(year: str) -> int:
    y = int(year)
    if y < 100:
        y += 2500
    if y >= 2500:
        y -= 543
    return y


def normalize_date(date_str: str):
    try:
        clean = re.sub(r"[^ก-๙0-9/-]", "", date_str)
        # case: normal 16/09/2020
        if re.match(r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}", clean):
            d, m, y = re.split(r"[/-]", clean)
            return datetime(normalize_year(y), int(m), int(d)).strftime("%Y-%m-%d")

        # case: ไทย/เพี้ยน
        for month in thai_months:
            if month in clean or difflib.get_close_matches(month, [clean], n=1, cutoff=0.3):
                nums = re.findall(r"\d{1,4}", clean)
                d = int(nums[0])
                y = normalize_year(nums[-1])
                m = thai_months[month]
                return datetime(y, m, d).strftime("%Y-%m-%d")
    except:
        return None
    return None


def find_date(text: str):
    for p in date_patterns:
        m = re.findall(p, text)
        if m:
            normalized = normalize_date(m[0])
            if normalized:
                return normalized
    return None


def parse_slip(img: Image.Image):
    text = pytesseract.image_to_string(img, lang="tha+eng")

    date_match = find_date(text)
    time_match = re.findall(time_pattern, text)
    money_match = re.findall(money_pattern, text)

    return {
        "date": date_match if date_match else None,
        "time": time_match[0] if time_match else None,
        "amount": money_match[0] if money_match else None
    }
