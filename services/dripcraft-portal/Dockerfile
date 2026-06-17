FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
COPY app.py /app/app.py
COPY static /app/static

USER 1000:1000
EXPOSE 8080

CMD ["python", "/app/app.py"]
