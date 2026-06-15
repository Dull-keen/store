import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import OAuth2PasswordBearer
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from passlib.context import CryptContext
import time
import jwt
from datetime import datetime, timedelta
import requests
import uuid
from typing import Optional

app = FastAPI(title="Сервис Заказов и Пользователей")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
SECRET_KEY = "sokolova_store_super_secret"
ALGORITHM = "HS256"
CATALOG_SERVICE_URL = "http://catalog-service:8001"

# НОВОЕ: Указываем FastAPI, где выдаются токены (для красивой работы Swagger)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

class OrderRequest(BaseModel):
    item_id: int
    item_name: str

class CheckoutRequest(BaseModel):
    note: Optional[str] = ""

class UserRegister(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

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
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            item_id INTEGER NOT NULL,
            item_name VARCHAR(255) NOT NULL,
            status VARCHAR(50) NOT NULL
        )
    ''')
    
    # НОВОЕ: Добавляем колонки для группировки заказа и примечания
    cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS group_id VARCHAR(50)")
    cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS note TEXT")
    
    conn.commit()
    cursor.close()
    conn.close()

@app.on_event("startup")
def on_startup():
    init_db()

# --- ФЕЙСКОНТРОЛЬ (Проверка токена) ---
def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        # Пытаемся расшифровать токен
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Недействительный токен")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Недействительный токен")
    
    # Ищем пользователя в базе
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user # Возвращаем все данные пользователя (включая его ID)

# --- АВТОРИЗАЦИЯ ---
@app.post("/register")
def register_user(user: UserRegister):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE username = %s", (user.username,))
    if cursor.fetchone():
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Пользователь с таким именем уже существует")
        
    hashed_password = pwd_context.hash(user.password)
    cursor.execute(
        "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
        (user.username, hashed_password)
    )
    new_user_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Успешно!", "user_id": new_user_id, "username": user.username}

@app.post("/login")
def login_user(user: UserLogin):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM users WHERE username = %s", (user.username,))
    db_user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if not db_user or not pwd_context.verify(user.password, db_user["password_hash"]):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
        
    expire = datetime.utcnow() + timedelta(hours=24)
    token_data = {"sub": db_user["username"], "exp": expire}
    token = jwt.encode(token_data, SECRET_KEY, algorithm=ALGORITHM)
    return {"access_token": token, "token_type": "bearer", "username": db_user["username"]}

# --- ЗАКАЗЫ (ТЕПЕРЬ ЗАЩИЩЕНЫ) ---
# Обрати внимание на Depends(get_current_user) - без токена метод даже не запустится!
@app.post("/orders")
def create_order(order: OrderRequest, current_user: dict = Depends(get_current_user)):
    # 1. Сначала просим сервис каталога зарезервировать товар
    try:
        response = requests.post(
            f"{CATALOG_SERVICE_URL}/reserve", 
            json={"item_id": order.item_id, "quantity": 1},
            timeout=5
        )
        # Если каталог ответил ошибкой (например, 400), значит товара нет
        if response.status_code != 200:
            raise HTTPException(status_code=400, detail="Этого товара больше нет в наличии")
    except requests.exceptions.RequestException:
        raise HTTPException(status_code=503, detail="Сервис каталога временно недоступен")

    # 2. Если товар успешно зарезервирован, добавляем его в корзину пользователя
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orders (user_id, item_id, item_name, status) VALUES (%s, %s, %s, %s) RETURNING order_id",
        (current_user["id"], order.item_id, order.item_name, "В корзине")
    )
    new_order_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Успешно!", "order_id": new_order_id}

@app.get("/orders")
def get_orders(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    # НОВОЕ: добавили group_id и note в выборку
    cursor.execute("SELECT order_id, item_id, item_name, status, group_id, note FROM orders WHERE user_id = %s", (current_user["id"],))
    orders = cursor.fetchall()
    cursor.close()
    conn.close()
    return orders

@app.post("/checkout")
def checkout_orders(req: CheckoutRequest, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Генерируем красивый короткий номер заказа, например ORD-A1B2C3
    new_group_id = f"ORD-{str(uuid.uuid4())[:6].upper()}"
    
    # Меняем статус и присваиваем номер заказа и примечание
    cursor.execute(
        "UPDATE orders SET status = 'Оформлен', group_id = %s, note = %s WHERE user_id = %s AND status = 'В корзине'",
        (new_group_id, req.note, current_user["id"])
    )
    updated_count = cursor.rowcount 
    
    conn.commit()
    cursor.close()
    conn.close()
    
    if updated_count == 0:
        raise HTTPException(status_code=400, detail="Корзина пуста")
        
    return {"message": "Заказ успешно оформлен!", "order_group": new_group_id}

@app.delete("/orders/{order_id}")
def delete_order(order_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)

    # 1. Узнаем item_id удаляемого товара из нашей БД
    cursor.execute(
        "SELECT item_id FROM orders WHERE order_id = %s AND user_id = %s AND status = 'В корзине'",
        (order_id, current_user["id"])
    )
    order = cursor.fetchone()

    if not order:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Товар не найден или уже оформлен")

    # 2. Просим каталог вернуть товар на виртуальный склад
    try:
        requests.post(
            f"{CATALOG_SERVICE_URL}/release", 
            json={"item_id": order["item_id"], "quantity": 1},
            timeout=5
        )
    except requests.exceptions.RequestException:
        # Для курсовой просто игнорируем, в реальности тут нужна система повторных попыток (retry)
        pass 

    # 3. Удаляем товар из корзины
    cursor.execute(
        "DELETE FROM orders WHERE order_id = %s AND user_id = %s AND status = 'В корзине'",
        (order_id, current_user["id"])
    )
    conn.commit()
    cursor.close()
    conn.close()

    return {"message": "Товар успешно удален из корзины"}