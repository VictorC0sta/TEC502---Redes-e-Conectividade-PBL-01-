FROM python:3.12-slim

WORKDIR /app

COPY server.py .

RUN mkdir -p dados

EXPOSE 5000

CMD ["python", "server.py"]