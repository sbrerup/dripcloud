# python:3.12-slim (3.12.16-slim-trixie), multi-arch index digest as of 2026-10-28.
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
COPY app.py /app/app.py
COPY static /app/static

USER 1000:1000
EXPOSE 8080

CMD ["python", "/app/app.py"]
