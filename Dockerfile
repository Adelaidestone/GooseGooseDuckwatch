FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 安装 Chromium/Chromedriver 与常用中文字体
RUN apt-get update && apt-get install -y --no-install-recommends \
    chromium chromium-driver \
    fonts-wqy-zenhei fonts-noto-cjk \
    unzip curl ca-certificates git \
 && rm -rf /var/lib/apt/lists/*

# 让爬虫可通过环境变量找到浏览器
ENV CHROME_BIN=/usr/bin/chromium

WORKDIR /app
COPY requirements.txt /app/
RUN pip install -U pip && pip install -r requirements.txt

# 代码与 data 在运行时挂载
EXPOSE 8000
CMD ["uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
