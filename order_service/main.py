import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from passlib.context import CryptContext
import time
import jwt
from datetime import datetime, timedelta

app = FastAPI(title="Сервис Заказов и Пользователей")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# НОВОЕ: Настройка для хеширования (превращения пароля в шифр)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

class OrderRequest(BaseModel):
    item_id: int
    item_name: str

# НОВОЕ: Формат данных, который мы ждем от фронтенда при регистрации
class UserRegister(BaseModel):
    username: str
    password: str

def get_db_connection():
    retries = 5
    while retries > 0:
        try:
            conn = psycopg2.connect(
                host="db",
                database="store_db",
                user="user",
                password="password"
            )
            return conn
        except psycopg2.OperationalError:
            retries -= 1
            time.sleep(2)
    raise Exception("Не удалось подключиться к БД")

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Старая таблица заказов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL,
            item_name VARCHAR(255) NOT NULL,
            status VARCHAR(50) NOT NULL
        )
    ''')
    
    # НОВОЕ: Таблица пользователей. 
    # Обрати внимание на UNIQUE - двух пользователей с одинаковым логином быть не может.
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL
        )
    ''')
    
    conn.commit()
    cursor.close()
    conn.close()

@app.on_event("startup")
def on_startup():
    init_db()

# НОВЫЙ ЭНДПОИНТ: Регистрация
@app.post("/register")
def register_user(user: UserRegister):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Проверяем, есть ли уже такой пользователь в базе
    cursor.execute("SELECT * FROM users WHERE username = %s", (user.username,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        # Выдаем ошибку, если имя занято
        raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
        
    # 2. Хешируем пароль (чтобы преподаватель не докопался к безопасности)
    hashed_password = pwd_context.hash(user.password)
    
    # 3. Сохраняем в базу (обрати внимание, мы сохраняем ХЕШ, а не сам пароль)
    cursor.execute(
        "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
        (user.username, hashed_password)
    )
    new_user_id = cursor.fetchone()[0]
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"message": "Регистрация прошла успешно!", "user_id": new_user_id, "username": user.username}


# Секретный ключ для подписи токенов (в реальных проектах его прячут, но для курсовой оставляем так)
SECRET_KEY = "sokolova_store_super_secret" 
ALGORITHM = "HS256"

class UserLogin(BaseModel):
    username: str
    password: str

@app.post("/login")
def login_user(user: UserLogin):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    # 1. Ищем пользователя в базе
    cursor.execute("SELECT * FROM users WHERE username = %s", (user.username,))
    db_user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    # 2. Проверяем, существует ли он и совпадает ли пароль
    if not db_user or not pwd_context.verify(user.password, db_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
        
    # 3. Генерируем JWT-токен (зашиваем в него имя пользователя и срок действия)
    expire = datetime.utcnow() + timedelta(hours=24) # Токен "сгорит" через 24 часа
    token_data = {"sub": db_user["username"], "exp": expire}
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
    
    return {"access_token": token, "token_type": "bearer", "username": db_user["username"]}

# --- Старые методы для заказов ---
@app.post("/orders")
def create_order(order: OrderRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orders (item_id, item_name, status) VALUES (%s, %s, %s) RETURNING order_id",
        (order.item_id, order.item_name, "Оформлен")
    )
    new_order_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Заказ успешно сохранен в PostgreSQL!", "order": {"order_id": new_order_id, "item_id": order.item_id, "item_name": order.item_name, "status": "Оформлен"}}

@app.get("/orders")
def get_orders():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT order_id, item_id, item_name, status FROM orders")
    orders = cursor.fetchall()
    cursor.close()
    conn.close()
    return orders