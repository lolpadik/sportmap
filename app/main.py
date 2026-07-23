from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
import json
import os
import telebot

from .database import get_db, init_db
from .models import SportsGround, Game, User, Player, ChatMessage
from .auth import hash_password, check_password, get_current_user, require_login
from .translations import translations

app = FastAPI(title="SportMap Belarus")
templates = Jinja2Templates(directory="templates")

from starlette.middleware.sessions import SessionMiddleware
app.add_middleware(SessionMiddleware, secret_key="supersecretkey123", max_age=1209600)


def get_lang(request: Request):
    lang = request.query_params.get("lang", "ru")
    return lang, translations.get(lang, translations["ru"])


@app.on_event("startup")
async def startup():
    for db_path in ["instance/sportmap.db", "sportmap.db"]:
        if os.path.exists(db_path):
            os.remove(db_path)
    init_db()
    db = next(get_db())
    grounds = [
        SportsGround(name="Стадион Динамо", sport_type="Футбол", city="Минск",
                     address="Минск, ул. Кирова, 8", latitude=53.8950, longitude=27.5590,
                     description="Главный стадион Беларуси"),
    ]
    db.add_all(grounds)
    db.commit()
    db.close()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user = get_current_user(request)
    lang, t = get_lang(request)
    return templates.TemplateResponse("index.html", {"request": request, "user": user, "t": t, "lang": lang})


@app.get("/map", response_class=HTMLResponse)
async def show_map(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    lang, t = get_lang(request)
    grounds = db.query(SportsGround).all()
    now = datetime.utcnow()
    grounds_json = json.dumps([{
        "id": g.id, "name": g.name, "sport_type": g.sport_type,
        "lat": g.latitude, "lon": g.longitude, "address": g.address,
        "description": g.description, "city": g.city,
        "has_active": any(game.game_date <= now for game in g.games if game.players),
        "has_upcoming": any(game.game_date > now for game in g.games)
    } for g in grounds])
    return templates.TemplateResponse("map.html", {
        "request": request, "user": user, "grounds_json": grounds_json, "t": t, "lang": lang
    })


@app.get("/ground/{ground_id}", response_class=HTMLResponse)
async def ground_detail(request: Request, ground_id: int, db: Session = Depends(get_db)):
    user = get_current_user(request)
    lang, t = get_lang(request)
    ground = db.query(SportsGround).filter(SportsGround.id == ground_id).first()
    if not ground:
        return RedirectResponse("/map", status_code=303)
    games = db.query(Game).filter(Game.ground_id == ground_id, Game.game_date >= datetime.utcnow()).all()
    return templates.TemplateResponse("game.html", {
        "request": request, "user": user, "ground": ground, "games": games, "t": t, "lang": lang
    })


@app.get("/register", response_class=HTMLResponse)
async def register_form(request: Request):
    lang, t = get_lang(request)
    return templates.TemplateResponse("register.html", {"request": request, "error": None, "t": t, "lang": lang})


@app.post("/register")
async def register(request: Request, username: str = Form(...), password: str = Form(...),
                   email: str = Form(...), db: Session = Depends(get_db)):
    lang, t = get_lang(request)
    existing = db.query(User).filter(User.username == username).first()
    if existing:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Пользователь уже существует", "t": t, "lang": lang})
    hashed = hash_password(password)
    user = User(username=username, hashed_password=hashed, email=email)
    db.add(user)
    db.commit()
    request.session['user_id'] = user.id
    return RedirectResponse("/", status_code=303)


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    lang, t = get_lang(request)
    return templates.TemplateResponse("login.html", {"request": request, "error": None, "t": t, "lang": lang})


@app.post("/login")
async def login(request: Request, username: str = Form(...), password: str = Form(...),
                db: Session = Depends(get_db)):
    lang, t = get_lang(request)
    user = db.query(User).filter(User.username == username).first()
    if not user or not check_password(password, user.hashed_password):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Неверное имя или пароль", "t": t, "lang": lang})
    request.session['user_id'] = user.id
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.post("/create_game")
async def create_game(request: Request, ground_id: int = Form(...), title: str = Form(...),
                      game_date: str = Form(...), max_players: int = Form(...),
                      description: str = Form(""), db: Session = Depends(get_db)):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    game = Game(ground_id=ground_id, creator_id=user.id, title=title,
                game_date=datetime.strptime(game_date, "%Y-%m-%dT%H:%M"),
                max_players=max_players, description=description)
    db.add(game)
    db.commit()
    return RedirectResponse(f"/ground/{ground_id}", status_code=303)


@app.post("/join_game/{game_id}")
async def join_game(request: Request, game_id: int, db: Session = Depends(get_db)):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        return RedirectResponse("/map", status_code=303)
    existing_player = db.query(Player).filter(Player.game_id == game_id, Player.user_id == user.id).first()
    if existing_player:
        return RedirectResponse(f"/ground/{game.ground_id}", status_code=303)
    current_players = db.query(Player).filter(Player.game_id == game_id).count()
    if current_players >= game.max_players:
        return RedirectResponse(f"/ground/{game.ground_id}", status_code=303)
    new_player = Player(game_id=game_id, user_id=user.id)
    db.add(new_player)
    db.commit()
    return RedirectResponse(f"/ground/{game.ground_id}", status_code=303)


@app.post("/send_message/{game_id}")
async def send_message(request: Request, game_id: int, text: str = Form(...), db: Session = Depends(get_db)):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    game = db.query(Game).filter(Game.id == game_id).first()
    if not game:
        return RedirectResponse("/map", status_code=303)
    msg = ChatMessage(game_id=game_id, user_id=user.id, text=text)
    db.add(msg)
    db.commit()
    return RedirectResponse(f"/ground/{game.ground_id}", status_code=303)


@app.get("/profile", response_class=HTMLResponse)
async def profile(request: Request, db: Session = Depends(get_db)):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    lang, t = get_lang(request)
    my_games = db.query(Game).filter(Game.creator_id == user.id).order_by(Game.game_date.desc()).all()
    my_players = db.query(Player).filter(Player.user_id == user.id).all()
    joined_games = [p.game for p in my_players if p.game.creator_id != user.id]
    return templates.TemplateResponse("profile.html", {
        "request": request, "user": user, "t": t, "lang": lang,
        "my_games": my_games, "joined_games": joined_games
    })


@app.post("/set_city")
async def set_city(request: Request, city: str = Form(...), db: Session = Depends(get_db)):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    user.city = city
    db.commit()
    return RedirectResponse("/profile", status_code=303)


@app.post("/telegram_callback")
async def telegram_callback(request: Request):
    body = await request.json()
    callback = body.get("callback_query", {})
    data = callback.get("data", "")
    chat_id = callback.get("message", {}).get("chat", {}).get("id")
    message_id = callback.get("message", {}).get("message_id")
    bot = telebot.TeleBot("8660797791:AAEdd9BY2YbEDlItlEhJARFREZtnb7Gw61I")
    if data.startswith("accept"):
        parts = data.split("|")
        name, sport_type, address, lat, lon, description = parts[1], parts[2], parts[3], parts[4], parts[5], parts[6]
        db = next(get_db())
        ground = SportsGround(name=name, sport_type=sport_type, address=address,
                              latitude=float(lat), longitude=float(lon), description=description)
        db.add(ground)
        db.commit()
        db.close()
        bot.edit_message_text(f"✅ Принято: {name}", chat_id, message_id)
    elif data.startswith("reject"):
        name = data.split("|")[1]
        bot.edit_message_text(f"❌ Отклонено: {name}", chat_id, message_id)
    return {"ok": True}


@app.post("/suggest_ground")
async def suggest_ground(request: Request, name: str = Form(...), sport_type: str = Form(...),
                         address: str = Form(...), lat: str = Form(""), lon: str = Form(""),
                         description: str = Form(""), db: Session = Depends(get_db)):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    try:
        float(lat)
        float(lon)
    except:
        lang, t = get_lang(request)
        return RedirectResponse("/map?lang=" + lang, status_code=303)
    with open("suggestions.txt", "a", encoding="utf-8") as f:
        f.write(f"\n--- Новая заявка ---\n")
        f.write(f"От: {user.username}\n")
        f.write(f"Название: {name}\n")
        f.write(f"Спорт: {sport_type}\n")
        f.write(f"Адрес: {address}\n")
        f.write(f"Координаты: {lat}, {lon}\n")
        f.write(f"Описание: {description}\n")
    bot = telebot.TeleBot("8660797791:AAEdd9BY2YbEDlItlEhJARFREZtnb7Gw61I")
    text = f"📩 Новая площадка!\n\nОт: {user.username}\nНазвание: {name}\nСпорт: {sport_type}\nАдрес: {address}\nКоординаты: {lat}, {lon}\nОписание: {description}"
    keyboard = telebot.types.InlineKeyboardMarkup()
    btn_yes = telebot.types.InlineKeyboardButton("✅ Принять", callback_data=f"accept|{name}|{sport_type}|{address}|{lat}|{lon}|{description}")
    btn_no = telebot.types.InlineKeyboardButton("❌ Отказать", callback_data=f"reject|{name}")
    keyboard.add(btn_yes, btn_no)
    try:
        bot.send_message("6886288656", text, reply_markup=keyboard)
    except:
        pass
    return RedirectResponse("/map", status_code=303)