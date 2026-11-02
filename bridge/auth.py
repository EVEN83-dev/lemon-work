"""
B-007: Auth - JWT-based user authentication and multi-tenant support.

Uses python-jose for JWT, passlib for password hashing.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

JWT_SECRET_KEY = os.environ.get("LEMON_JWT_SECRET", "lemon_bridge_default_secret_change_me")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_HOURS = 72


class User:
    def __init__(self, user_id: str = "", username: str = "", email: str = "",
                 password_hash: str = "", api_key: str = "",
                 created_at: float = 0.0):
        self.user_id = user_id or uuid.uuid4().hex[:16]
        self.username = username
        self.email = email
        self.password_hash = password_hash
        self.api_key = api_key or uuid.uuid4().hex[:24]
        self.created_at = created_at or time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "userId": self.user_id,
            "username": self.username,
            "email": self.email,
            "apiKey": self.api_key,
            "createdAt": self.created_at,
        }


class AuthManager:
    def __init__(self, db_path: str = ""):
        if not db_path:
            config_dir = os.path.join(os.path.expanduser("~"), ".lemon_bridge")
            os.makedirs(config_dir, exist_ok=True)
            db_path = os.path.join(config_dir, "auth.db")
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS users (
                user_id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                api_key TEXT UNIQUE,
                created_at REAL
            )""")
            conn.commit()
            conn.close()

    def _hash_password(self, password: str) -> str:
        return hashlib.sha256(password.encode('utf-8') + b'lemon_salt').hexdigest()

    def _verify_password(self, password: str, password_hash: str) -> bool:
        return self._hash_password(password) == password_hash

    def register(self, username: str, password: str, email: str = "") -> Tuple[Optional[User], str]:
        if not username or len(username) < 3:
            return None, "Username must be at least 3 characters"
        if not password or len(password) < 6:
            return None, "Password must be at least 6 characters"
        password_hash = self._hash_password(password)
        user = User(username=username, email=email, password_hash=password_hash)
        with self._lock:
            try:
                conn = sqlite3.connect(self._db_path)
                c = conn.cursor()
                c.execute(
                    "INSERT INTO users (user_id, username, email, password_hash, api_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (user.user_id, user.username, user.email, user.password_hash,
                     user.api_key, user.created_at),
                )
                conn.commit()
                conn.close()
                return user, ""
            except sqlite3.IntegrityError:
                return None, "Username or email already exists"

    def login(self, username: str, password: str) -> Tuple[Optional[User], str]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute(
                "SELECT user_id, username, email, password_hash, api_key, created_at FROM users WHERE username=?",
                (username,),
            )
            row = c.fetchone()
            conn.close()
        if row is None:
            return None, "User not found"
        if not self._verify_password(password, row[3]):
            return None, "Invalid password"
        user = User(
            user_id=row[0], username=row[1], email=row[2],
            password_hash=row[3], api_key=row[4], created_at=row[5],
        )
        return user, ""

    def create_token(self, user: User) -> str:
        try:
            from jose import jwt
            payload = {
                "sub": user.user_id,
                "username": user.username,
                "exp": int(time.time()) + JWT_EXPIRE_HOURS * 3600,
                "iat": int(time.time()),
            }
            return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
        except ImportError:
            payload = json.dumps({
                "sub": user.user_id,
                "username": user.username,
                "exp": int(time.time()) + JWT_EXPIRE_HOURS * 3600,
            })
            sig = hmac.new(JWT_SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()[:24]
            return f"{payload}|{sig}"

    def verify_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            from jose import jwt, JWTError
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
            return payload
        except ImportError:
            pass
        except Exception:
            return None
        try:
            parts = token.rsplit("|", 1)
            if len(parts) != 2:
                return None
            payload_str, sig = parts
            expected_sig = hmac.new(JWT_SECRET_KEY.encode(), payload_str.encode(),
                                    hashlib.sha256).hexdigest()[:24]
            if sig != expected_sig:
                return None
            payload = json.loads(payload_str)
            if payload.get("exp", 0) < time.time():
                return None
            return payload
        except (json.JSONDecodeError, ValueError):
            return None

    def authenticate_api_key(self, api_key: str) -> Optional[User]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute(
                "SELECT user_id, username, email, api_key, created_at FROM users WHERE api_key=?",
                (api_key,),
            )
            row = c.fetchone()
            conn.close()
        if row is None:
            return None
        return User(user_id=row[0], username=row[1], email=row[2],
                    api_key=row[3], created_at=row[4])

    def get_user(self, user_id: str) -> Optional[User]:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            c = conn.cursor()
            c.execute(
                "SELECT user_id, username, email, api_key, created_at FROM users WHERE user_id=?",
                (user_id,),
            )
            row = c.fetchone()
            conn.close()
        if row is None:
            return None
        return User(user_id=row[0], username=row[1], email=row[2],
                    api_key=row[3], created_at=row[4])
