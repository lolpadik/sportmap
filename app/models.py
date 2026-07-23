from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String, unique=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    email = Column(String, unique=True)
    registered_at = Column(DateTime, default=datetime.utcnow)
    games_created = relationship("Game", back_populates="creator")
    players = relationship("Player", back_populates="user")
    messages = relationship("ChatMessage", back_populates="user")

class SportsGround(Base):
    __tablename__ = 'grounds'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String, nullable=False)
    sport_type = Column(String)
    city = Column(String, default="Минск")
    address = Column(String)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    games = relationship("Game", back_populates="ground")

class Game(Base):
    __tablename__ = 'games'
    id = Column(Integer, primary_key=True, autoincrement=True)
    ground_id = Column(Integer, ForeignKey('grounds.id'))
    creator_id = Column(Integer, ForeignKey('users.id'))
    title = Column(String, nullable=False)
    game_date = Column(DateTime, nullable=False)
    max_players = Column(Integer, default=10)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    ground = relationship("SportsGround", back_populates="games")
    creator = relationship("User", back_populates="games_created")
    players = relationship("Player", back_populates="game")
    messages = relationship("ChatMessage", back_populates="game")

class Player(Base):
    __tablename__ = 'players'
    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey('games.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    joined_at = Column(DateTime, default=datetime.utcnow)
    game = relationship("Game", back_populates="players")
    user = relationship("User", back_populates="players")

class ChatMessage(Base):
    __tablename__ = 'chat_messages'
    id = Column(Integer, primary_key=True, autoincrement=True)
    game_id = Column(Integer, ForeignKey('games.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    text = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)
    game = relationship("Game", back_populates="messages")
    user = relationship("User", back_populates="messages")