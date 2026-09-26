FROM python:3.12-slim

# CJK font so Japanese/Korean song titles render in the B50 image
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY chumai ./chumai

VOLUME ["/app/data"]
CMD ["python", "-m", "chumai"]
