FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    python3-tk \
    tk-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY cliente.py .
RUN pip install requests matplotlib

CMD ["python", "-u", "cliente.py"]