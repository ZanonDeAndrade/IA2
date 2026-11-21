FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu 'torch==2.15.0+cpu' \
    && pip install --no-cache-dir -r requirements.txt
COPY agent agent
COPY backend backend
COPY data data
COPY evaluation evaluation
COPY knowledge_base knowledge_base
COPY mcp_server mcp_server
CMD ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
