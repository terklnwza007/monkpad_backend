# =============================
# Monkpad Backend Dockerfile
# =============================

FROM python:3.11-slim

# ติดตั้ง Tesseract และภาษาไทย
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-tha && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ตั้ง working directory
WORKDIR /app

# คัดลอกไฟล์ทั้งหมดเข้ามาใน container
COPY . /app

# ติดตั้ง dependencies
RUN pip install --no-cache-dir -r requirements.txt

# เปิดพอร์ต (Render ใช้ 10000 ตามค่าใน startCommand)
EXPOSE 10000

# สั่งรัน FastAPI ด้วย uvicorn
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "10000"]
