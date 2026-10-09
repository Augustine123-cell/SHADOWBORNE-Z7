from config import DB_PATH
from database import Database

db=Database(DB_PATH); db.init_db()
print('database: OK')
print('categories:', len(db.get_categories()))
