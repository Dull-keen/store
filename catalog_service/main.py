import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import time

app = FastAPI(title="Сервис Каталога Украшений")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db_connection():
    retries = 5
    while retries > 0:
        try:
            conn = psycopg2.connect(
                host="db", database="store_db", user="user", password="password"
            )
            return conn
        except psycopg2.OperationalError:
            retries -= 1
            time.sleep(2)
    raise Exception("Не удалось подключиться к БД")

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Создаем правильную таблицу с тремя новыми параметрами
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS catalog_products (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            price INTEGER NOT NULL,
            image VARCHAR(255),
            product_type VARCHAR(50) NOT NULL,
            collection VARCHAR(100) NOT NULL,
            is_new BOOLEAN DEFAULT FALSE
        )
    ''')
    
    cursor.execute("SELECT COUNT(*) FROM catalog_products")
    if cursor.fetchone()[0] == 0:
        # Заполняем базу товарами из твоего макета
        # Формат: (Имя, Цена, Картинка, ТИП, КОЛЛЕКЦИЯ, НОВИНКА)
        initial_products = [
            ("Ожерелье «THE FAIRY POOL»", 1600, "fairy.png", "Ожерелье", "МАРМЕЛАДНАЯ", False),
            ("Ожерелье «ВСЕЛЕНСКИЙ ЭЙСИД»", 1500, "acid.png", "Ожерелье", "МАРМЕЛАДНАЯ", False),
            ("Ожерелье «ВОДНЫЕ ПРОЦЕДУРЫ»", 1500, "water.png", "Ожерелье", "МАРМЕЛАДНАЯ", True),
            ("Ожерелье «ДУХ РУССКОЙ ЭМО ШКОЛЫ»", 1600, "emo.png", "Ожерелье", "МАРМЕЛАДНАЯ", True),
            ("Ожерелье «ТИМОФЕЕВА ТРАВА»", 1800, "grass.png", "Ожерелье", "РУССКАЯ СКАЗКА", True),
            ("Комплект «ЖИВИЦА»", 2500, "set_zhivitsa.png", "Комплект", "ДУХОВНАЯ", False),
            ("Комплект «СТЕРИЛЬНЫЙ»", 2800, "set_sterile.png", "Комплект", "ДУХОВНАЯ", True)
        ]
        cursor.executemany(
            "INSERT INTO catalog_products (name, price, image, product_type, collection, is_new) VALUES (%s, %s, %s, %s, %s, %s)", 
            initial_products
        )
    
    conn.commit()
    cursor.close()
    conn.close()

@app.on_event("startup")
def on_startup():
    init_db()

# Умный метод, который принимает фильтры (если они есть)
@app.get("/products")
def get_products(product_type: Optional[str] = None, is_new: Optional[bool] = None):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor) 
    
    # Базовый запрос
    query = "SELECT id, name, price, image, product_type, collection, is_new FROM catalog_products WHERE 1=1"
    params = []
    
    # Если фронтенд попросил конкретный тип (например, "Ожерелье")
    if product_type:
        query += " AND product_type = %s"
        params.append(product_type)
        
    # Если фронтенд попросил новинки
    if is_new is not None:
        query += " AND is_new = %s"
        params.append(is_new)
        
    cursor.execute(query, tuple(params))
    products = cursor.fetchall()
    
    cursor.close()
    conn.close()
    return products