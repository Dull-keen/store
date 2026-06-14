# Берем готовый легкий образ Python
FROM python:3.10-slim

# Указываем рабочую папку внутри контейнера
WORKDIR /app

# Копируем список зависимостей и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код сервиса в контейнер
COPY . .

# Команда для запуска (обрати внимание на --host 0.0.0.0, это важно для Docker)
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]