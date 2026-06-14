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

# НОВОЕ: Указываем FastAPI, где выдаются токены (для красивой работы Swagger)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

class OrderRequest(BaseModel):
    item_id: int
    item_name: str

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
    
    # НОВОЕ: В таблицу заказов добавлено поле user_id!
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            order_id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            item_id INTEGER NOT NULL,
            item_name VARCHAR(255) NOT NULL,
            status VARCHAR(50) NOT NULL
        )
    ''')
    
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
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO orders (user_id, item_id, item_name, status) VALUES (%s, %s, %s, %s) RETURNING order_id",
        (current_user["id"], order.item_id, order.item_name, "В корзине") # Сохраняем user_id!
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
    # Выдаем только те заказы, которые принадлежат этому пользователю
    cursor.execute("SELECT order_id, item_id, item_name, status FROM orders WHERE user_id = %s", (current_user["id"],))
    orders = cursor.fetchall()
    cursor.close()
    conn.close()
    return orders

@app.post("/checkout")
def checkout_orders(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Меняем статус с "В корзине" на "Оформлен"
    cursor.execute(
        "UPDATE orders SET status = 'Оформлен' WHERE user_id = %s AND status = 'В корзине'",
        (current_user["id"],)
    )
    updated_count = cursor.rowcount # Смотрим, сколько товаров обновилось
    
    conn.commit()
    cursor.close()
    conn.close()
    
    if updated_count == 0:
        raise HTTPException(status_code=400, detail="Корзина пуста")
        
    return {"message": "Заказ успешно оформлен!"}

@app.delete("/orders/{order_id}")
def delete_order(order_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Удаляем товар по его ID. 
    # ВАЖНО: проверяем user_id, чтобы хакер не мог удалить чужой заказ!
    # И разрешаем удалять только то, что еще "В корзине" (оформленные отменять нельзя).
    cursor.execute(
        "DELETE FROM orders WHERE order_id = %s AND user_id = %s AND status = 'В корзине'",
        (order_id, current_user["id"])
    )
    deleted_count = cursor.rowcount
    
    conn.commit()
    cursor.close()
    conn.close()
    
    if deleted_count == 0:
        raise HTTPException(status_code=400, detail="Товар не найден или уже оформлен")
        
    return {"message": "Товар успешно удален из корзины"}