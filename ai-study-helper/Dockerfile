# AI 학습 도우미 — 기본(CPU) 이미지.
# GPU STT를 컨테이너에서 쓰려면 nvidia/cuda 베이스 이미지 + `docker run --gpus all`이
# 필요하다. 로컬 GPU 환경에서는 run_all.ps1 실행을 권장하고, 이 이미지는
# 데모·배포(문서 파이프라인·UI) 용도다.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY api ./api
COPY worker ./worker
COPY app ./app
COPY .env.example .

ENV PYTHONUNBUFFERED=1
EXPOSE 8501 8000

CMD ["streamlit", "run", "app/streamlit_app.py", "--server.port", "8501", "--server.address", "0.0.0.0"]
