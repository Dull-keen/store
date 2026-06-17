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
    
    cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS group_id VARCHAR(50)")
    cursor.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS note TEXT")
    
    conn.commit()
    cursor.close()
    conn.close()

@app.on_event("startup")
def on_startup():
    init_db()

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Недействительный токен")
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Недействительный токен")
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
    user = cursor.fetchone()
    cursor.close()
    conn.close()
    
    if user is None:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user

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


@app.get("/orders")
def get_orders(current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT order_id, item_id, item_name, status, group_id, note FROM orders WHERE user_id = %s", (current_user["id"],))
    orders = cursor.fetchall()
    cursor.close()
    conn.close()
    return orders

@app.post("/orders")
def create_order(order: OrderRequest, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT COUNT(*) FROM orders WHERE user_id = %s AND item_id = %s AND status = 'В корзине'",
        (current_user["id"], order.item_id)
    )
    in_cart = cursor.fetchone()[0]
    
    try:
        resp = requests.get(f"{CATALOG_SERVICE_URL}/products/{order.item_id}", timeout=5)
        if resp.status_code == 200:
            stock = resp.json()["stock"]
            if in_cart >= stock:
                cursor.close()
                conn.close()
                raise HTTPException(status_code=400, detail=f"На складе доступно только {stock} шт.")
    except requests.exceptions.RequestException:
        pass 
        
    cursor.execute(
        "INSERT INTO orders (user_id, item_id, item_name, status) VALUES (%s, %s, %s, %s) RETURNING order_id",
        (current_user["id"], order.item_id, order.item_name, "В корзине")
    )
    new_order_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Добавлено в корзину", "order_id": new_order_id}

@app.delete("/orders/{order_id}")
def delete_order(order_id: int, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "DELETE FROM orders WHERE order_id = %s AND user_id = %s AND status = 'В корзине'",
        (order_id, current_user["id"])
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Товар удален из корзины"}

@app.post("/checkout")
def checkout_orders(req: CheckoutRequest, current_user: dict = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    
    cursor.execute(
        "SELECT item_id, COUNT(*) as quantity FROM orders WHERE user_id = %s AND status = 'В корзине' GROUP BY item_id",
        (current_user["id"],)
    )
    cart_items = cursor.fetchall()
    
    if not cart_items:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=400, detail="Корзина пуста")
        
    items_to_checkout = [{"item_id": row["item_id"], "quantity": row["quantity"]} for row in cart_items]
    
    try:
        response = requests.post(
            f"{CATALOG_SERVICE_URL}/verify_and_checkout", 
            json={"items": items_to_checkout},
            timeout=5
        )
        if response.status_code != 200:
            cursor.close()
            conn.close()
            error_msg = response.json().get("detail", "Недостаточно товара на складе")
            raise HTTPException(status_code=400, detail=error_msg)
    except requests.exceptions.RequestException:
        cursor.close()
        conn.close()
        raise HTTPException(status_code=503, detail="Сервис каталога недоступен")
        
    new_group_id = f"ORD-{str(uuid.uuid4())[:6].upper()}"
    cursor.execute(
        "UPDATE orders SET status = 'Оформлен', group_id = %s, note = %s WHERE user_id = %s AND status = 'В корзине'",
        (new_group_id, req.note, current_user["id"])
    )
    conn.commit()
    cursor.close()
    conn.close()
    
    return {"message": "Заказ успешно оформлен!", "order_group": new_group_id}