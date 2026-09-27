"""
SQLite database helpers for the Movie Recommendation System.

The SQLite database is the master catalog for users, favorites, and movies.
The movie CSV is used only for the one-time seed when the movies table is empty.
"""

import csv
import os
import sqlite3
from typing import Optional, Dict, Any, Tuple, List


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "movie_recommendation.db")
CSV_PATH = os.path.join(BASE_DIR, "movies.csv")


def get_connection():
    """Return a SQLite connection with row access by column name."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create the application tables if they do not already exist."""
    conn = get_connection()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_admin INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS movies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                release_year INTEGER,
                genre TEXT,
                director TEXT,
                cast TEXT,
                keywords TEXT,
                overview TEXT,
                vote_average REAL DEFAULT 0.0,
                vote_count INTEGER DEFAULT 0,
                popularity REAL DEFAULT 0.0,
                poster_url TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS favorites (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                movie_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, movie_id)
            );
            """
        )
        conn.commit()
    finally:
        conn.close()


def _clean(value):
    """Convert empty/NaN-like values to None and strip strings."""
    if value is None:
        return None
    value = str(value).strip()
    if value == "" or value.lower() in {"nan", "none", "null"}:
        return None
    return value


def _to_int(value, default=None):
    value = _clean(value)
    if value is None:
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value, default=0.0):
    value = _clean(value)
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def seed_movies_from_csv_if_empty():
    """
    Seed movies from movies.csv only when the SQLite movies table is empty.

    CSV columns:
    movie_id,title,release_year,genre,director,cast,keywords,overview,
    vote_average,vote_count,popularity,poster_url
    """
    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM movies").fetchone()[0]
        if count > 0:
            return

        if not os.path.exists(CSV_PATH):
            return

        with open(CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            rows = []
            for row in reader:
                movie_id = _to_int(row.get("movie_id"))
                title = _clean(row.get("title"))
                if title is None:
                    continue

                rows.append(
                    (
                        movie_id,
                        title,
                        _to_int(row.get("release_year")),
                        _clean(row.get("genre")),
                        _clean(row.get("director")),
                        _clean(row.get("cast")),
                        _clean(row.get("keywords")),
                        _clean(row.get("overview")),
                        _to_float(row.get("vote_average")),
                        _to_int(row.get("vote_count"), 0),
                        _to_float(row.get("popularity")),
                        _clean(row.get("poster_url")),
                    )
                )

        conn.executemany(
            """
            INSERT INTO movies
            (id, title, release_year, genre, director, "cast", keywords,
             overview, vote_average, vote_count, popularity, poster_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def create_user(username, email, password_hash):
    """Create a normal user. Returns (success, message)."""
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO users (username, email, password_hash, is_admin)
            VALUES (?, ?, ?, 0)
            """,
            (username, email, password_hash),
        )
        conn.commit()
        return True, "User created successfully."
    except sqlite3.IntegrityError as exc:
        message = str(exc)
        if "username" in message.lower():
            return False, "Username is already registered."
        if "email" in message.lower():
            return False, "Email is already registered."
        return False, "Unable to create user."
    finally:
        conn.close()


def get_user_by_username(username):
    """Return a user dictionary by username, or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, username, email, password_hash, created_at, is_admin "
            "FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_email(email):
    """Return a user dictionary by email, or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, username, email, password_hash, created_at, is_admin "
            "FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def is_user_admin(user_id):
    """Return True when the given user has administrator privileges."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT is_admin FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return bool(row and row["is_admin"])
    finally:
        conn.close()


def promote_user_to_admin(user_id):
    """Promote a user to administrator. Returns (success, message)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "UPDATE users SET is_admin = 1 WHERE id = ?", (user_id,)
        )
        conn.commit()
        if cur.rowcount:
            return True, "User promoted to administrator."
        return False, "User not found."
    finally:
        conn.close()


def add_favorite(user_id, movie_id):
    """Add a movie to a user's favorites."""
    conn = get_connection()
    try:
        movie = conn.execute(
            "SELECT id FROM movies WHERE id = ?", (movie_id,)
        ).fetchone()
        if not movie:
            return False, "Movie not found."

        try:
            conn.execute(
                "INSERT INTO favorites (user_id, movie_id) VALUES (?, ?)",
                (user_id, movie_id),
            )
            conn.commit()
            return True, "Movie added to favorites."
        except sqlite3.IntegrityError:
            conn.rollback()
            return False, "Movie is already in favorites."
    finally:
        conn.close()


def remove_favorite(user_id, movie_id):
    """Remove a movie from a user's favorites."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND movie_id = ?",
            (user_id, movie_id),
        )
        conn.commit()
        if cur.rowcount:
            return True, "Movie removed from favorites."
        return False, "Movie is not in favorites."
    finally:
        conn.close()


def get_user_favorite_movie_ids(user_id):
    """Return a list of movie IDs favorited by a user."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT movie_id FROM favorites WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()
        return [int(row["movie_id"]) for row in rows]
    finally:
        conn.close()


def is_movie_favorite(user_id, movie_id):
    """Return whether a movie is in a user's favorites."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND movie_id = ? LIMIT 1",
            (user_id, movie_id),
        ).fetchone()
        return row is not None
    finally:
        conn.close()



def get_all_movies_df():
    """Return the complete SQLite movie catalog as a Pandas DataFrame."""
    import pandas as pd

    conn = get_connection()
    try:
        return pd.read_sql_query(
            """
            SELECT
                id AS movie_id,
                title,
                release_year,
                genre,
                director,
                "cast" AS cast,
                keywords,
                overview,
                vote_average,
                vote_count,
                popularity,
                poster_url
            FROM movies
            ORDER BY id
            """,
            conn,
        )
    finally:
        conn.close()


def load_movies_dataframe():
    """Compatibility alias for the SQLite-to-DataFrame loader."""
    return get_all_movies_df()

def admin_get_all_movies():
    """Return all movies as dictionaries for the admin dashboard."""
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, title, release_year, genre, director, "cast", keywords,
                   overview, vote_average, vote_count, popularity, poster_url,
                   created_at, updated_at
            FROM movies
            ORDER BY id
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def admin_get_movie_by_id(movie_id):
    """Return one movie dictionary by SQLite ID, or None."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, title, release_year, genre, director, "cast", keywords,
                   overview, vote_average, vote_count, popularity, poster_url,
                   created_at, updated_at
            FROM movies
            WHERE id = ?
            """,
            (movie_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def admin_add_movie(data):
    """Insert a movie from the admin form. Returns (success, message, new_id)."""
    title = _clean(data.get("title"))
    if not title:
        return False, "Movie title is required.", None

    conn = get_connection()
    try:
        cur = conn.execute(
            """
            INSERT INTO movies
            (title, release_year, genre, director, "cast", keywords, overview,
             vote_average, vote_count, popularity, poster_url)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                title,
                _to_int(data.get("release_year")),
                _clean(data.get("genre")),
                _clean(data.get("director")),
                _clean(data.get("cast")),
                _clean(data.get("keywords")),
                _clean(data.get("overview")),
                _to_float(data.get("vote_average")),
                _to_int(data.get("vote_count"), 0),
                _to_float(data.get("popularity")),
                _clean(data.get("poster_url")),
            ),
        )
        conn.commit()
        return True, f"Movie '{title}' added successfully.", cur.lastrowid
    except sqlite3.Error as exc:
        conn.rollback()
        return False, f"Database error: {exc}", None
    finally:
        conn.close()


def admin_update_movie(movie_id, data):
    """Update an existing movie. Returns (success, message)."""
    title = _clean(data.get("title"))
    if not title:
        return False, "Movie title is required."

    conn = get_connection()
    try:
        cur = conn.execute(
            """
            UPDATE movies
            SET title = ?,
                release_year = ?,
                genre = ?,
                director = ?,
                "cast" = ?,
                keywords = ?,
                overview = ?,
                vote_average = ?,
                vote_count = ?,
                popularity = ?,
                poster_url = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                title,
                _to_int(data.get("release_year")),
                _clean(data.get("genre")),
                _clean(data.get("director")),
                _clean(data.get("cast")),
                _clean(data.get("keywords")),
                _clean(data.get("overview")),
                _to_float(data.get("vote_average")),
                _to_int(data.get("vote_count"), 0),
                _to_float(data.get("popularity")),
                _clean(data.get("poster_url")),
                movie_id,
            ),
        )
        conn.commit()
        if cur.rowcount:
            return True, f"Movie '{title}' updated successfully."
        return False, f"Movie #{movie_id} not found."
    except sqlite3.Error as exc:
        conn.rollback()
        return False, f"Database error: {exc}"
    finally:
        conn.close()


def admin_delete_movie(movie_id):
    """Delete a movie and its favorite references. Returns (success, message)."""
    conn = get_connection()
    try:
        # Remove dependent favorites first for compatibility with SQLite foreign keys.
        conn.execute("DELETE FROM favorites WHERE movie_id = ?", (movie_id,))
        cur = conn.execute("DELETE FROM movies WHERE id = ?", (movie_id,))
        conn.commit()

        if cur.rowcount:
            return True, f"Movie #{movie_id} deleted successfully."
        return False, f"Movie #{movie_id} not found."
    except sqlite3.Error as exc:
        conn.rollback()
        return False, f"Database error: {exc}"
    finally:
        conn.close()
