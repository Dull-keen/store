import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import time

app = FastAPI(title="Сервис Каталога Украшений")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Функция подключения с ожиданием (т.к. база в Докере стартует не мгновенно)
def get_db_connection():
    retries = 5
    while retries > 0:
        try:
            conn = psycopg2.connect(
                host="db", # Имя нашего контейнера с базой из docker-compose
                database="store_db",
                user="user",
                password="password"
            )
            return conn
        except psycopg2.OperationalError:
            retries -= 1
            time.sleep(2) # Ждем 2 секунды и пробуем снова
    raise Exception("Не удалось подключиться к базе данных PostgreSQL")

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Создаем таблицу для каталога
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS catalog_products (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            price INTEGER NOT NULL,
            image VARCHAR(255)
        )
    ''')
    
    # Добавляем стартовые товары, если база пустая (с PNG картинками)
    cursor.execute("SELECT COUNT(*) FROM catalog_products")
    if cursor.fetchone()[0] == 0:
        initial_products = [
            ("Ожерелье «THE FAIRY POOL»", 1600, "fairy.png"),
            ("Ожерелье «НА ЗЕМЛЯНИЧНОМ ХОЛМЕ»", 1700, "strawberry.png"),
            ("Ожерелье «МАМБА»", 1500, "mamba.png")
        ]
        cursor.executemany("INSERT INTO catalog_products (name, price, image) VALUES (%s, %s, %s)", initial_products)
    
    conn.commit()
    cursor.close()
    conn.close()

@app.on_event("startup")
def on_startup():
    init_db()

@app.get("/products")
def get_products():
    conn = get_db_connection()
    # RealDictCursor сам превращает ответ из БД в красивый словарь
    cursor = conn.cursor(cursor_factory=RealDictCursor) 
    cursor.execute("SELECT id, name, price, image FROM catalog_products")
    products = cursor.fetchall()
    
    cursor.close()
    conn.close()
    return products