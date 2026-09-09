FROM python:3.12-slim

WORKDIR /app

# Dependencies first, so a code change does not invalidate the wheel layer.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Most hosts inject the port they want the container to listen on.
ENV PORT=8000
ENV QUANT_RATE_LIMIT_PER_MINUTE=30

# Single worker on purpose: the rate limiter keeps its counter in process, so
# replicas would each allow the full limit. Move to Redis before scaling out.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1"]
