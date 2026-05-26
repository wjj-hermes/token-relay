FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data

ENV DATABASE_URL=sqlite+aiosqlite:///./data/data.db

EXPOSE ${PORT:-8888}

CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8888}
