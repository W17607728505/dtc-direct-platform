FROM python:3.12-slim

WORKDIR /app
COPY . /app

ENV HOST=0.0.0.0 \
    PORT=8787 \
    DTC_ENV=prod \
    DTC_DATA_DIR=/app/data

RUN mkdir -p /app/data

EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8787/api/health',timeout=3).status==200 else 1)"

CMD ["python", "server.py"]
