from flask import Flask, render_template, request, jsonify, make_response, redirect, url_for, Response
import traceback
import random
import json
from functools import wraps
import time
import requests as http_requests
import html
import re
from datetime import datetime, timedelta
import os
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from config import config
from flask_sitemap import Sitemap
import xml.etree.ElementTree as ET
from urllib.parse import quote

# ---------------------------------------------------------------------------
# IMDbOT REST API wrapper — replaces cinemagoer/IMDbPY which is now broken
# (IMDb's anti-scraping measures block all scraper-based libraries)
# ---------------------------------------------------------------------------
IMDBAOT_SEARCH_URL = "https://imdb.iamidiotareyoutoo.com/search"

def imdb_search(keyword, results=20):
    """Search IMDb via OMDb API. Returns a list of result dicts compatible with previous IMDbOT format."""
    try:
        omdb_url = f"https://www.omdbapi.com/?s={quote(keyword)}&apikey=trilogy"
        resp = http_requests.get(omdb_url, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        
        if data.get('Response') == 'True':
            items = data.get('Search', [])
            formatted_items = []
            for item in items[:results]:
                formatted_items.append({
                    '#IMDB_ID': item.get('imdbID', ''),
                    '#TITLE': item.get('Title', 'Untitled'),
                    '#YEAR': item.get('Year', ''),
                    '#IMG_POSTER': item.get('Poster', '') if item.get('Poster') != 'N/A' else '',
                    '#ACTORS': '' # OMDb search doesn't return actors
                })
            return formatted_items
        return []
    except Exception as e:
        print(f"imdb_search error: {e}")
        return []

def imdb_get_movie(imdb_id):
    """
    Fetch movie/show metadata from OMDb (free, no-key tier via rapid lookup).
    Falls back to the IMDbOT search endpoint using the IMDb ID as a query.
    Returns a dict with normalised keys, or None on failure.
    """
    try:
        # Clean ID → always 'tt1234567' format
        if not imdb_id.startswith('tt'):
            imdb_id = f'tt{imdb_id}'

        # OMDb free endpoint (no API key needed for basic title lookup)
        omdb_url = f"https://www.omdbapi.com/?i={imdb_id}&apikey=trilogy"
        resp = http_requests.get(omdb_url, timeout=10)
        if resp.status_code == 200:
            d = resp.json()
            if d.get('Response') == 'True':
                genres = [g.strip() for g in d.get('Genre', '').split(',') if g.strip()]
                directors = [dr.strip() for dr in d.get('Director', '').split(',') if dr.strip() and dr.strip() != 'N/A']
                cast = [a.strip() for a in d.get('Actors', '').split(',') if a.strip() and a.strip() != 'N/A']
                rating_str = d.get('imdbRating', '')
                try:
                    rating = float(rating_str) if rating_str and rating_str != 'N/A' else ''
                except ValueError:
                    rating = ''
                votes_str = d.get('imdbVotes', '').replace(',', '')
                try:
                    votes = int(votes_str) if votes_str and votes_str != 'N/A' else ''
                except ValueError:
                    votes = ''
                kind = d.get('Type', 'movie')
                is_series = kind in ('series', 'episode')
                return {
                    'imdb_id': imdb_id,
                    'title': d.get('Title', 'Untitled'),
                    'year': d.get('Year', '').split('–')[0],
                    'genres': genres,
                    'directors': directors,
                    'plot': d.get('Plot', ''),
                    'rating': rating,
                    'votes': votes,
                    'cast': cast,
                    'is_series': is_series,
                    'thumbnail': d.get('Poster', '') if d.get('Poster') != 'N/A' else '',
                    'kind': kind,
                }
    except Exception as e:
        print(f"OMDb fetch failed for {imdb_id}: {e}")

    # Fallback: search by IMDb ID string using IMDbOT
    try:
        items = imdb_search(imdb_id, results=1)
        if items:
            item = items[0]
            title = item.get('#TITLE', 'Untitled')
            year = str(item.get('#YEAR', ''))
            actors = [a.strip() for a in item.get('#ACTORS', '').split(',') if a.strip()]
            return {
                'imdb_id': imdb_id,
                'title': title,
                'year': year,
                'genres': [],
                'directors': [],
                'plot': '',
                'rating': '',
                'votes': '',
                'cast': actors,
                'is_series': False,
                'thumbnail': item.get('#IMG_POSTER', ''),
                'kind': 'movie',
            }
    except Exception as e:
        print(f"IMDbOT fallback failed for {imdb_id}: {e}")

    return None

def _normalize_search_result(item):
    """Convert an IMDbOT search result dict to the app's standard format."""
    raw_id = item.get('#IMDB_ID', '')
    # Ensure no 'tt' prefix in movieID for backward compat, store full id separately
    clean_id = raw_id.replace('tt', '') if raw_id.startswith('tt') else raw_id
    title = item.get('#TITLE', 'Untitled')
    year = item.get('#YEAR', '')
    thumbnail = item.get('#IMG_POSTER', '')
    # IMDbOT doesn't expose kind; treat as movie by default
    # We check the title/year heuristically for series detection
    actors = item.get('#ACTORS', '')
    return {
        'movieID': clean_id,
        'imdb_id': raw_id,
        'title': title,
        'year': year,
        'thumbnail': thumbnail,
        'actors': actors,
        'kind': 'movie',  # IMDbOT does not expose kind in search results
    }

# Create Flask app with the correct configuration
app = Flask(__name__)
env = os.environ.get('FLASK_ENV', 'development')
app.config.from_object(config[env])

# Initialize security extensions
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Enable HTTPS and security headers
talisman = Talisman(
    app,
    content_security_policy=app.config['SECURITY_HEADERS']['Content-Security-Policy'],
    force_https=app.config.get('FORCE_HTTPS', False)  # Only force HTTPS in production
)

# cinema_goer = IMDb()  # Removed — IMDbPY/cinemagoer is broken (IMDb blocks scrapers)
# Using IMDbOT REST API instead (see imdb_search / imdb_get_movie helpers above)

# Cache to store commonly accessed movie details
MOVIE_CACHE = {}
# Cache for our dynamic sitemap
SITEMAP_CACHE = {
    'last_updated': None,
    'content': None,
    'recently_viewed': [],
    'new_releases': []
}
# Cache configuration
CACHE_TIMEOUT = app.config['CACHE_DEFAULT_TIMEOUT']

# Video source configuration
VIDSRC_BASE_URL = app.config['VIDSRC_BASE_URL']

# Disable default Flask-Sitemap routes for cleaner URLs
app.config['SITEMAP_INCLUDE_RULES_WITHOUT_PARAMS'] = False
app.config['SITEMAP_URL_SCHEME'] = 'https' if app.config.get('FORCE_HTTPS', False) else 'http'
app.config['SITEMAP_BLUEPRINT_URL_PREFIX'] = None

# No need for the extension to generate a sitemap (we use our custom one)
ext = Sitemap(app=app)

@ext.register_generator
def sitemap_routes():
    """Generate sitemap routes for Flask-Sitemap extension"""
    # Yield only user-facing static routes
    user_facing_routes = ['index', 'watchlist', 'about', 'privacy']
    for route in user_facing_routes:
        yield route, {}
    
    # Yield movie pages from our cache
    for movie in SITEMAP_CACHE['recently_viewed']:
        try:
            # Extract imdb_id and slug
            imdb_id = movie.get('imdb_id')
            slug = movie.get('slug')
            
            if imdb_id and slug:
                # Parameters dict for url_for function
                yield 'movie_page', {'imdb_id': imdb_id, 'slug': slug}
            else:
                # Extract from URL if not directly available
                url_parts = movie['url'].split('/')
                if len(url_parts) >= 5:  # Make sure we have enough parts
                    for i, part in enumerate(url_parts):
                        if part == 'movie' and i+2 < len(url_parts):
                            imdb_id = url_parts[i+1]
                            slug = url_parts[i+2]
                            # Parameters dict for url_for function
                            yield 'movie_page', {'imdb_id': imdb_id, 'slug': slug}
                            break
        except Exception as e:
            print(f"Error adding movie to sitemap generator: {str(e)}")
            continue

# Input validation helper
def validate_imdb_id(imdb_id):
    """Validate IMDb ID format"""
    if not imdb_id:
        return None
    # Remove 'tt' prefix if present
    clean_id = imdb_id.replace('tt', '') if imdb_id.startswith('tt') else imdb_id
    # Check if it's a valid IMDb ID (numbers only)
    if not clean_id.isdigit():
        return None
    return f"tt{clean_id}"

# Helper function to detect TV series
def is_tv_series(movie_obj):
    """Helper function to determine if a result is a TV series based on various attributes"""
    if not movie_obj:
        return False
    # Check the 'kind' attribute first
    if movie_obj.get('kind') == 'tv series':
        return True
    
    # Check the title for common TV series indicators
    title = movie_obj.get('title', '').lower()
    if any(indicator in title for indicator in ['season', 'episode', 'series', 'show']):
        return True
    
    # Check if it has episodes
    if 'episodes' in movie_obj:
        return True
    
    # Check the string representation for episode mentions
    if 'episode' in str(movie_obj).lower() and movie_obj.get('kind') != 'movie':
        return True
        
    return False

# Add custom template filters
@app.template_filter('escapejs')
def escapejs_filter(s):
    """Escape string for use in JavaScript"""
    if s is None:
        return ''
    s = str(s)
    s = html.escape(s)
    s = s.replace("'", "\\'")
    s = s.replace('"', '\\"')
    return s

def cache_response(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        response = f(*args, **kwargs)
        if isinstance(response, str):
            response = make_response(response)
        response.headers['Cache-Control'] = f'public, max-age={CACHE_TIMEOUT}'
        return response
    return decorated_function

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/search_movies')
@limiter.limit("60 per minute")
@cache_response
def search_movies():
    keyword = request.args.get('keyword', '').strip()
    media_type = request.args.get('type', 'movie')

    print(f"Search request - keyword: '{keyword}', media_type: '{media_type}'")

    if not keyword:
        return jsonify([])

    try:
        searching_for_tv = media_type == 'tv'
        
        print(f"Searching for {'TV series' if searching_for_tv else 'movies'} with keyword: '{keyword}'")
        raw_results = imdb_search(keyword, results=40)
        print(f"IMDbOT returned {len(raw_results)} results")

        movie_data = []
        for item in raw_results:
            raw_id = item.get('#IMDB_ID', '')
            clean_id = raw_id.replace('tt', '') if raw_id.startswith('tt') else raw_id
            title = item.get('#TITLE', 'Untitled')
            year = item.get('#YEAR', '')
            thumbnail = item.get('#IMG_POSTER', '')
            # IMDbOT doesn't expose kind in search; include all results when not filtering
            # For type=movie or type=tv we include all (filtering is hard without kind data)
            movie_item = {
                'imdb_id': raw_id,
                'title': title,
                'year': year,
                'thumbnail': thumbnail,
                'is_series': False,  # not reliably available from search endpoint
            }
            movie_data.append(movie_item)
            if len(movie_data) >= app.config['MAX_SEARCH_RESULTS']:
                break

        print(f"Returning {len(movie_data)} results for media_type: {media_type}")
        return jsonify(movie_data)
    except Exception as e:
        print(f"Error searching {media_type}s: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/get_movie_details')
@limiter.limit("120 per minute")
@cache_response
def get_movie_details():
    imdb_id = request.args.get('imdbId')

    # Validate IMDb ID
    imdb_id = validate_imdb_id(imdb_id)
    if not imdb_id:
        return jsonify({'error': 'Invalid IMDb ID provided'}), 400

    try:
        # Check if movie is in cache
        if imdb_id in MOVIE_CACHE and (datetime.now() - MOVIE_CACHE[imdb_id].get('time_added', datetime.now())).total_seconds() < CACHE_TIMEOUT:
            return jsonify(MOVIE_CACHE[imdb_id])

        movie = imdb_get_movie(imdb_id)
        if not movie:
            return jsonify({'error': 'Movie not found'}), 404
            
        is_series = movie.get('is_series', False)
        
        # Create title slug for SEO
        title = movie.get('title', 'Untitled')
        slug = slugify(title)
        
        # Generate SEO-friendly URL
        seo_url = url_for('movie_page', imdb_id=imdb_id, slug=slug, _external=True)
        
        details = {
            'imdb_id': imdb_id,
            'title': title,
            'year': movie.get('year', ''),
            'genres': movie.get('genres', []),
            'directors': movie.get('directors', []),
            'plot': movie.get('plot', ''),
            'rating': movie.get('rating', ''),
            'votes': movie.get('votes', ''),
            'cast': movie.get('cast', []),
            'is_series': is_series,
            'thumbnail': movie.get('thumbnail', ''),
            'seo_url': seo_url,
            'slug': slug
        }
        
        # Store in cache
        MOVIE_CACHE[imdb_id] = details
        MOVIE_CACHE[imdb_id]['time_added'] = datetime.now()

        return jsonify(details)
    except Exception as e:
        print(f"Error getting movie details: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/get_similar_movies')
@cache_response
def get_similar_movies():
    imdb_id = request.args.get('imdbId')

    if not imdb_id:
        return jsonify([])

    try:
        if not imdb_id.startswith('tt'):
            imdb_id = f'tt{imdb_id}'
            
        movie = imdb_get_movie(imdb_id)
        if not movie:
            return jsonify([])
        
        genres = movie.get('genres', [])
        is_series = movie.get('is_series', False)
        
        # If no genres, return empty list
        if not genres:
            # Fallback: search by title for similar content
            title = movie.get('title', '')
            if not title:
                return jsonify([])
            raw_results = imdb_search(title, results=20)
            similar_movies = []
            for item in raw_results:
                raw_id = item.get('#IMDB_ID', '')
                if raw_id == imdb_id:
                    continue
                similar_movies.append({
                    'imdb_id': raw_id,
                    'title': item.get('#TITLE', 'Untitled'),
                    'year': item.get('#YEAR', ''),
                    'thumbnail': item.get('#IMG_POSTER', ''),
                    'is_series': False,
                })
            random.shuffle(similar_movies)
            return jsonify(similar_movies[:10])
        
        # Search for similar content using genres
        similar_movies = []
        for genre in genres[:2]:  # Use first 2 genres
            raw_results = imdb_search(genre, results=20)
            for item in raw_results:
                raw_id = item.get('#IMDB_ID', '')
                if raw_id == imdb_id:
                    continue
                if any(sm['imdb_id'] == raw_id for sm in similar_movies):
                    continue
                similar_movies.append({
                    'imdb_id': raw_id,
                    'title': item.get('#TITLE', 'Untitled'),
                    'year': item.get('#YEAR', ''),
                    'thumbnail': item.get('#IMG_POSTER', ''),
                    'is_series': False,
                })
                if len(similar_movies) >= 20:
                    break

        if similar_movies:
            random.shuffle(similar_movies)
            
        return jsonify(similar_movies[:20])
    except Exception as e:
        print(f"Error getting similar movies: {str(e)}")
        traceback.print_exc()
        return jsonify([])

@app.route('/watch')
def watch():
    """Movie/TV show watch page with rich meta tags"""
    imdb_id = request.args.get('imdbId')
    if not imdb_id:
        return redirect(url_for('index'))
        
    try:
        # Fetch movie details
        movie = imdb_get_movie(imdb_id)
        if not movie:
            return redirect(url_for('index'))
            
        is_series = movie.get('is_series', False)
        
        # Convert movie dict to the format expected by the template
        movie_data = {
            'imdb_id': imdb_id,
            'title': movie.get('title', ''),
            'year': movie.get('year', ''),
            'plot': movie.get('plot', ''),
            'rating': movie.get('rating', ''),
            'votes': movie.get('votes', ''),
            'directors': movie.get('directors', []),
            'cast': movie.get('cast', []),
            'genres': movie.get('genres', []),
            'is_series': is_series,
            'thumbnail': movie.get('thumbnail', ''),
            'current_season': request.args.get('season', '1'),
            'current_episode': request.args.get('episode', '1')
        }
            
        # Prepare meta description
        description = f"Watch {movie_data['title']} ({movie_data['year']}) online for free. "
        if movie_data['plot']:
            description += f"{movie_data['plot'][:150]}... "
        if movie_data['directors']:
            description += f"Directed by {', '.join(movie_data['directors'][:2])}. "
        if movie_data['cast']:
            description += f"Starring {', '.join(movie_data['cast'][:3])}."
            
        # Prepare meta keywords
        keywords = [
            movie_data['title'],
            str(movie_data['year']),
            'watch online',
            'free streaming',
            'HD quality'
        ]
        if movie_data['genres']:
            keywords.extend(movie_data['genres'])
        if movie_data['directors']:
            keywords.extend(movie_data['directors'][:2])
        if movie_data['cast']:
            keywords.extend(movie_data['cast'][:3])
            
        return render_template('watch.html',
            movie=movie_data,
            meta_description=description,
            meta_keywords=', '.join(keywords),
            canonical_url=url_for('movie_page', 
                imdb_id=imdb_id, 
                slug=slugify(f"{movie_data['title']}-{movie_data['year']}"),
                _external=True
            )
        )
    except Exception as e:
        print(f"Error in watch page: {str(e)}")
        return redirect(url_for('index'))

# SEO-friendly URL route for movies
@app.route('/movie/<string:imdb_id>/<string:slug>')
def movie_page(imdb_id, slug):
    """SEO-friendly movie page"""
    try:
        # Clean IMDb ID
        imdb_id = validate_imdb_id(imdb_id)
        if not imdb_id:
            return redirect(url_for('index'))
            
        # Fetch movie details
        movie = imdb_get_movie(imdb_id)
        if not movie:
            return redirect(url_for('index'))
            
        # Create correct slug
        correct_slug = slugify(f"{movie.get('title', '')}-{movie.get('year', '')}")
        
        # Redirect if slug is incorrect (for SEO)
        if slug != correct_slug:
            return redirect(url_for('movie_page', imdb_id=imdb_id, slug=correct_slug))
            
        # Update sitemap with higher priority for newer movies
        current_year = datetime.now().year
        movie_year_str = str(movie.get('year', current_year)).split('–')[0]
        try:
            movie_year = int(movie_year_str)
        except (ValueError, TypeError):
            movie_year = current_year
        priority = min(0.9, 0.5 + (1.0 if movie_year >= current_year else 0.0))
        
        update_sitemap_entry(imdb_id, movie.get('title', ''), movie.get('year', ''), priority)
        
        # Redirect to watch page
        return redirect(url_for('watch', imdbId=imdb_id))
        
    except Exception as e:
        print(f"Error in movie page: {str(e)}")
        return redirect(url_for('index'))

# Helper function for URL slugs
def slugify(text):
    """Convert text to URL-friendly slug"""
    if not text:
        return 'watch'
    # Convert to lowercase
    text = text.lower()
    # Replace spaces with hyphens
    text = text.replace(' ', '-')
    # Remove special characters
    text = re.sub(r'[^a-z0-9-]', '', text)
    # Remove multiple consecutive hyphens
    text = re.sub(r'-+', '-', text)
    # Remove leading/trailing hyphens
    text = text.strip('-')
    return text or 'watch'

@app.route('/stream')
def stream():
    imdb_id = request.args.get('imdbId')
    season = request.args.get('season')
    episode = request.args.get('episode')
    
    if not imdb_id:
        return jsonify({'error': 'No IMDb ID provided'})
        
    # Add 'tt' prefix if not present
    if not imdb_id.startswith('tt'):
        imdb_id = f'tt{imdb_id}'
    
    try:
        print(f"Stream request: imdbId={imdb_id}, season={season}, episode={episode}")
        # Generate stream URL based on content type
        if season and episode:
            stream_url = f"{VIDSRC_BASE_URL}embed/tv/{imdb_id}/{season}/{episode}"
        else:
            stream_url = f"{VIDSRC_BASE_URL}embed/movie/{imdb_id}"
            
        return render_template('stream.html', stream_url=stream_url)
    except Exception as e:
        print(f"Error streaming content: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)})

@app.route('/watchlist')
def watchlist():
    """Render the watchlist page."""
    try:
        return render_template('watchlist.html')
    except Exception as e:
        error_message = f"An error occurred when loading the watchlist page: {str(e)}"
        app.logger.error(f"Watchlist error: {error_message}")
        return render_template('error.html', error=error_message)

@app.route("/search")
def search():
    """Search for movies based on a keyword."""
    keyword = request.args.get("keyword", "")
    if not keyword:
        return render_template("search.html", movies=[])
    else:
        try:
            raw_results = imdb_search(keyword, results=20)
            movies = [{
                'movieID': item.get('#IMDB_ID', '').replace('tt', ''),
                'title': item.get('#TITLE', 'Untitled'),
                'year': item.get('#YEAR', ''),
                'thumbnail': item.get('#IMG_POSTER', ''),
            } for item in raw_results]
            return render_template("search.html", movies=movies, keyword=keyword)
        except Exception as e:
            app.logger.error(f"Search error: {str(e)}")
            return render_template("error.html", error=f"Error searching for movies: {str(e)}")

@app.route('/search_combined')
@cache_response
def search_combined():
    """Search for both movies and TV series in a single request."""
    keyword = request.args.get('keyword')
    
    print(f"Combined search request - keyword: '{keyword}'")
    
    if not keyword:
        return jsonify([])
    
    try:
        # Fetch all results first via IMDbOT API
        raw_results = imdb_search(keyword, results=40)
        print(f"IMDbOT returned {len(raw_results)} results")
        
        if not raw_results:
            return jsonify([])
        
        # Process results
        combined_data = []
        for item in raw_results:
            raw_id = item.get('#IMDB_ID', '')
            title = item.get('#TITLE', 'Untitled')
            year = item.get('#YEAR', '')
            thumbnail = item.get('#IMG_POSTER', '')
            
            movie_item = {
                'imdb_id': raw_id,
                'title': title,
                'year': year,
                'thumbnail': thumbnail,
                'is_series': False,
                'kind': 'movie',
                'rating': 0
            }
            combined_data.append(movie_item)
        
        # Sort results by year (newest first), rating not available from search endpoint
        def get_safe_year(y):
            try:
                return int(str(y)[:4]) if y else 0
            except ValueError:
                return 0
                
        combined_data.sort(key=lambda x: -get_safe_year(x.get('year')))
        
        # Return the top results (limit to 20 for performance)
        print(f"Returning {min(20, len(combined_data))} combined results")
        return jsonify(combined_data[:20])
    except Exception as e:
        print(f"Error in combined search: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)})

def update_sitemap_entry(imdb_id, title, year, priority=0.5):
    """Update sitemap with new movie entry"""
    try:
        # Validate inputs
        if not imdb_id or not title:
            print(f"Missing required data for sitemap entry: imdb_id={imdb_id}, title={title}")
            return
            
        # Create slug and URL
        movie_slug = slugify(f"{title}-{year}")
        movie_url = url_for('movie_page', imdb_id=imdb_id, slug=movie_slug, _external=True)
        
        # Don't add duplicate entries
        if any(m['url'] == movie_url for m in SITEMAP_CACHE['recently_viewed']):
            # Update the timestamp on the existing entry to keep it fresh
            for m in SITEMAP_CACHE['recently_viewed']:
                if m['url'] == movie_url:
                    m['timestamp'] = datetime.now()
                    m['lastmod'] = datetime.now().strftime('%Y-%m-%d')
                    break
            return
        
        # Add to recently viewed with timestamp
        current_time = datetime.now()
        
        # Store movie details
        is_new_release = int(year) >= datetime.now().year - 1 if year else False
        
        SITEMAP_CACHE['recently_viewed'].append({
            'url': movie_url,
            'title': title,
            'year': year,
            'imdb_id': imdb_id,
            'slug': movie_slug,
            'lastmod': current_time.strftime('%Y-%m-%d'),
            'priority': 0.9 if is_new_release else priority,  # Higher priority for new releases
            'timestamp': current_time,
            'is_new_release': is_new_release
        })
        
        # Keep only last 100 entries
        SITEMAP_CACHE['recently_viewed'] = sorted(
            SITEMAP_CACHE['recently_viewed'],
            key=lambda x: x['timestamp'],
            reverse=True
        )[:100]
        
        print(f"Added movie to sitemap: {title} ({year}) - {imdb_id}")
        
        # Invalidate sitemap cache to force regeneration
        SITEMAP_CACHE['last_updated'] = None
        SITEMAP_CACHE['content'] = None
        
    except Exception as e:
        print(f"Error updating sitemap: {str(e)}")
        traceback.print_exc()

@app.route('/sitemap.xml')
def custom_sitemap():
    """Generate dynamic sitemap with proper XML namespaces and styling"""
    try:
        # Check if we have a cached version that's less than 1 hour old
        if (SITEMAP_CACHE['last_updated'] and 
            datetime.now() - SITEMAP_CACHE['last_updated'] < timedelta(hours=1) and
            SITEMAP_CACHE['content']):
            return Response(SITEMAP_CACHE['content'], mimetype='application/xml')

        # Force-populate with popular movies if empty
        if not SITEMAP_CACHE['recently_viewed']:
            # Add some popular movies to the sitemap
            popular_movies = [
                {'imdb_id': 'tt0111161', 'title': 'The Shawshank Redemption', 'year': '1994'},
                {'imdb_id': 'tt0068646', 'title': 'The Godfather', 'year': '1972'},
                {'imdb_id': 'tt0071562', 'title': 'The Godfather: Part II', 'year': '1974'},
                {'imdb_id': 'tt0468569', 'title': 'The Dark Knight', 'year': '2008'},
                {'imdb_id': 'tt0167260', 'title': 'The Lord of the Rings: The Return of the King', 'year': '2003'},
                {'imdb_id': 'tt1375666', 'title': 'Inception', 'year': '2010'},
                {'imdb_id': 'tt0133093', 'title': 'The Matrix', 'year': '1999'},
                {'imdb_id': 'tt0109830', 'title': 'Forrest Gump', 'year': '1994'},
                {'imdb_id': 'tt0167261', 'title': 'The Lord of the Rings: The Two Towers', 'year': '2002'},
                {'imdb_id': 'tt0080684', 'title': 'Star Wars: Episode V - The Empire Strikes Back', 'year': '1980'}
            ]
            
            # Add each movie to the sitemap cache
            for movie in popular_movies:
                update_sitemap_entry(movie['imdb_id'], movie['title'], movie['year'], 0.7)

        # Create new sitemap with proper namespaces and stylesheet
        xml_pi = '<?xml version="1.0" encoding="UTF-8"?>\n'
        stylesheet_pi = '<?xml-stylesheet type="text/xsl" href="/static/sitemap.xsl"?>\n'
        
        urlset = ET.Element('urlset', {
            'xmlns': 'http://www.sitemaps.org/schemas/sitemap/0.9',
            'xmlns:xsi': 'http://www.w3.org/2001/XMLSchema-instance',
            'xsi:schemaLocation': 'http://www.sitemaps.org/schemas/sitemap/0.9 http://www.sitemaps.org/schemas/sitemap/0.9/sitemap.xsd'
        })
        
        # Only include user-facing pages, not API endpoints or utility routes
        user_facing_pages = [
            {'route': 'index', 'priority': '0.8', 'changefreq': 'daily'},
            {'route': 'watchlist', 'priority': '0.6', 'changefreq': 'weekly'},
            {'route': 'about', 'priority': '0.5', 'changefreq': 'monthly'},
            {'route': 'privacy', 'priority': '0.5', 'changefreq': 'monthly'}
        ]
        
        # Keep track of included URLs to avoid duplicates
        included_urls = set()
        
        for page in user_facing_pages:
            try:
                page_url = url_for(page['route'], _external=True)
                
                # Skip if URL already included
                if page_url in included_urls:
                    continue
                    
                included_urls.add(page_url)
                
                url = ET.SubElement(urlset, 'url')
                loc = ET.SubElement(url, 'loc')
                loc.text = page_url
                lastmod = ET.SubElement(url, 'lastmod')
                lastmod.text = datetime.now().strftime('%Y-%m-%d')
                changefreq = ET.SubElement(url, 'changefreq')
                changefreq.text = page['changefreq']
                priority = ET.SubElement(url, 'priority')
                priority.text = page['priority']
            except Exception as e:
                print(f"Error adding {page['route']} to sitemap: {str(e)}")
                continue
        
        # Add movies - ensuring no duplicates
        added_movie_count = 0
        for movie in SITEMAP_CACHE['recently_viewed']:
            try:
                # Skip if URL already included
                if movie['url'] in included_urls:
                    continue
                    
                included_urls.add(movie['url'])
                
                url = ET.SubElement(urlset, 'url')
                loc = ET.SubElement(url, 'loc')
                loc.text = movie['url']
                lastmod = ET.SubElement(url, 'lastmod')
                lastmod.text = movie['lastmod']
                changefreq = ET.SubElement(url, 'changefreq')
                changefreq.text = 'weekly'
                priority = ET.SubElement(url, 'priority')
                priority.text = str(movie['priority'])
                added_movie_count += 1
            except Exception as e:
                print(f"Error adding movie {movie.get('title', 'unknown')} to sitemap: {str(e)}")
                continue
                
        print(f"Added {added_movie_count} movies to sitemap")
            
        # Generate XML with XML declaration and stylesheet
        sitemap_content = xml_pi + stylesheet_pi + ET.tostring(urlset, encoding='unicode')
        
        # Cache the result
        SITEMAP_CACHE['content'] = sitemap_content
        SITEMAP_CACHE['last_updated'] = datetime.now()
        
        # Create sitemap stylesheet if it doesn't exist
        create_sitemap_stylesheet()
        
        return Response(sitemap_content, mimetype='application/xml')
    except Exception as e:
        print(f"Error generating sitemap: {str(e)}")
        traceback.print_exc()
        return Response(f"<!-- Error generating sitemap: {str(e)} -->", status=500, mimetype='application/xml')

# Add missing routes referenced in sitemap
@app.route('/about')
def about():
    """About page"""
    return render_template('about.html')

@app.route('/privacy')
def privacy():
    """Privacy policy page"""
    return render_template('privacy.html')

@app.route('/robots.txt')
def robots():
    """Generate robots.txt with rules for search engines"""
    robots_content = f"""User-agent: *
Allow: /
Disallow: /stream
Disallow: /search_movies
Disallow: /get_movie_details
Disallow: /get_similar_movies
Disallow: /search_combined
Disallow: /update-sitemap
Sitemap: {url_for('custom_sitemap', _external=True)}

# Optimize crawling
Crawl-delay: 1
"""
    return Response(robots_content, mimetype='text/plain')

# Custom error handlers
@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 errors with a custom template"""
    return render_template('error.html', 
        error="Page not found. The requested URL was not found on the server.",
        code=404,
        suggestion="Please check the URL and try again."), 404

@app.errorhandler(429)
def ratelimit_handler(error):
    """Handle rate limit exceeded errors"""
    return render_template('error.html',
        error="Rate limit exceeded. Too many requests.",
        code=429,
        suggestion="Please wait a while before trying again."), 429

@app.errorhandler(500)
def internal_error(error):
    """Handle internal server errors"""
    print(f"Internal Server Error: {str(error)}")
    traceback.print_exc()
    return render_template('error.html',
        error="An internal server error occurred.",
        code=500,
        suggestion="Please try again later. If the problem persists, contact support."), 500

@app.errorhandler(Exception)
def handle_exception(e):
    """Handle all other exceptions"""
    print(f"Unhandled exception: {str(e)}")
    traceback.print_exc()
    
    # Determine if this is a known error type
    if isinstance(e, http_requests.exceptions.RequestException):
        message = "Error accessing movie database. Please try again later."
        suggestion = "Check your internet connection and try again."
    elif isinstance(e, ValueError):
        message = "Invalid input provided."
        suggestion = "Please check your input and try again."
    else:
        message = str(e)
        suggestion = "Please try again later. If the problem persists, contact support."
    
    return render_template('error.html',
        error=message,
        code=500,
        suggestion=suggestion), 500

@app.route('/update-sitemap')
@limiter.limit("1 per minute")
def update_sitemap():
    """Force update the sitemap with popular movies"""
    if not request.args.get('key') == app.config['SECRET_KEY']:
        return Response("Unauthorized", status=401)
        
    try:
        # Clear existing cache to rebuild from scratch
        SITEMAP_CACHE['recently_viewed'] = []
        
        # Add some popular movies to the sitemap
        popular_movies = [
            {'imdb_id': 'tt0111161', 'title': 'The Shawshank Redemption', 'year': '1994'},
            {'imdb_id': 'tt0068646', 'title': 'The Godfather', 'year': '1972'},
            {'imdb_id': 'tt0071562', 'title': 'The Godfather: Part II', 'year': '1974'},
            {'imdb_id': 'tt0468569', 'title': 'The Dark Knight', 'year': '2008'},
            {'imdb_id': 'tt0167260', 'title': 'The Lord of the Rings: The Return of the King', 'year': '2003'},
            {'imdb_id': 'tt1375666', 'title': 'Inception', 'year': '2010'},
            {'imdb_id': 'tt0133093', 'title': 'The Matrix', 'year': '1999'},
            {'imdb_id': 'tt0109830', 'title': 'Forrest Gump', 'year': '1994'},
            {'imdb_id': 'tt0167261', 'title': 'The Lord of the Rings: The Two Towers', 'year': '2002'},
            {'imdb_id': 'tt0080684', 'title': 'Star Wars: Episode V - The Empire Strikes Back', 'year': '1980'}
        ]
        
        # Add recent movies with higher priority
        recent_movies = [
            {'imdb_id': 'tt10366206', 'title': 'John Wick: Chapter 4', 'year': '2023'},
            {'imdb_id': 'tt1630029', 'title': 'Avatar: The Way of Water', 'year': '2022'},
            {'imdb_id': 'tt5433140', 'title': 'Fast X', 'year': '2023'},
            {'imdb_id': 'tt1517268', 'title': 'Barbie', 'year': '2023'},
            {'imdb_id': 'tt15398776', 'title': 'Oppenheimer', 'year': '2023'}
        ]
        
        # Add all movies to the sitemap
        for movie in popular_movies:
            update_sitemap_entry(movie['imdb_id'], movie['title'], movie['year'], 0.7)
            
        # Add recent movies with higher priority
        for movie in recent_movies:
            update_sitemap_entry(movie['imdb_id'], movie['title'], movie['year'], 0.9)
        
        # Create or update the sitemap stylesheet
        create_sitemap_stylesheet()
        
        # Force sitemap regeneration
        SITEMAP_CACHE['last_updated'] = None
        sitemap_content = custom_sitemap().get_data(as_text=True)
        
        # Check if the sitemap was successfully generated
        url_count = sitemap_content.count('<url>')
        movie_count = len(SITEMAP_CACHE['recently_viewed'])
        
        return Response(f"Sitemap updated with {url_count} URLs ({movie_count} movies)", mimetype='text/plain')
    except Exception as e:
        print(f"Error updating sitemap: {str(e)}")
        traceback.print_exc()
        return Response(f"Error updating sitemap: {str(e)}", status=500, mimetype='text/plain')

def create_sitemap_stylesheet():
    """Create XSL stylesheet for sitemap if it doesn't exist"""
    try:
        # Ensure static directory exists
        os.makedirs('static', exist_ok=True)
        
        # Path to the stylesheet
        stylesheet_path = os.path.join('static', 'sitemap.xsl')
        
        # Skip if file already exists
        if os.path.exists(stylesheet_path):
            return
            
        # XSL stylesheet content for nice sitemap display
        xsl_content = '''<?xml version="1.0" encoding="UTF-8"?>
<xsl:stylesheet version="2.0" 
    xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
    xmlns:sitemap="http://www.sitemaps.org/schemas/sitemap/0.9">

<xsl:template match="/">
<html lang="en">
<head>
    <title>XML Sitemap - IMDBies</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Oxygen-Sans, Ubuntu, Cantarell, "Helvetica Neue", sans-serif;
            color: #333;
            background-color: #f8f9fa;
            line-height: 1.6;
            padding: 20px;
            max-width: 1200px;
            margin: 0 auto;
        }
        .header {
            background-color: #e50914;
            color: white;
            padding: 20px;
            margin-bottom: 20px;
            border-radius: 5px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        }
        h1 {
            margin: 0;
            padding: 0;
            font-size: 24px;
        }
        .stats {
            background-color: white;
            padding: 15px;
            margin-bottom: 20px;
            border-radius: 5px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background-color: white;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
            border-radius: 5px;
            overflow: hidden;
        }
        th {
            background-color: #343a40;
            color: white;
            text-align: left;
            padding: 12px 15px;
        }
        td {
            padding: 10px 15px;
            border-top: 1px solid #f2f2f2;
        }
        tr:hover {
            background-color: #f5f5f5;
        }
        a {
            color: #e50914;
            text-decoration: none;
        }
        a:hover {
            text-decoration: underline;
        }
        .priority-high {
            background-color: #28a745;
            color: white;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.8em;
        }
        .priority-medium {
            background-color: #ffc107;
            color: #333;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.8em;
        }
        .priority-low {
            background-color: #6c757d;
            color: white;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 0.8em;
        }
        .footer {
            margin-top: 20px;
            text-align: center;
            font-size: 0.9em;
            color: #6c757d;
        }
        @media (max-width: 768px) {
            th, td {
                padding: 8px 10px;
            }
            .url-column {
                max-width: 200px;
                overflow: hidden;
                text-overflow: ellipsis;
                white-space: nowrap;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>IMDBies XML Sitemap</h1>
    </div>
    
    <div class="stats">
        <p>This sitemap contains <strong><xsl:value-of select="count(sitemap:urlset/sitemap:url)"/></strong> URLs.</p>
    </div>
    
    <table>
        <tr>
            <th width="60%">URL</th>
            <th>Last Modified</th>
            <th>Change Frequency</th>
            <th>Priority</th>
        </tr>
        <xsl:for-each select="sitemap:urlset/sitemap:url">
        <tr>
            <td class="url-column">
                <a href="{sitemap:loc}"><xsl:value-of select="sitemap:loc"/></a>
            </td>
            <td><xsl:value-of select="sitemap:lastmod"/></td>
            <td><xsl:value-of select="sitemap:changefreq"/></td>
            <td>
                <xsl:choose>
                    <xsl:when test="number(sitemap:priority) >= 0.8">
                        <span class="priority-high"><xsl:value-of select="sitemap:priority"/></span>
                    </xsl:when>
                    <xsl:when test="number(sitemap:priority) >= 0.6">
                        <span class="priority-medium"><xsl:value-of select="sitemap:priority"/></span>
                    </xsl:when>
                    <xsl:otherwise>
                        <span class="priority-low"><xsl:value-of select="sitemap:priority"/></span>
                    </xsl:otherwise>
                </xsl:choose>
            </td>
        </tr>
        </xsl:for-each>
    </table>
    
    <div class="footer">
        <p>Generated by IMDBies - Your Ultimate Movie Streaming Destination</p>
    </div>
</body>
</html>
</xsl:template>

</xsl:stylesheet>
'''
        
        # Write the stylesheet to the file
        with open(stylesheet_path, 'w', encoding='utf-8') as f:
            f.write(xsl_content)
            
        print(f"Created sitemap stylesheet at {stylesheet_path}")
        
    except Exception as e:
        print(f"Error creating sitemap stylesheet: {str(e)}")
        traceback.print_exc()

@app.route('/sitemap.xsl')
def serve_sitemap_xsl():
    """Serve the sitemap XSL stylesheet"""
    try:
        # Create the stylesheet if it doesn't exist
        create_sitemap_stylesheet()
        
        # Return the stylesheet
        return app.send_static_file('sitemap.xsl')
    except Exception as e:
        print(f"Error serving sitemap.xsl: {str(e)}")
        traceback.print_exc()
        return Response("Error serving sitemap stylesheet", status=500)

if __name__ == "__main__":
    # Create static directory if it doesn't exist
    os.makedirs('static', exist_ok=True)
    
    # In development
    if app.config['DEBUG']:
        app.run(debug=True, use_reloader=True, host='0.0.0.0', port=5000)
    else:
        # In production
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
