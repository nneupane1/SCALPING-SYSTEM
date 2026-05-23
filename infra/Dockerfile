FROM python:3.11-slim AS backend

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt
COPY . /app

CMD ["python", "main_paper.py"]

