import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import time

app = FastAPI(title="Сервис Каталога Украшений")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class ProductCreate(BaseModel):
    name: str
    price: int
    image: str
    product_type: str
    collection: str
    is_new: bool
    stock: int

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
        CREATE TABLE IF NOT EXISTS catalog_products (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            price INTEGER NOT NULL,
            image VARCHAR(255),
            product_type VARCHAR(50) NOT NULL,
            collection VARCHAR(100) NOT NULL,
            is_new BOOLEAN DEFAULT FALSE,
            stock INTEGER DEFAULT 0
        )
    ''')
    
    cursor.execute("SELECT COUNT(*) FROM catalog_products")
    if cursor.fetchone()[0] == 0:
        # Формат: (Имя, Цена, Картинка, ТИП, КОЛЛЕКЦИЯ, НОВИНКА, ОСТАТОК)
        initial_products = [
            ("Ожерелье «THE FAIRY POOL»", 1600, "fairy.png", "Ожерелье", "МАРМЕЛАДНАЯ", False, 5),
            ("Ожерелье «ВСЕЛЕНСКИЙ ЭЙСИД»", 1500, "acid.png", "Ожерелье", "МАРМЕЛАДНАЯ", False, 3),
            ("Ожерелье «ДУХ РУССКОЙ ЭМО ШКОЛЫ»", 1600, "emo.png", "Ожерелье", "МАРМЕЛАДНАЯ", True, 0),
            ("Ожерелье «ТИМОФЕЕВА ТРАВА»", 1800, "grass.png", "Ожерелье", "РУССКАЯ СКАЗКА", True, 1),
            ("Ожерелье «ВОДНЫЕ ПРОЦЕДУРЫ»", 1500, "water.png", "Ожерелье", "МАРМЕЛАДНАЯ", False, 2),
            ("Комплект «ПТИЧЬЕ МОЛОКО»", 1250, "moloko.png", "Комплект", "ДУХОВНАЯ", True, 1),
            ("Комплект «ЖИВИЦА»", 1250, "set_zhivitsa.png", "Комплект", "ДУХОВНАЯ", False, 4),
            ("Комплект «СТЕРИЛЬНЫЙ»", 1250, "set_sterile.png", "Комплект", "ДУХОВНАЯ", True, 10),
            ("Ожерелье «МЕСТО ПОД СОЛНЦЕМ»", 1500, "sun.png", "Ожерелье", "ДЕВЧАЧЬЯ", False, 0),
            ("Ожерелье «СУБСТРАТ»", 2300, "substrat.png", "Ожерелье", "ДУХОВНАЯ", False, 3),
            ("Ожерелье «ПОКОРНОСТЬ»", 1800, "pokornost.png", "Ожерелье", "ДУХОВНАЯ", False, 4),
            ("Ожерелье «ЗНАМЯ МИРА»", 1250, "mir.png", "Ожерелье", "ДУХОВНАЯ", False, 4),
            ("Ожерелье «ПЛОХАЯ КАРМА»", 1700, "karma.png", "Ожерелье", "ДУХОВНАЯ", False, 1),
            ("Ожерелье «ВОДЯНОЙ ОРЕХ»", 1500, "oreh.png", "Ожерелье", "ДУХОВНАЯ", False, 7),
            ("Ожерелье «МЫСЛИ МОНАХИНИ»", 1500, "monah.png", "Ожерелье", "ДУХОВНАЯ", False, 6),
            ("Ожерелье «ДОБРОЕ НАМЕРЕНИЕ»", 1500, "dobri.png", "Ожерелье", "ДУХОВНАЯ", False, 3),
            ("Ожерелье «ПРИЛИВ ЧУВСТВ»", 1700, "priliv.png", "Ожерелье", "ДУХОВНАЯ", False, 2),
            ("Ожерелье «НА ЗЕМЛЯНИЧНОМ ХОЛМЕ»", 1600, "strawberry.png", "Ожерелье", "МАРМЕЛАДНАЯ", False, 1),
            ("Комплект «ОЧАРОВАНИЕ»", 1250, "charm.png", "Комплект", "ДЕВЧАЧЬЯ", False, 4),
            ("Комплект «ФЛЁР»", 1250, "fler.png", "Комплект", "ДЕВЧАЧЬЯ", False, 0)
        ]
        cursor.executemany(
            "INSERT INTO catalog_products (name, price, image, product_type, collection, is_new, stock) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
            initial_products
        )
    
    conn.commit()
    cursor.close()
    conn.close()

@app.on_event("startup")
def on_startup():
    init_db()

@app.post("/admin/products")
def add_product(product: ProductCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO catalog_products (name, price, image, product_type, collection, is_new, stock) VALUES (%s, %s, %s, %s, %s, %s, %s)", 
        (product.name, product.price, product.image, product.product_type, product.collection, product.is_new, product.stock)
    )
    conn.commit()
    cursor.close()
    conn.close()
    return {"message": "Товар успешно добавлен в ассортимент!"}

@app.get("/products")
def get_products(product_type: Optional[str] = None, is_new: Optional[bool] = None):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor) 
    
    query = "SELECT id, name, price, image, product_type, collection, is_new, stock FROM catalog_products WHERE 1=1"
    params = []
    
    if product_type:
        query += " AND product_type = %s"
        params.append(product_type)
        
    if is_new is not None:
        query += " AND is_new = %s"
        params.append(is_new)
        
    cursor.execute(query, tuple(params))
    products = cursor.fetchall()
    
    cursor.close()
    conn.close()
    return products

class CheckoutItem(BaseModel):
    item_id: int
    quantity: int

class MassCheckoutRequest(BaseModel):
    items: list[CheckoutItem]

@app.get("/products/{item_id}")
def get_product(item_id: int):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=RealDictCursor)
    cursor.execute("SELECT * FROM catalog_products WHERE id = %s", (item_id,))
    product = cursor.fetchone()
    cursor.close()
    conn.close()
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")
    return product

@app.post("/verify_and_checkout")
def verify_and_checkout(req: MassCheckoutRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("BEGIN")
        
        for item in req.items:
            cursor.execute(
                "UPDATE catalog_products SET stock = stock - %s WHERE id = %s AND stock >= %s RETURNING stock",
                (item.quantity, item.item_id, item.quantity)
            )
            if cursor.fetchone() is None:
                cursor.execute("ROLLBACK")
                raise HTTPException(status_code=400, detail="Извините, часть товаров из вашей корзины уже раскупили.")
        
        cursor.execute("COMMIT")
        return {"message": "Успешно списано со склада"}
    except HTTPException:
        raise
    except Exception as e:
        cursor.execute("ROLLBACK")
        raise HTTPException(status_code=500, detail="Ошибка базы данных")
    finally:
        cursor.close()
        conn.close()