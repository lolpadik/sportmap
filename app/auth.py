import bcrypt
from fastapi import Request
from fastapi.responses import RedirectResponse
from .database import SessionLocal
from .models import User

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def check_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode('utf-8'), hashed.encode('utf-8'))

def get_current_user(request: Request):
    user_id = request.session.get('user_id')
    if user_id:
        db = SessionLocal()
        user = db.query(User).filter(User.id == user_id).first()
        db.close()
        return user
    return None

def require_login(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse('/login', status_code=303)
    return user