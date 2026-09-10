import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import init_db
init_db()
print("✓ БД инициализирована.")
print("  Логин: admin")
print(f"  Пароль: {os.environ.get('ADMIN_PASSWORD', 'admin123')}")
print("  Смените пароль через панель после первого входа!")