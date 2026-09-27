"""
Content-based movie recommendation engine.

SQLite is the master movie catalog. The engine keeps the catalog and TF-IDF
matrix in memory and rebuilds them when reload_engine() is called.

Public API used by app.py:
    df
    initialize_engine()
    reload_engine()
    get_recommendations(movie_title, top_n=5)
"""

import re
import threading

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from database import get_all_movies_df


# These names are intentionally module-level because app.py reads recommendation_engine.df.
df = None
tfidf_matrix = None
similarity_matrix = None
vectorizer = None

_engine_lock = threading.RLock()


def _normalize_title(value):
    """Normalize a title for forgiving exact/partial matching."""
    value = "" if value is None else str(value).lower()
    return re.sub(r"[^a-z0-9]+", "", value)


def _safe_text(value):
    """Return clean text suitable for TF-IDF input."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _build_feature_text(dataframe):
    """
    Build the content representation used by the TF-IDF model.

    The project catalog contains title, genre, director, cast, keywords and
    overview. Missing values are converted to empty strings so incomplete
    admin entries cannot break vectorization.
    """
    text_columns = [
        "title",
        "genre",
        "director",
        "cast",
        "keywords",
        "overview",
    ]

    parts = []
    for column in text_columns:
        if column in dataframe.columns:
            parts.append(dataframe[column].map(_safe_text))
        else:
            parts.append(pd.Series([""] * len(dataframe), index=dataframe.index))

    combined = parts[0]
    for part in parts[1:]:
        combined = combined + " " + part

    return combined.str.replace(r"\s+", " ", regex=True).str.strip()


def initialize_engine(df_source=None):
    """
    Build the in-memory recommendation engine.

    If df_source is omitted, the current SQLite movie catalog is loaded.
    Returns the active DataFrame.
    """
    global df, tfidf_matrix, similarity_matrix, vectorizer

    source = get_all_movies_df() if df_source is None else df_source.copy()

    if source is None:
        source = pd.DataFrame()

    source = source.copy()

    # Keep a predictable schema even if the catalog is temporarily empty.
    required_columns = [
        "movie_id",
        "title",
        "release_year",
        "genre",
        "director",
        "cast",
        "keywords",
        "overview",
        "vote_average",
        "vote_count",
        "popularity",
        "poster_url",
    ]

    for column in required_columns:
        if column not in source.columns:
            source[column] = ""

    source = source[required_columns].copy()
    source["title"] = source["title"].map(_safe_text)

    feature_text = _build_feature_text(source)

    with _engine_lock:
        if source.empty:
            df = source
            vectorizer = None
            tfidf_matrix = None
            similarity_matrix = None
            return df

        new_vectorizer = TfidfVectorizer(stop_words="english")
        new_tfidf = new_vectorizer.fit_transform(feature_text)

        # The project uses an in-memory cosine-similarity matrix for fast
        # recommendation requests after the one-time/reload computation.
        new_similarity = cosine_similarity(new_tfidf)

        # Swap references only after the new structures are completely built.
        df = source
        vectorizer = new_vectorizer
        tfidf_matrix = new_tfidf
        similarity_matrix = new_similarity

    return df


def reload_engine():
    """Reload the movie catalog from SQLite and rebuild the TF-IDF index."""
    return initialize_engine()


def _resolve_title(movie_title):
    """
    Resolve a user title using the project's multi-tier matching strategy:
    exact -> normalized -> partial matching.

    Returns the matching DataFrame index or None.
    """
    if df is None or df.empty:
        return None

    query = _safe_text(movie_title)
    if not query:
        return None

    # Tier 1: case-insensitive exact title.
    exact = df[df["title"].map(lambda x: _safe_text(x).casefold() == query.casefold())]
    if not exact.empty:
        return exact.index[0]

    normalized_query = _normalize_title(query)

    # Tier 2: punctuation/hyphen/spacing-insensitive exact match.
    normalized = df[
        df["title"].map(lambda x: _normalize_title(x) == normalized_query)
    ]
    if not normalized.empty:
        return normalized.index[0]

    # Tier 3: safe partial matching in normalized form.
    if normalized_query:
        partial = df[
            df["title"].map(
                lambda x: normalized_query in _normalize_title(x)
                or _normalize_title(x) in normalized_query
            )
        ]
        if not partial.empty:
            # Prefer the shortest matching title for ambiguous partial queries.
            ranked = sorted(
                partial.index,
                key=lambda i: (
                    len(_safe_text(df.loc[i, "title"])),
                    _safe_text(df.loc[i, "title"]).casefold(),
                ),
            )
            return ranked[0]

    return None


def get_recommendations(movie_title, top_n=5):
    """
    Return top-N content-based recommendations.

    Response shape is compatible with app.py:
        {
            "status": "success",
            "query": original_query,
            "resolved_title": matched_title,
            "recommendations": [...]
        }
    """
    with _engine_lock:
        current_df = df
        current_similarity = similarity_matrix

        if current_df is None or current_df.empty or current_similarity is None:
            return {
                "status": "error",
                "message": "Recommendation engine is not initialized.",
            }

        target_index = _resolve_title(movie_title)

        if target_index is None:
            return {
                "status": "error",
                "message": f"Movie '{movie_title}' not found.",
            }

        position = current_df.index.get_loc(target_index)
        scores = current_similarity[position]

        candidates = []
        for pos, score in enumerate(scores):
            row_index = current_df.index[pos]

            # Never recommend the queried movie itself.
            if row_index == target_index:
                continue

            candidates.append((row_index, float(score)))

        # Stable deterministic ordering: score descending, then title.
        candidates.sort(
            key=lambda item: (
                -item[1],
                _safe_text(current_df.loc[item[0], "title"]).casefold(),
            )
        )

        limit = max(0, int(top_n))
        selected = candidates[:limit]

        recommendations = []
        for row_index, score in selected:
            row = current_df.loc[row_index]

            recommendations.append(
                {
                    "movie_id": int(row["movie_id"]),
                    "title": _safe_text(row["title"]),
                    "release_year": (
                        int(row["release_year"])
                        if pd.notna(row["release_year"])
                        and str(row["release_year"]).strip() != ""
                        else None
                    ),
                    "genre": _safe_text(row["genre"]),
                    "director": _safe_text(row["director"]),
                    "cast": _safe_text(row["cast"]),
                    "keywords": _safe_text(row["keywords"]),
                    "overview": _safe_text(row["overview"]),
                    "vote_average": (
                        float(row["vote_average"])
                        if pd.notna(row["vote_average"])
                        else 0.0
                    ),
                    "vote_count": (
                        int(row["vote_count"])
                        if pd.notna(row["vote_count"])
                        else 0
                    ),
                    "popularity": (
                        float(row["popularity"])
                        if pd.notna(row["popularity"])
                        else 0.0
                    ),
                    "similarity_score": round(score, 4),
                }
            )

        return {
            "status": "success",
            "query": movie_title,
            "resolved_title": _safe_text(current_df.loc[target_index, "title"]),
            "recommendations": recommendations,
        }


# Build the initial engine when the module is imported.
initialize_engine()
