from fastapi import APIRouter, UploadFile, File, HTTPException
from io import BytesIO
from PIL import Image
from app.utils.ocr_utils import parse_slip

router = APIRouter(prefix="/ocr", tags=["OCR"])

@router.post("/parse")
async def parse_bill(file: UploadFile = File(...)):
    if file.content_type not in {"image/png", "image/jpeg"}:
        raise HTTPException(status_code=415, detail="Only PNG or JPEG supported")

    image_data = await file.read()
    img = Image.open(BytesIO(image_data))

    result = parse_slip(img)
    return result
