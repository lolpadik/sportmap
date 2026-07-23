from fastapi import FastAPI, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from datetime import datetime
import json
import os
import hashlib
import glob
import re
import telebot

from .database import get_db, init_db
from .models import SportsGround, Game, User, Player, ChatMessage, Rating
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
    for path in ["sportmap.db", "instance/sportmap.db", "/opt/render/project/src/sportmap.db"]:
        if os.path.exists(path):
            os.remove(path)
    init_db()
    db = next(get_db())
    grounds = [
        SportsGround(name="Микрорайон «Шведская горка»", sport_type="🏀 Баскетбол", city="Гомель",
                     address="ул. Григория Денисенко, 64–82", latitude=52.393165, longitude=30.957660,
                     description="Открытая баскетбольная площадка"),
        SportsGround(name="Железнодорожный район (Сельмаш)", sport_type="🏀 Баскетбол", city="Гомель",
                     address="ул. Бориса Царикова, возле СШ №38", latitude=52.449742, longitude=30.963124,
                     description="Баскетбольная площадка у школы"),
        SportsGround(name="Центральный район (Школа №11)", sport_type="🏀 Баскетбол", city="Гомель",
                     address="ул. Портовая, 12", latitude=52.440263, longitude=31.011831,
                     description="Школьная баскетбольная площадка"),
        SportsGround(name="Новобелицкий район (Школа №73)", sport_type="🏀 Баскетбол", city="Гомель",
                     address="ул. Кристалловская, 1А", latitude=52.370215, longitude=31.026330,
                     description="Баскетбольная площадка у школы"),
        SportsGround(name="Площадка на Огоренко (Волотова)", sport_type="🏀 Баскетбол", city="Гомель",
                     address="ул. Огоренко, 19", latitude=52.463286, longitude=31.025816,
                     description="Открытая баскетбольная площадка"),
        SportsGround(name="Микрорайон Клёнковский (21-й мкрн)", sport_type="🏀 Баскетбол", city="Гомель",
                     address="ул. Чечерская, 21-й мкрн", latitude=52.469145, longitude=31.041634,
                     description="Баскетбольная площадка в жилом массиве"),
        SportsGround(name="Микрорайон Клёнковский (20-й мкрн)", sport_type="🏀 Баскетбол", city="Гомель",
                     address="ул. Мазурова, 20-й мкрн", latitude=52.461942, longitude=31.031541,
                     description="Заводское спортивное поле"),
        SportsGround(name="Микрорайон Мельников Луг (17-й мкрн)", sport_type="🏀 Баскетбол", city="Гомель",
                     address="ул. Хатаевича / ул. Мазурова", latitude=52.449102, longitude=31.022987,
                     description="Баскетбольная площадка у жилых домов"),
        SportsGround(name="Стритбольная зона у Речицкого проспекта", sport_type="🏀 Баскетбол", city="Гомель",
                     address="Речицкий проспект, 61", latitude=52.406120, longitude=30.932450,
                     description="Workout-зона с баскетбольным кольцом"),
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
        "total_games": db.query(Game).filter(Game.ground_id == g.id).count(),
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
    total_games = db.query(Game).filter(Game.ground_id == ground_id).count()
    return templates.TemplateResponse("game.html", {
        "request": request, "user": user, "ground": ground, "games": games, "t": t, "lang": lang, "total_games": total_games
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
    existing_email = db.query(User).filter(User.email == email).first()
    if existing:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Пользователь уже существует", "t": t, "lang": lang})
    if existing_email:
        return templates.TemplateResponse("register.html", {"request": request, "error": "Эта почта уже используется", "t": t, "lang": lang})
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
    bot = telebot.TeleBot("8660797791:AAEdd9BY2YbEDlItlEhJARFREZtnb7Gw61I")
    try:
        bot.send_message("6886288656", f"🎮 Новая игра создана!\n{title}\nПлощадка: {game.ground.name}\nДата: {game_date}")
    except:
        pass
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
    bot = telebot.TeleBot("8660797791:AAEdd9BY2YbEDlItlEhJARFREZtnb7Gw61I")
    try:
        bot.send_message("6886288656", f"🔔 {user.username} записался на игру!\n{game.title}\nИгроков: {current_players+1}/{game.max_players}")
    except:
        pass
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
    db_user = db.query(User).filter(User.id == user.id).first()
    db_user.city = city
    db.commit()
    db.refresh(db_user)
    return RedirectResponse("/profile", status_code=303)


@app.post("/rate_ground/{ground_id}")
async def rate_ground(request: Request, ground_id: int, score: int = Form(...), db: Session = Depends(get_db)):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    ground = db.query(SportsGround).filter(SportsGround.id == ground_id).first()
    if not ground:
        return RedirectResponse("/map", status_code=303)
    existing = db.query(Rating).filter(Rating.ground_id == ground_id, Rating.user_id == user.id).first()
    if existing:
        existing.score = score
    else:
        rating = Rating(ground_id=ground_id, user_id=user.id, score=score)
        db.add(rating)
        ground.total_ratings += 1
    db.commit()
    avg = db.query(Rating).filter(Rating.ground_id == ground_id).with_entities(
        (Rating.score * 1.0).label('avg')
    ).all()
    ground.avg_rating = round(sum(a[0] for a in avg) / len(avg), 1)
    db.commit()
    return RedirectResponse(f"/ground/{ground_id}", status_code=303)


@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, db: Session = Depends(get_db)):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    if user.id != 1:
        return RedirectResponse("/", status_code=303)
    lang, t = get_lang(request)
    grounds = db.query(SportsGround).all()
    users = db.query(User).all()
    games = db.query(Game).all()
    return templates.TemplateResponse("admin.html", {
        "request": request, "user": user, "t": t, "lang": lang,
        "grounds": grounds, "users": users, "games": games
    })


@app.post("/admin/delete_ground/{ground_id}")
async def admin_delete_ground(request: Request, ground_id: int, db: Session = Depends(get_db)):
    user = require_login(request)
    if isinstance(user, RedirectResponse):
        return user
    if user.id != 1:
        return RedirectResponse("/", status_code=303)
    ground = db.query(SportsGround).filter(SportsGround.id == ground_id).first()
    if ground:
        db.delete(ground)
        db.commit()
    return RedirectResponse("/admin", status_code=303)


@app.get("/calendar", response_class=HTMLResponse)
async def calendar(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    lang, t = get_lang(request)
    games = db.query(Game).order_by(Game.game_date).all()
    games_json = json.dumps([{
        "title": g.title,
        "start": g.game_date.strftime("%Y-%m-%dT%H:%M"),
        "url": f"/ground/{g.ground_id}?lang={lang}",
        "extendedProps": {
            "ground": g.ground.name,
            "players": f"{len(g.players)}/{g.max_players}",
            "sport": g.ground.sport_type
        }
    } for g in games])
    return templates.TemplateResponse("calendar.html", {
        "request": request, "user": user, "t": t, "lang": lang, "games_json": games_json, "games": games
    })


@app.get("/stats", response_class=HTMLResponse)
async def stats(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request)
    lang, t = get_lang(request)
    grounds = db.query(SportsGround).all()
    sport_ratings = {}
    sport_counts = {}
    for g in grounds:
        sport = g.sport_type
        if sport not in sport_ratings:
            sport_ratings[sport] = []
            sport_counts[sport] = 0
        sport_counts[sport] += 1
        if g.avg_rating > 0:
            sport_ratings[sport].append(g.avg_rating)
    
    sport_stats = {}
    for sport in sport_ratings:
        ratings = sport_ratings[sport]
        avg = round(sum(ratings) / len(ratings), 1) if ratings else 0
        sport_stats[sport] = {"avg": avg, "count": sport_counts[sport]}
    
    sport_stats = dict(sorted(sport_stats.items(), key=lambda x: x[1]["avg"], reverse=True))
    
    return templates.TemplateResponse("stats.html", {
        "request": request, "user": user, "t": t, "lang": lang, "sport_stats": sport_stats
    })


@app.post("/chat_send")
async def chat_send(request: Request, text: str = Form(...)):
    user = get_current_user(request)
    username = user.username if user else "Гость"
    user_id = user.id if user else 0
    bot = telebot.TeleBot("8660797791:AAEdd9BY2YbEDlItlEhJARFREZtnb7Gw61I")
    try:
        bot.send_message("6886288656", f"💬 Чат от {username} (ID:{user_id}):\n{text}\n\nДля ответа ответьте на это сообщение (reply)")
    except:
        pass
    return {"ok": True}


@app.get("/chat_check")
async def chat_check(request: Request):
    user = get_current_user(request)
    user_id = user.id if user else 0
    filename = f"chat_reply_{user_id}.txt"
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            reply = f.read()
        return JSONResponse({"reply": reply})
    return JSONResponse({"reply": None})


@app.get("/chat_clear")
async def chat_clear(request: Request):
    user = get_current_user(request)
    user_id = user.id if user else 0
    filename = f"chat_reply_{user_id}.txt"
    if os.path.exists(filename):
        os.remove(filename)
    return {"ok": True}


@app.post("/telegram_callback")
async def telegram_callback(request: Request):
    body = await request.json()
    bot = telebot.TeleBot("8660797791:AAEdd9BY2YbEDlItlEhJARFREZtnb7Gw61I")
    
    message = body.get("message", {})
    if message:
        chat_id = message.get("chat", {}).get("id")
        text = message.get("text", "")
        if text == "/admin" and str(chat_id) == "6886288656":
            keyboard = telebot.types.InlineKeyboardMarkup()
            keyboard.add(
                telebot.types.InlineKeyboardButton("📋 Площадки", callback_data="admin_grounds"),
                telebot.types.InlineKeyboardButton("👥 Пользователи", callback_data="admin_users")
            )
            keyboard.add(
                telebot.types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
                telebot.types.InlineKeyboardButton("📩 Заявки", callback_data="admin_suggests")
            )
            bot.send_message(chat_id, "🛡️ Админ-панель", reply_markup=keyboard)
            return {"ok": True}
        if message.get("reply_to_message") and str(chat_id) == "6886288656":
            original = message.get("reply_to_message", {}).get("text", "")
            if "💬 Чат от" in original:
                match = re.search(r'ID:(\d+)\)', original)
                if match:
                    user_id = match.group(1)
                    with open(f"chat_reply_{user_id}.txt", "w", encoding="utf-8") as f:
                        f.write(text)
                    bot.send_message(chat_id, f"✅ Ответ отправлен пользователю ID:{user_id}")
                    return {"ok": True}
    
    callback = body.get("callback_query", {})
    data = callback.get("data", "")
    chat_id = callback.get("message", {}).get("chat", {}).get("id")
    message_id = callback.get("message", {}).get("message_id")
    
    if data.startswith("accept"):
        uid = data.split("|")[1]
        if os.path.exists(f"suggest_{uid}.txt"):
            with open(f"suggest_{uid}.txt", "r", encoding="utf-8") as f:
                parts = f.read().split("|")
                name, sport_type, address, lat, lon, description = parts[0], parts[1], parts[2], parts[3], parts[4], parts[5]
            db = next(get_db())
            ground = SportsGround(name=name, sport_type=sport_type, address=address,
                                  latitude=float(lat), longitude=float(lon), description=description)
            db.add(ground)
            db.commit()
            db.close()
            bot.edit_message_text(f"✅ Принято: {name}", chat_id, message_id)
    elif data.startswith("reject"):
        uid = data.split("|")[1]
        if os.path.exists(f"suggest_{uid}.txt"):
            with open(f"suggest_{uid}.txt", "r", encoding="utf-8") as f:
                name = f.read().split("|")[0]
            bot.edit_message_text(f"❌ Отклонено: {name}", chat_id, message_id)
    elif data == "admin_grounds":
        db = next(get_db())
        grounds = db.query(SportsGround).all()
        text = "📋 Все площадки:\n\n"
        for g in grounds:
            text += f"• {g.name} ({g.city})\n"
        db.close()
        bot.send_message(chat_id, text[:4000])
    elif data == "admin_users":
        db = next(get_db())
        users = db.query(User).all()
        text = f"👥 Пользователей: {len(users)}\n\n"
        for u in users[:20]:
            text += f"• {u.username} | {u.city}\n"
        db.close()
        bot.send_message(chat_id, text)
    elif data == "admin_stats":
        db = next(get_db())
        grounds_count = db.query(SportsGround).count()
        users_count = db.query(User).count()
        games_count = db.query(Game).count()
        db.close()
        bot.send_message(chat_id, f"📊 Статистика:\n\n🏟️ Площадок: {grounds_count}\n👥 Пользователей: {users_count}\n🎮 Игр: {games_count}")
    elif data == "admin_suggests":
        files = glob.glob("suggest_*.txt")
        if files:
            for f in files[:10]:
                with open(f, "r", encoding="utf-8") as file:
                    bot.send_message(chat_id, file.read()[:500])
        else:
            bot.send_message(chat_id, "Нет заявок")
    
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
    uid = hashlib.md5(f"{name}{address}{datetime.utcnow()}".encode()).hexdigest()[:8]
    with open(f"suggest_{uid}.txt", "w", encoding="utf-8") as f:
        f.write(f"{name}|{sport_type}|{address}|{lat}|{lon}|{description}")
    with open("suggestions.txt", "a", encoding="utf-8") as f:
        f.write(f"\n--- Новая заявка ---\n")
        f.write(f"От: {user.username}\n")
        f.write(f"Название: {name}\n")
        f.write(f"Спорт: {sport_type}\n")
        f.write(f"Адрес: {address}\n")
        f.write(f"Координаты: {lat}, {lon}\n")
        f.write(f"Описание: {description}\n")
    bot = telebot.TeleBot("8660797791:AAEdd9BY2YbEDlItlEhJARFREZtnb7Gw61I")
    text = f"📩 Новая площадка!\n\n👤 От: {user.username}\n🏟️ Название: {name}\n{sport_type}\n📍 Адрес: {address}\n🗺️ Координаты: {lat}, {lon}\n📝 Описание: {description}"
    keyboard = telebot.types.InlineKeyboardMarkup()
    btn_yes = telebot.types.InlineKeyboardButton("✅ Принять", callback_data=f"accept|{uid}")
    btn_no = telebot.types.InlineKeyboardButton("❌ Отказать", callback_data=f"reject|{uid}")
    keyboard.add(btn_yes, btn_no)
    try:
        bot.send_message("6886288656", text, reply_markup=keyboard)
        print("Сообщение в Telegram отправлено")
    except Exception as e:
        print(f"Ошибка отправки в Telegram: {e}")
    return RedirectResponse("/map", status_code=303)