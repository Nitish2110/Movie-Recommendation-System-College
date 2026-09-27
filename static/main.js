/**
 * Movie Recommendation System - Client-side Controller & Modal Manager
 * ====================================================================
 * Connects the frontend search form to the Flask /recommend/<title> API,
 * manages dynamic genre pills browsing via /movies/by-genre/<genre>,
 * renders high-resolution posters, movie cards with rating badges,
 * recommendation cards with similarity progress bars, and modal favorites.
 */

document.addEventListener("DOMContentLoaded", () => {
    const searchForm = document.getElementById("search_form");
    const movieInput = document.getElementById("movie_title");
    const genreSelect = document.getElementById("genre_select");
    const genrePillsBar = document.getElementById("genre_pills_bar");
    const navGenresLink = document.getElementById("nav_genres_link");
    const resultsContainer = document.getElementById("results_container");
    const modal = document.getElementById("movie_modal");
    const modalContent = document.getElementById("modal_content");
    const modalCloseBtn = document.getElementById("modal_close_btn");

    // In-memory cache of current displayed movies for modal binding
    let currentMovies = [];

    // ---------------------------------------------------------
    // Utility: High-Resolution Poster URL Transformer
    // ---------------------------------------------------------
    function getHighResPosterUrl(url) {
        if (!url || typeof url !== "string" || url.trim() === "" || url.trim() === "nan") {
            return "";
        }
        const trimmed = url.trim();

        // 1. Amazon / IMDb CDN (replaces low-res thumbnails like _UX67_, _UY98_ with high-res 500px)
        if (trimmed.includes("media-amazon.com") || trimmed.includes("imdb.com")) {
            return trimmed.replace(/\._V1_.*\.jpg$/i, "._V1_FMjpg_UX500_.jpg");
        }

        // 2. TMDB CDN (upgrades w185/w342 to w500)
        if (trimmed.includes("image.tmdb.org/t/p/")) {
            return trimmed.replace(/\/t\/p\/w\d+\//i, "/t/p/w500/");
        }

        return trimmed;
    }

    // Helper to generate resilient poster HTML with high-res upgrade & graceful fallback
    function generatePosterHtml(movie, cssClass = "movie-poster") {
        const origUrl = (movie.poster_url && typeof movie.poster_url === "string" && movie.poster_url !== "nan") 
            ? movie.poster_url.trim() 
            : "";
            
        if (!origUrl) {
            return `<div class="poster-placeholder"><span>🎬</span><small>No Poster</small></div>`;
        }

        const highResUrl = getHighResPosterUrl(origUrl);

        return `
            <img 
                src="${highResUrl}" 
                alt="${movie.title} Poster" 
                class="${cssClass}" 
                loading="lazy"
                data-original="${origUrl}"
                onerror="if(this.dataset.original && this.src !== this.dataset.original) { this.src=this.dataset.original; } else { this.onerror=null; this.parentElement.innerHTML='<div class=\\'poster-placeholder\\'><span>🎬</span><small>No Poster</small></div>'; }"
            >
        `;
    }

    // ---------------------------------------------------------
    // Initial Load: Auto-fetch Popular / Discover Movies
    // ---------------------------------------------------------
    loadPopularDiscoverMovies();

    async function loadPopularDiscoverMovies() {
        resultsContainer.innerHTML = `
            <div class="message-card loading-card">
                <div class="spinner"></div>
                <span>Curating popular & trending movies from the catalog...</span>
            </div>
        `;

        try {
            const response = await fetch("/movies/by-genre/all");
            const data = await response.json();

            if (response.ok && data.status === "success") {
                currentMovies = data.movies || [];
                renderDiscoverSection(currentMovies);
            } else {
                currentMovies = [];
                resultsContainer.innerHTML = "";
            }
        } catch (error) {
            console.error("Error loading discover movies:", error);
            resultsContainer.innerHTML = "";
        }
    }

    // ---------------------------------------------------------
    // 1. Movie Search & Recommendations Handler (TF-IDF + Cosine Sim)
    // ---------------------------------------------------------
    if (searchForm) {
        searchForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            
            const rawTitle = movieInput ? movieInput.value.trim() : "";
            if (!rawTitle) {
                const selectedGenre = genreSelect ? genreSelect.value : "all";
                if (selectedGenre && selectedGenre !== "all") {
                    browseMoviesByGenre(selectedGenre);
                    return;
                }
                resultsContainer.innerHTML = `
                    <div class="message-card error-card">
                        <h3>Input Required</h3>
                        <p>Please enter a movie title to get content recommendations, or choose a genre from the pills above.</p>
                    </div>
                `;
                return;
            }

            // Display loading indicator
            resultsContainer.innerHTML = `
                <div class="message-card loading-card">
                    <div class="spinner"></div>
                    <span>Analyzing TF-IDF vectors & calculating cosine similarities for "${rawTitle}"...</span>
                </div>
            `;

            try {
                const encodedTitle = encodeURIComponent(rawTitle);
                const response = await fetch(`/recommend/${encodedTitle}`);
                const data = await response.json();

                if (response.ok && data.status === "success") {
                    currentMovies = data.recommendations || [];
                    renderRecommendations(data.query_movie, currentMovies);
                } else {
                    currentMovies = [];
                    renderError(data.message || `Movie "${rawTitle}" not found in the dataset.`);
                }
            } catch (error) {
                currentMovies = [];
                renderError("An error occurred while communicating with the server. Please try again.");
                console.error("Fetch error:", error);
            }
        });
    }

    // ---------------------------------------------------------
    // 2. Dynamic Genre Pills Navigation Handler
    // ---------------------------------------------------------
    if (genrePillsBar) {
        genrePillsBar.addEventListener("click", (e) => {
            const pill = e.target.closest(".genre-pill");
            if (!pill) return;

            const selectedGenre = pill.getAttribute("data-genre") || "all";

            // Update active state across pills
            genrePillsBar.querySelectorAll(".genre-pill").forEach(p => p.classList.remove("active"));
            pill.classList.add("active");

            // Sync hidden select if exists
            if (genreSelect) {
                genreSelect.value = selectedGenre;
            }

            // Fetch and render movies for genre
            if (selectedGenre === "all") {
                loadPopularDiscoverMovies();
            } else {
                browseMoviesByGenre(selectedGenre);
            }
        });
    }

    // Quick anchor smooth scroll for "Browse by Genre" nav link
    if (navGenresLink) {
        navGenresLink.addEventListener("click", (e) => {
            e.preventDefault();
            const genreSec = document.getElementById("genre_section");
            if (genreSec) {
                genreSec.scrollIntoView({ behavior: "smooth", block: "center" });
            }
        });
    }

    async function browseMoviesByGenre(genre) {
        const displayLabel = genre === "all" ? "All Genres" : genre;
        resultsContainer.innerHTML = `
            <div class="message-card loading-card">
                <div class="spinner"></div>
                <span>Fetching top movies in genre "${displayLabel}"...</span>
            </div>
        `;

        try {
            const encodedGenre = encodeURIComponent(genre);
            const response = await fetch(`/movies/by-genre/${encodedGenre}`);
            const data = await response.json();

            if (response.ok && data.status === "success") {
                currentMovies = data.movies || [];
                renderGenreMovies(data.genre, currentMovies);
            } else {
                currentMovies = [];
                renderError(data.message || `No movies found for genre "${genre}".`);
            }
        } catch (error) {
            currentMovies = [];
            renderError("An error occurred while fetching genre movies. Please try again.");
            console.error("Fetch error:", error);
        }
    }

    // ---------------------------------------------------------
    // 3. Render Discover / Popular Movies Grid (5–6 cols desktop)
    // ---------------------------------------------------------
    function renderDiscoverSection(movies) {
        if (!movies || movies.length === 0) return;

        let html = `
            <div class="results-header discover-header">
                <div class="results-header-info">
                    <h2 class="section-title"><span class="title-icon">🔥</span> Discover Popular Movies</h2>
                    <p class="section-desc">Explore some of the most popular and highly rated movies across the catalogue.</p>
                </div>
            </div>
            <div class="movies-cards-grid">
        `;

        movies.forEach((movie, index) => {
            const posterHtml = generatePosterHtml(movie, "movie-poster");
            const ratingVal = movie.vote_average ? Number(movie.vote_average).toFixed(1) : "N/A";
            const primaryGenre = (movie.genre || "Cinema").split(",")[0].trim();

            html += `
                <div class="movie-grid-card interactive-card" data-index="${index}" role="button" tabindex="0" title="Click to view full details for ${movie.title}">
                    <div class="movie-poster-wrapper">
                        ${posterHtml}
                        <div class="card-overlay-badge rating-badge">★ ${ratingVal}</div>
                    </div>
                    <div class="movie-grid-info">
                        <h3 class="movie-title">${movie.title}</h3>
                        <div class="movie-meta-row">
                            <span class="movie-year">${movie.release_year || 'N/A'}</span>
                            <span class="meta-dot">&bull;</span>
                            <span class="movie-genre-tag">${primaryGenre}</span>
                        </div>
                    </div>
                </div>
            `;
        });

        html += `</div>`;
        resultsContainer.innerHTML = html;
        attachCardListeners();
    }

    // ---------------------------------------------------------
    // 4. Render Recommendation Cards (with Similarity Progress Bars)
    // ---------------------------------------------------------
    function renderRecommendations(queryTitle, recommendations) {
        if (!recommendations || recommendations.length === 0) {
            renderError(`No recommendations found for "${queryTitle}".`);
            return;
        }

        let html = `
            <div class="results-header">
                <div class="results-header-info">
                    <h2 class="section-title"><span class="title-icon">🎯</span> Top Recommendations for <span class="highlight">"${queryTitle}"</span></h2>
                    <p class="section-desc">Calculated via TF-IDF vectorization & Cosine Similarity across overview, genres, cast, director, and keywords</p>
                </div>
                <button type="button" class="btn-back-discover" id="btn_back_discover">
                    &larr; Discover Popular
                </button>
            </div>
            <div class="recommendations-list">
        `;

        recommendations.forEach((movie, index) => {
            const posterHtml = generatePosterHtml(movie, "movie-poster");
            const ratingVal = movie.vote_average ? Number(movie.vote_average).toFixed(1) : "N/A";
            const rawScore = Number(movie.similarity_score) || 0;
            const simPercentage = (rawScore * 100).toFixed(2);
            // Visual progress bar fill width (normalized scale min 10% for visual visibility)
            const progressWidth = Math.min(100, Math.max(10, rawScore * 250));

            html += `
                <div class="movie-card interactive-card" data-index="${index}" role="button" tabindex="0" title="Click to view details for ${movie.title}">
                    <div class="movie-poster-wrapper">
                        ${posterHtml}
                        <div class="movie-rank-badge">#${index + 1}</div>
                        <div class="card-overlay-badge rating-badge">★ ${ratingVal}</div>
                    </div>
                    <div class="movie-info">
                        <div class="movie-title-row">
                            <h3 class="movie-title">${movie.title}</h3>
                            <span class="movie-year">(${movie.release_year || 'N/A'})</span>
                        </div>
                        <p class="movie-meta"><strong>Genre:</strong> ${movie.genre || 'Not available'}</p>
                        <p class="movie-meta"><strong>Director:</strong> ${movie.director || 'Not available'}</p>
                        <p class="movie-meta"><strong>Cast:</strong> ${movie.cast || 'Not available'}</p>

                        <!-- Visual Similarity Progress Bar -->
                        <div class="similarity-progress-box">
                            <div class="sim-header-row">
                                <span class="sim-title">Similarity Match</span>
                                <span class="sim-value">${simPercentage}%</span>
                            </div>
                            <div class="sim-progress-track">
                                <div class="sim-progress-bar" style="width: ${progressWidth}%;"></div>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });

        html += `</div>`;
        resultsContainer.innerHTML = html;
        attachCardListeners();

        // Attach Back to Popular button
        const backBtn = document.getElementById("btn_back_discover");
        if (backBtn) {
            backBtn.addEventListener("click", () => {
                if (movieInput) movieInput.value = "";
                loadPopularDiscoverMovies();
            });
        }
    }

    // ---------------------------------------------------------
    // 5. Render Genre Browsing Cards
    // ---------------------------------------------------------
    function renderGenreMovies(genreTitle, movies) {
        if (!movies || movies.length === 0) {
            renderError(`No movies found for genre "${genreTitle}".`);
            return;
        }

        const displayGenre = genreTitle.toLowerCase() === "all" ? "All Genres" : genreTitle;

        let html = `
            <div class="results-header">
                <div class="results-header-info">
                    <h2 class="section-title"><span class="title-icon">🎬</span> Browsing: <span class="highlight">"${displayGenre}"</span></h2>
                    <p class="section-desc">Showing ${movies.length} highly popular titles in this category</p>
                </div>
                <button type="button" class="btn-back-discover" id="btn_back_discover_genre">
                    &larr; Discover Popular
                </button>
            </div>
            <div class="movies-cards-grid">
        `;

        movies.forEach((movie, index) => {
            const posterHtml = generatePosterHtml(movie, "movie-poster");
            const ratingVal = movie.vote_average ? Number(movie.vote_average).toFixed(1) : "N/A";
            const primaryGenre = (movie.genre || displayGenre).split(",")[0].trim();

            html += `
                <div class="movie-grid-card interactive-card" data-index="${index}" role="button" tabindex="0" title="Click to view details for ${movie.title}">
                    <div class="movie-poster-wrapper">
                        ${posterHtml}
                        <div class="card-overlay-badge rating-badge">★ ${ratingVal}</div>
                    </div>
                    <div class="movie-grid-info">
                        <h3 class="movie-title">${movie.title}</h3>
                        <div class="movie-meta-row">
                            <span class="movie-year">${movie.release_year || 'N/A'}</span>
                            <span class="meta-dot">&bull;</span>
                            <span class="movie-genre-tag">${primaryGenre}</span>
                        </div>
                    </div>
                </div>
            `;
        });

        html += `</div>`;
        resultsContainer.innerHTML = html;
        attachCardListeners();

        const backBtn = document.getElementById("btn_back_discover_genre");
        if (backBtn) {
            backBtn.addEventListener("click", () => {
                if (genrePillsBar) {
                    genrePillsBar.querySelectorAll(".genre-pill").forEach(p => p.classList.remove("active"));
                    const allPill = genrePillsBar.querySelector('[data-genre="all"]');
                    if (allPill) allPill.classList.add("active");
                }
                loadPopularDiscoverMovies();
            });
        }
    }

    // ---------------------------------------------------------
    // 6. Attach Click & Key Listeners to Movie Cards
    // ---------------------------------------------------------
    function attachCardListeners() {
        const cards = resultsContainer.querySelectorAll(".interactive-card");
        cards.forEach(card => {
            card.addEventListener("click", () => {
                const idx = parseInt(card.getAttribute("data-index"), 10);
                openMovieDetailsModal(currentMovies[idx]);
            });
            card.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    const idx = parseInt(card.getAttribute("data-index"), 10);
                    openMovieDetailsModal(currentMovies[idx]);
                }
            });
        });
    }

    // ---------------------------------------------------------
    // 7. Render Error Message
    // ---------------------------------------------------------
    function renderError(message) {
        resultsContainer.innerHTML = `
            <div class="message-card error-card">
                <div class="error-header-row">
                    <span class="error-icon">⚠️</span>
                    <h3>Movie Not Found</h3>
                </div>
                <p>${message}</p>
                <div style="margin-top: 14px;">
                    <button type="button" class="btn-back-discover" id="btn_error_back">
                        &larr; Return to Discover
                    </button>
                </div>
            </div>
        `;
        const errBack = document.getElementById("btn_error_back");
        if (errBack) {
            errBack.addEventListener("click", () => {
                if (movieInput) movieInput.value = "";
                loadPopularDiscoverMovies();
            });
        }
    }

    // ---------------------------------------------------------
    // 8. Modal Controller Logic with Favorites Support
    // ---------------------------------------------------------
    async function openMovieDetailsModal(movie) {
        if (!movie) return;

        const posterHtml = generatePosterHtml(movie, "modal-poster-img");
        const voteAvg = movie.vote_average ? Number(movie.vote_average).toFixed(1) : "N/A";
        const simScore = movie.similarity_score ? (movie.similarity_score * 100).toFixed(2) + "%" : null;

        modalContent.innerHTML = `
            <div class="modal-grid">
                <div class="modal-poster-col">
                    <div class="modal-poster-wrapper">
                        ${posterHtml}
                    </div>
                </div>
                <div class="modal-info-col">
                    <div class="modal-header-row">
                        <h2 class="modal-movie-title">${movie.title || 'Unknown Title'}</h2>
                        <span class="modal-release-year">(${movie.release_year || 'N/A'})</span>
                    </div>

                    <div class="modal-badges-row">
                        <div class="modal-badge rating-badge">
                            <span class="modal-badge-label">User Rating</span>
                            <span class="modal-badge-val">★ ${voteAvg} / 10</span>
                        </div>
                        ${simScore ? `
                        <div class="modal-badge sim-badge">
                            <span class="modal-badge-label">Match</span>
                            <span class="modal-badge-val">${simScore}</span>
                        </div>` : ''}
                    </div>

                    <div class="modal-field-group">
                        <p class="modal-field"><strong>Genre:</strong> ${movie.genre || 'Not available'}</p>
                        <p class="modal-field"><strong>Director:</strong> ${movie.director || 'Not available'}</p>
                        <p class="modal-field"><strong>Cast:</strong> ${movie.cast || 'Not available'}</p>
                    </div>

                    <div class="modal-overview-section">
                        <h4>Overview</h4>
                        <p class="modal-overview-text">${movie.overview || 'Not available'}</p>
                    </div>

                    <div class="modal-fav-action">
                        <button id="modal_fav_btn" class="btn-fav" data-movie-id="${movie.movie_id}">
                            <span>❤️ Add to Favorites</span>
                        </button>
                        <div id="modal_fav_feedback" class="fav-status-feedback"></div>
                    </div>
                </div>
            </div>
        `;

        // Check favorite status from backend
        checkFavoriteStatus(movie.movie_id);

        // Open modal
        modal.classList.add("active");
        modal.setAttribute("aria-hidden", "false");
        document.body.style.overflow = "hidden";
    }

    async function checkFavoriteStatus(movieId) {
        const favBtn = document.getElementById("modal_fav_btn");
        if (!favBtn) return;

        try {
            const res = await fetch(`/favorites/check/${movieId}`);
            const data = await res.json();

            if (data.is_favorite) {
                favBtn.classList.add("btn-fav-active");
                favBtn.innerHTML = `<span>💔 Remove from Favorites</span>`;
            } else {
                favBtn.classList.remove("btn-fav-active");
                favBtn.innerHTML = `<span>❤️ Add to Favorites</span>`;
            }

            favBtn.onclick = () => toggleFavorite(movieId, data.logged_in);
        } catch (err) {
            console.error("Error checking favorite status:", err);
        }
    }

    async function toggleFavorite(movieId, isLoggedIn) {
        const favBtn = document.getElementById("modal_fav_btn");
        const feedback = document.getElementById("modal_fav_feedback");
        if (!favBtn) return;

        const isCurrentlyFav = favBtn.classList.contains("btn-fav-active");
        const endpoint = isCurrentlyFav ? "/favorites/remove" : "/favorites/add";

        try {
            const response = await fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ movie_id: movieId })
            });

            const data = await response.json();

            if (response.status === 401) {
                feedback.innerHTML = `<span style="color: #f87171;">⚠️ Please <a href="/login" style="color: #38bdf8; text-decoration: underline;">log in</a> to save favorites.</span>`;
                return;
            }

            if (response.ok && data.status === "success") {
                if (isCurrentlyFav) {
                    favBtn.classList.remove("btn-fav-active");
                    favBtn.innerHTML = `<span>❤️ Add to Favorites</span>`;
                    feedback.innerHTML = `<span style="color: #94a3b8;">Removed from favorites.</span>`;
                } else {
                    favBtn.classList.add("btn-fav-active");
                    favBtn.innerHTML = `<span>💔 Remove from Favorites</span>`;
                    feedback.innerHTML = `<span style="color: #4ade80;">Saved to favorites!</span>`;
                }
                setTimeout(() => {
                    if (feedback) feedback.innerHTML = "";
                }, 2500);
            } else {
                feedback.innerHTML = `<span style="color: #fca5a5;">${data.message || 'Action failed.'}</span>`;
            }
        } catch (err) {
            console.error("Favorite toggle error:", err);
            feedback.innerHTML = `<span style="color: #fca5a5;">Network error occurred.</span>`;
        }
    }

    function closeModal() {
        modal.classList.remove("active");
        modal.setAttribute("aria-hidden", "true");
        document.body.style.overflow = "";
    }

    if (modalCloseBtn) {
        modalCloseBtn.addEventListener("click", closeModal);
    }

    if (modal) {
        modal.addEventListener("click", (e) => {
            if (e.target === modal) {
                closeModal();
            }
        });
    }

    document.addEventListener("keydown", (e) => {
        if (e.key === "Escape" && modal && modal.classList.contains("active")) {
            closeModal();
        }
    });
});

