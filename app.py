"""
Movie Recommendation System - Flask Application Entry Point
============================================================
This is the Flask backend entry point for the Movie Recommendation System.

Stage 11: Genre Filtering & Browsing Support
"""

import os
import re
from functools import wraps
import pandas as pd
from flask import Flask, jsonify, render_template, request, session, redirect, url_for
from werkzeug.security import generate_password_hash, check_password_hash

# Import database initialization, user, favorites, and admin operations
from database import (
    init_db,
    seed_movies_from_csv_if_empty,
    create_user,
    get_user_by_username,
    get_user_by_email,
    is_user_admin,
    promote_user_to_admin,
    add_favorite,
    remove_favorite,
    get_user_favorite_movie_ids,
    is_movie_favorite,
    admin_get_all_movies,
    admin_get_movie_by_id,
    admin_add_movie,
    admin_update_movie,
    admin_delete_movie
)

# Import recommendation engine and dynamic reloader
import recommendation_engine
from recommendation_engine import get_recommendations, reload_engine

# Initialize the Flask application instance
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key-movie-rec-system-2026")

# Initialize the SQLite database schema on startup and seed if empty
init_db()
seed_movies_from_csv_if_empty()


def admin_required(f):
    """
    Decorator to restrict route access strictly to authenticated administrators.
    Checks session user_id against SQLite is_admin status.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id or not is_user_admin(user_id):
            if request.is_json:
                return jsonify({"status": "error", "message": "Unauthorized: Administrator access required."}), 403
            return render_template("login.html", message="Administrator access required. Please log in with an admin account.", form_data={}), 403
        return f(*args, **kwargs)
    return decorated_function


# ---------------------------------------------------------
# Dynamic Application Movie Metadata Cache
# ---------------------------------------------------------
poster_map = {}
overview_map = {}
movies_by_id = {}
available_genres = []


def refresh_app_movie_cache():
    """
    Refreshes in-memory movie lookup mappings and unique genre lists
    from the active recommendation engine DataFrame.
    """
    global poster_map, overview_map, movies_by_id, available_genres
    current_df = recommendation_engine.df
    if current_df is None:
        return

    poster_map = {
        int(row['movie_id']): str(row['poster_url']).strip() if pd.notnull(row['poster_url']) else ""
        for _, row in current_df.iterrows()
    }
    overview_map = {
        int(row['movie_id']): str(row['overview']).strip() if pd.notnull(row['overview']) else "Not available"
        for _, row in current_df.iterrows()
    }
    movies_by_id = {
        int(row['movie_id']): {
            'movie_id': int(row['movie_id']),
            'title': str(row['title']),
            'release_year': int(row['release_year']) if pd.notnull(row['release_year']) and str(row['release_year']).isdigit() else (int(row['release_year']) if isinstance(row['release_year'], (int, float)) and not pd.isna(row['release_year']) else None),
            'genre': str(row['genre']) if pd.notnull(row['genre']) and str(row['genre']).strip() != '' else 'Not available',
            'director': str(row['director']) if pd.notnull(row['director']) and str(row['director']).strip() != '' else 'Not available',
            'cast': str(row['cast']) if pd.notnull(row['cast']) and str(row['cast']).strip() != '' else 'Not available',
            'overview': str(row['overview']) if pd.notnull(row['overview']) and str(row['overview']).strip() != '' else 'Not available',
            'poster_url': str(row['poster_url']).strip() if pd.notnull(row['poster_url']) else '',
            'vote_average': float(row['vote_average']) if pd.notnull(row['vote_average']) else 0.0,
            'vote_count': int(row['vote_count']) if pd.notnull(row['vote_count']) else 0
        } for _, row in current_df.iterrows()
    }

    unique_genres_set = set()
    for genre_str in current_df['genre'].dropna():
        for g in str(genre_str).split(','):
            clean_g = g.strip()
            if clean_g:
                unique_genres_set.add(clean_g)
    available_genres = sorted(list(unique_genres_set))


# Populate initial in-memory cache
refresh_app_movie_cache()


# ---------------------------------------------------------
# Route 1: Home Page (Movie Search & Genre Filter UI)
# ---------------------------------------------------------
@app.route("/", methods=["GET"])
def home():
    """
    Renders the main movie search and genre filter frontend page (index.html).
    """
    return render_template("index.html", genres=available_genres)


# ---------------------------------------------------------
# Route 2: Dynamic Genres List API
# ---------------------------------------------------------
@app.route("/api/genres", methods=["GET"])
def get_genres():
    """
    Returns the list of all dynamically extracted genres.
    """
    return jsonify({"status": "success", "genres": available_genres}), 200


# ---------------------------------------------------------
# Route 3: Movies by Genre Endpoint
# ---------------------------------------------------------
@app.route("/movies/by-genre/<string:genre_name>", methods=["GET"])
def get_movies_by_genre(genre_name):
    """
    Returns popular movies belonging to a specified genre,
    or top overall popular movies if 'all' is requested.
    """
    cleaned_genre = genre_name.strip()
    
    if cleaned_genre.lower() in ["all", "all genres"]:
        # Return top popular movies across all genres
        top_movies = sorted(
            movies_by_id.values(),
            key=lambda x: x['vote_count'],
            reverse=True
        )[:15]
        return jsonify({
            "status": "success",
            "genre": "All Genres",
            "total_matches": len(top_movies),
            "movies": top_movies
        }), 200

    # Filter movies where genre matches (case-insensitive substring/item match)
    matching_movies = []
    genre_lower = cleaned_genre.lower()
    for m in movies_by_id.values():
        m_genres = [g.strip().lower() for g in m['genre'].split(',')]
        if genre_lower in m_genres or genre_lower in m['genre'].lower():
            matching_movies.append(m)

    if not matching_movies:
        return jsonify({
            "status": "error",
            "message": f"No movies found for genre '{genre_name}'."
        }), 404

    # Sort matching movies by popularity/vote_count descending
    matching_movies.sort(key=lambda x: x['vote_count'], reverse=True)
    top_genre_movies = matching_movies[:15]

    return jsonify({
        "status": "success",
        "genre": cleaned_genre,
        "total_matches": len(top_genre_movies),
        "movies": top_genre_movies
    }), 200


# ---------------------------------------------------------
# Route 4: Movie Recommendation Endpoint
# ---------------------------------------------------------
@app.route("/recommend/<string:movie_title>", methods=["GET"])
def recommend_movie(movie_title):
    """
    API endpoint to generate top 5 content-based movie recommendations
    for a given movie title, attaching poster_url and overview to each recommendation.
    """
    result = get_recommendations(movie_title, top_n=5)
    
    if result["status"] == "success":
        for rec in result["recommendations"]:
            rec["poster_url"] = poster_map.get(rec["movie_id"], "")
            rec["overview"] = overview_map.get(rec["movie_id"], "Not available")
            
        return jsonify(result), 200
    else:
        return jsonify(result), 404


# ---------------------------------------------------------
# Route 5: User Registration Endpoint
# ---------------------------------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "GET":
        return render_template("register.html", success=False, message=None, form_data={})

    if request.is_json:
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        email = data.get("email", "").strip()
        password = data.get("password", "")
        confirm_password = data.get("confirm_password", "")
    else:
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

    form_data = {"username": username, "email": email}

    if not username or not email or not password or not confirm_password:
        error_msg = "All fields (Username, Email, Password, Confirm Password) are required."
        if request.is_json:
            return jsonify({"status": "error", "message": error_msg}), 400
        return render_template("register.html", success=False, message=error_msg, form_data=form_data), 400

    email_regex = r"^[\w\.\+\-]+@[\w\-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_regex, email):
        error_msg = "Please enter a valid email address format (e.g., user@example.com)."
        if request.is_json:
            return jsonify({"status": "error", "message": error_msg}), 400
        return render_template("register.html", success=False, message=error_msg, form_data=form_data), 400

    if password != confirm_password:
        error_msg = "Passwords do not match. Please ensure both password fields are identical."
        if request.is_json:
            return jsonify({"status": "error", "message": error_msg}), 400
        return render_template("register.html", success=False, message=error_msg, form_data=form_data), 400

    if len(password) < 6:
        error_msg = "Password must be at least 6 characters long."
        if request.is_json:
            return jsonify({"status": "error", "message": error_msg}), 400
        return render_template("register.html", success=False, message=error_msg, form_data=form_data), 400

    if get_user_by_username(username):
        error_msg = f"Username '{username}' is already registered. Please choose another username."
        if request.is_json:
            return jsonify({"status": "error", "message": error_msg}), 409
        return render_template("register.html", success=False, message=error_msg, form_data=form_data), 409

    if get_user_by_email(email):
        error_msg = f"Email '{email}' is already registered. Please use another email."
        if request.is_json:
            return jsonify({"status": "error", "message": error_msg}), 409
        return render_template("register.html", success=False, message=error_msg, form_data=form_data), 409

    password_hash = generate_password_hash(password)
    success, db_msg = create_user(username, email, password_hash)
    if not success:
        if request.is_json:
            return jsonify({"status": "error", "message": db_msg}), 500
        return render_template("register.html", success=False, message=db_msg, form_data=form_data), 500

    success_msg = f"Account for '{username}' created successfully! You are now registered."
    if request.is_json:
        return jsonify({"status": "success", "message": success_msg, "username": username, "email": email}), 201

    return render_template("register.html", success=True, message=success_msg, form_data={}), 201


# ---------------------------------------------------------
# Route 6: User Login Endpoint
# ---------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if "user_id" in session:
            return redirect(url_for("home"))
        return render_template("login.html", message=None, form_data={})

    if request.is_json:
        data = request.get_json() or {}
        username = data.get("username", "").strip()
        password = data.get("password", "")
    else:
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

    form_data = {"username": username}

    if not username or not password:
        error_msg = "Please enter both username and password."
        if request.is_json:
            return jsonify({"status": "error", "message": error_msg}), 400
        return render_template("login.html", message=error_msg, form_data=form_data), 400

    user = get_user_by_username(username)

    if not user or not check_password_hash(user["password_hash"], password):
        error_msg = "Invalid username or password."
        if request.is_json:
            return jsonify({"status": "error", "message": error_msg}), 401
        return render_template("login.html", message=error_msg, form_data=form_data), 401

    session["user_id"] = user["id"]
    session["username"] = user["username"]
    session["is_admin"] = bool(user.get("is_admin", 0))

    if request.is_json:
        return jsonify({
            "status": "success",
            "message": "Login successful!",
            "user": {
                "id": user["id"],
                "username": user["username"],
                "email": user["email"],
                "is_admin": bool(user.get("is_admin", 0))
            }
        }), 200

    return redirect(url_for("home"))


# ---------------------------------------------------------
# Route 7: User Logout Endpoint
# ---------------------------------------------------------
@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    if request.is_json:
        return jsonify({"status": "success", "message": "Logged out successfully."}), 200
    return redirect(url_for("home"))


# ---------------------------------------------------------
# Route 8: Favorites Management Endpoints
# ---------------------------------------------------------
@app.route("/favorites", methods=["GET"])
def favorites_page():
    if "user_id" not in session:
        return redirect(url_for("login"))

    user_id = session["user_id"]
    fav_movie_ids = get_user_favorite_movie_ids(user_id)
    user_favorites = [movies_by_id[mid] for mid in fav_movie_ids if mid in movies_by_id]

    return render_template("favorites.html", favorites=user_favorites)


@app.route("/favorites/check/<int:movie_id>", methods=["GET"])
def check_favorite_status(movie_id):
    if "user_id" not in session:
        return jsonify({"logged_in": False, "is_favorite": False}), 200

    user_id = session["user_id"]
    fav_status = is_movie_favorite(user_id, movie_id)
    return jsonify({"logged_in": True, "is_favorite": fav_status}), 200


@app.route("/favorites/add", methods=["POST"])
def add_to_favorites():
    if "user_id" not in session:
        return jsonify({"status": "error", "message": "Please log in to add favorites."}), 401

    if request.is_json:
        data = request.get_json() or {}
        movie_id = data.get("movie_id")
    else:
        movie_id = request.form.get("movie_id")

    try:
        movie_id = int(movie_id)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid movie ID."}), 400

    if movie_id not in movies_by_id:
        return jsonify({"status": "error", "message": "Movie not found in dataset."}), 404

    user_id = session["user_id"]
    success, msg = add_favorite(user_id, movie_id)
    status_code = 200 if success else 409

    return jsonify({"status": "success" if success else "error", "message": msg, "movie_id": movie_id}), status_code


@app.route("/favorites/remove", methods=["POST"])
def remove_from_favorites():
    if "user_id" not in session:
        return jsonify({"status": "error", "message": "Please log in to remove favorites."}), 401

    if request.is_json:
        data = request.get_json() or {}
        movie_id = data.get("movie_id")
    else:
        movie_id = request.form.get("movie_id")

    try:
        movie_id = int(movie_id)
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Invalid movie ID."}), 400

    user_id = session["user_id"]
    success, msg = remove_favorite(user_id, movie_id)
    status_code = 200 if success else 404

    return jsonify({"status": "success" if success else "error", "message": msg, "movie_id": movie_id}), status_code


# ---------------------------------------------------------
# Route 9: Admin Dashboard & Movie Management (Stage 12)
# ---------------------------------------------------------
@app.route("/admin", methods=["GET"])
@admin_required
def admin_dashboard():
    """
    Renders the admin dashboard with full listing of movies from SQLite table.
    Restricted strictly to users with is_admin == 1.
    """
    movies = admin_get_all_movies()
    return render_template("admin.html", movies=movies)


@app.route("/admin/movies/add", methods=["POST"])
@admin_required
def admin_add_movie_route():
    """
    Adds a new movie record to the SQLite movies table.
    """
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form.to_dict()

    success, msg, new_id = admin_add_movie(data)
    if not success:
        if request.is_json:
            return jsonify({"status": "error", "message": msg}), 400
        movies = admin_get_all_movies()
        return render_template("admin.html", movies=movies, message=msg, success=False), 400

    # On successful add, reload recommendation engine and movie metadata cache
    reload_engine()
    refresh_app_movie_cache()

    if request.is_json:
        return jsonify({"status": "success", "message": msg, "movie_id": new_id}), 201

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/movies/get/<int:movie_id>", methods=["GET"])
@admin_required
def admin_get_movie_route(movie_id):
    """
    Returns single movie JSON details for populating the edit modal.
    """
    movie = admin_get_movie_by_id(movie_id)
    if not movie:
        return jsonify({"status": "error", "message": f"Movie #{movie_id} not found."}), 404
    return jsonify({"status": "success", "movie": movie}), 200


@app.route("/admin/movies/edit/<int:movie_id>", methods=["POST"])
@admin_required
def admin_edit_movie_route(movie_id):
    """
    Updates an existing movie record in the SQLite movies table.
    """
    if request.is_json:
        data = request.get_json() or {}
    else:
        data = request.form.to_dict()

    success, msg = admin_update_movie(movie_id, data)
    if not success:
        if request.is_json:
            return jsonify({"status": "error", "message": msg}), 400
        movies = admin_get_all_movies()
        return render_template("admin.html", movies=movies, message=msg, success=False), 400

    # On successful update, reload recommendation engine and movie metadata cache
    reload_engine()
    refresh_app_movie_cache()

    if request.is_json:
        return jsonify({"status": "success", "message": msg, "movie_id": movie_id}), 200

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/movies/delete/<int:movie_id>", methods=["POST"])
@admin_required
def admin_delete_movie_route(movie_id):
    """
    Deletes a movie record from the SQLite movies table.
    """
    success, msg = admin_delete_movie(movie_id)
    if success:
        # On successful deletion, reload recommendation engine and movie metadata cache
        reload_engine()
        refresh_app_movie_cache()
        return jsonify({"status": "success", "message": msg, "movie_id": movie_id}), 200
    else:
        return jsonify({"status": "error", "message": msg, "movie_id": movie_id}), 404


if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
