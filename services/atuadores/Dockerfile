FROM python:3.11-slim

WORKDIR /app

COPY alarme.py .
COPY resfriamento.py .

RUN mkdir -p dados

CMD ["python", "-u", "alarme.py"]