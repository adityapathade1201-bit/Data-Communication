FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 NETPULSE_DATA=/app/data
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY tests ./tests
COPY pytest.ini .
COPY scripts ./scripts
RUN mkdir -p /app/data/runs /app/data/scenarios
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
