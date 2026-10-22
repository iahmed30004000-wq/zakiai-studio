# syntax=docker/dockerfile:1
# تطبيق VidPattern. ⚠ غير مجرَّب — ينجرّب على السيرفر. ما في أي مفتاح أو توكن داخل الصورة.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

# أقفال الكرت المشتركة مع صناديق الأوزان (حجم بالـ compose). 0777 لأنو مستخدم الصناديق (10001) غير مستخدم التطبيق (APP_UID).
RUN mkdir -p /locks && chmod 0777 /locks

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# الكود بس. library/ و models/ بتتركّب كحجوم وقت التشغيل (شوف docker-compose.yml)، ومستثناة بـ .dockerignore
COPY . .

EXPOSE 8000
# 0.0.0.0 هون = جوّا الحاوية بس. الـ compose بيربط المنفذ بـ 127.0.0.1 للجهاز.
CMD ["python", "run_web.py", "--lan", "--port", "8000"]
