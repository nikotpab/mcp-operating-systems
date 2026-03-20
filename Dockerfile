FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    gnome-screenshot \
    x11-apps \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN git clone https://github.com/MeterLong/MCP-Doc.git /app/MCP-Doc

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "bot.py"]
