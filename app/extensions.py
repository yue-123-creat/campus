from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy

# 统一 SQLAlchemy 扩展实例（供 app.py / migrate / models 共用）
db = SQLAlchemy(session_options={"autoflush": False, "expire_on_commit": False})
migrate = Migrate(compare_type=True)

