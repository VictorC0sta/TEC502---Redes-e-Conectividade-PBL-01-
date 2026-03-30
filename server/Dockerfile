FROM python:3.11-slim

WORKDIR /app

COPY server.py .

RUN mkdir -p dados

CMD ["python", "-u", "server.py"]