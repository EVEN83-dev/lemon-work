FROM python:3.12-slim

WORKDIR /app

COPY bridge/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8765

CMD ["python", "bridge_server.py"]
