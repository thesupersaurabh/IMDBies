from flask import Flask, render_template, request, jsonify, make_response, redirect, url_for, Response
import traceback
import random
import json
from functools import wraps
import time
from imdb import IMDb, IMDbError
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

cinema_goer = IMDb()

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

# Initialize Sitemap
ext = Sitemap(app=app)

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
        # Fix: Map 'tv' from frontend to 'tv series' for backend processing
        searching_for_tv = media_type == 'tv'
        
        if not searching_for_tv:
            print(f"Searching for movies with keyword: '{keyword}'")
            movies = cinema_goer.search_movie(keyword)
            movies = [m for m in movies if not is_tv_series(m)]
            print(f"Found {len(movies)} movies")
        else:
            print(f"Searching for TV series with keyword: '{keyword}'")
            # Use a higher result count for TV series to ensure we get enough after filtering
            movies = cinema_goer.search_movie(keyword, results=40)
            print(f"Initial search returned {len(movies)} results")
            # Print kinds for debugging
            kinds = {m.get('kind', 'unknown') for m in movies}
            print(f"Content kinds in search results: {kinds}")
            
            # Ensure we're only getting TV series using our helper function
            movies = [m for m in movies if is_tv_series(m)]
            print(f"Filtered to {len(movies)} TV series")

        movie_data = []
        for movie in movies[:app.config['MAX_SEARCH_RESULTS']]:
            cover_url = movie.get('cover url', '')
            if cover_url:
                cover_url = cover_url.replace('._V1_SX300', '._V1_SX600')
            
            movie_item = {
                'imdb_id': movie.movieID,
                'title': movie.get('title', 'Untitled'),
                'year': movie.get('year', ''),
                'thumbnail': cover_url,
                'is_series': is_tv_series(movie)
            }
            movie_data.append(movie_item)

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

        # Ensure ID is in the correct format
        clean_id = imdb_id.replace('tt', '')
        
        movie = cinema_goer.get_movie(clean_id)
        if not movie:
            return jsonify({'error': 'Movie not found'}), 404
            
        is_series = is_tv_series(movie)
        
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
            'directors': [director['name'] for director in movie.get('directors', [])] if movie.get('directors') else [],
            'plot': movie.get('plot outline', movie.get('plot', [''])[0] if movie.get('plot') else ''),
            'rating': movie.get('rating', ''),
            'votes': movie.get('votes', ''),
            'cast': [cast['name'] for cast in movie.get('cast', [])[:5]] if movie.get('cast') else [],
            'is_series': is_series,
            'thumbnail': movie.get('cover url', '').replace('._V1_SX300', '._V1_SX600') if movie.get('cover url') else '',
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
        # Ensure imdb_id format is correct
        clean_id = imdb_id.replace('tt', '') if imdb_id.startswith('tt') else imdb_id
            
        movie = cinema_goer.get_movie(clean_id)
        genres = movie.get('genres', [])
        is_series = is_tv_series(movie)
        
        # If no genres, return empty list
        if not genres:
            return jsonify([])
        
        # Search for similar content
        similar_movies = []
        for genre in genres[:2]:  # Use first 2 genres
            # Search for the appropriate content type
            search_results = cinema_goer.search_movie(genre, results=30)
            
            for m in search_results:
                # Skip the current movie/series
                if m.movieID == clean_id:
                    continue
                    
                # For series, match with series; for movies, match with movies
                if is_series:
                    if not is_tv_series(m):
                        continue
                else:
                    if is_tv_series(m):
                        continue
                        
                # Check if already added to avoid duplicates
                if any(sm['imdb_id'] == m.movieID for sm in similar_movies):
                    continue
                    
                # Get a better thumbnail URL
                cover_url = m.get('cover url', '')
                if cover_url:
                    cover_url = cover_url.replace('._V1_SX300', '._V1_SX600')
                
                similar_movies.append({
                    'imdb_id': f"tt{m.movieID}",
                    'title': m.get('title', 'Untitled'),
                    'year': m.get('year', ''),
                    'thumbnail': cover_url,
                    'is_series': is_tv_series(m)
                })

                # Limit the number of similar movies
                if len(similar_movies) >= 20:
                    break

        # Randomize the order to provide variety
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
        movie = cinema_goer.get_movie(imdb_id.replace('tt', ''))
        if not movie:
            return redirect(url_for('index'))
            
        # Convert movie object to serializable dictionary
        movie_data = {
            'imdb_id': imdb_id,
            'title': movie.get('title', ''),
            'year': movie.get('year', ''),
            'plot': movie.get('plot outline', movie.get('plot', [''])[0] if movie.get('plot') else ''),
            'rating': movie.get('rating', ''),
            'votes': movie.get('votes', ''),
            'directors': [director['name'] for director in movie.get('directors', [])] if movie.get('directors') else [],
            'cast': [cast['name'] for cast in movie.get('cast', [])[:5]] if movie.get('cast') else [],
            'genres': movie.get('genres', []),
            'is_series': is_tv_series(movie),
            'thumbnail': movie.get('cover url', '').replace('._V1_SX300', '._V1_SX600') if movie.get('cover url') else '',
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
        movie = cinema_goer.get_movie(imdb_id.replace('tt', ''))
        if not movie:
            return redirect(url_for('index'))
            
        # Create correct slug
        correct_slug = slugify(f"{movie.get('title', '')}-{movie.get('year', '')}")
        
        # Redirect if slug is incorrect (for SEO)
        if slug != correct_slug:
            return redirect(url_for('movie_page', imdb_id=imdb_id, slug=correct_slug))
            
        # Update sitemap with higher priority for newer movies
        current_year = datetime.now().year
        movie_year = int(movie.get('year', current_year))
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
            movies = cinema_goer.search_movie(keyword)
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
        # Fetch all results first
        results = cinema_goer.search_movie(keyword, results=40)
        print(f"Initial search returned {len(results)} results")
        
        if not results:
            return jsonify([])
        
        # Get kinds for debugging
        kinds = {m.get('kind', 'unknown') for m in results}
        print(f"Content kinds in search results: {kinds}")
        
        # Process results
        combined_data = []
        for movie in results[:40]:  # Get all results for sorting later
            cover_url = movie.get('cover url', '')
            if cover_url:
                cover_url = cover_url.replace('._V1_SX300', '._V1_SX600')
            
            # Use our helper function to detect TV series
            is_series = is_tv_series(movie)
            
            movie_item = {
                'imdb_id': movie.movieID,
                'title': movie.get('title', 'Untitled'),
                'year': movie.get('year', ''),
                'thumbnail': cover_url,
                'is_series': is_series,
                'kind': movie.get('kind', 'unknown'),
                'rating': movie.get('rating', 0)
            }
            combined_data.append(movie_item)
        
        # Sort results: top rated first, then by year (newest first)
        combined_data.sort(key=lambda x: (-(x.get('rating') or 0), -(x.get('year') or 0)))
        
        # Return the top results (limit to 20 for performance)
        print(f"Returning {min(20, len(combined_data))} combined results")
        return jsonify(combined_data[:20])
    except Exception as e:
        print(f"Error in combined search: {str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)})

def update_sitemap_entry(imdb_id, title, year, priority=0.5):
    """Update sitemap with new movie entry and metadata"""
    try:
        movie_slug = slugify(f"{title}-{year}")
        movie_url = url_for('movie_page', imdb_id=imdb_id, slug=movie_slug, _external=True)
        
        # Get movie details for rich metadata
        movie = cinema_goer.get_movie(imdb_id.replace('tt', ''))
        current_time = datetime.now()
        
        # Calculate priority based on various factors
        current_year = datetime.now().year
        movie_year = int(year) if year else current_year
        base_priority = min(0.9, 0.5 + (0.4 if movie_year >= current_year - 1 else 0.0))
        
        # Boost priority for popular movies
        if movie and movie.get('rating', 0) > 7.0:
            base_priority = min(0.95, base_priority + 0.1)
        
        entry = {
            'url': movie_url,
            'title': title,
            'lastmod': current_time.strftime('%Y-%m-%d'),
            'priority': base_priority,
            'timestamp': current_time,
            'thumbnail': movie.get('cover url', '').replace('._V1_SX300', '._V1_SX600') if movie else None
        }
        
        # Add to recently viewed
        SITEMAP_CACHE['recently_viewed'].append(entry)
        
        # Keep only last 1000 entries, sorted by priority and timestamp
        SITEMAP_CACHE['recently_viewed'] = sorted(
            SITEMAP_CACHE['recently_viewed'],
            key=lambda x: (-x['priority'], x['timestamp']),
            reverse=True
        )[:1000]
        
        # Invalidate sitemap cache to regenerate with new entry
        SITEMAP_CACHE['last_updated'] = None
        
    except Exception as e:
        print(f"Error updating sitemap: {str(e)}")

@app.route('/sitemap.xml')
def sitemap():
    """Generate dynamic sitemap with XSLT styling"""
    try:
        # Get base URL
        base_url = request.url_root.rstrip('/')
        current_date = datetime.now().strftime("%Y-%m-%d")

        # Start with XML declaration and stylesheet reference
        xml_parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<?xml-stylesheet type="text/xsl" href="/static/sitemap.xsl"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"',
            '        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
            '        xsi:schemaLocation="http://www.sitemaps.org/schemas/sitemap/0.9',
            '        http://www.sitemaps.org/schemas/sitemap/0.9/sitemap.xsd">',
        ]

        # Add static pages
        static_pages = [
            ('/', 1.0, 'daily'),
            ('/watchlist', 0.8, 'daily'),
            ('/search', 0.8, 'always'),
            ('/about', 0.6, 'weekly'),
            ('/privacy', 0.6, 'monthly')
        ]

        for path, priority, changefreq in static_pages:
            xml_parts.extend([
                '    <url>',
                f'        <loc>{base_url}{path}</loc>',
                f'        <lastmod>{current_date}</lastmod>',
                f'        <changefreq>{changefreq}</changefreq>',
                f'        <priority>{priority}</priority>',
                '    </url>'
            ])

        # Add popular movies
        popular_movies = [
            ('tt0111161', 'The Shawshank Redemption', '1994'),
            ('tt0068646', 'The Godfather', '1972'),
            ('tt0468569', 'The Dark Knight', '2008'),
            ('tt0167260', 'The Lord of the Rings: The Return of the King', '2003'),
            ('tt0137523', 'Fight Club', '1999')
        ]

        for imdb_id, title, year in popular_movies:
            movie_slug = slugify(f"{title}-{year}")
            movie_url = f"{base_url}/movie/{imdb_id}/{movie_slug}"
            xml_parts.extend([
                '    <url>',
                f'        <loc>{movie_url}</loc>',
                f'        <lastmod>{current_date}</lastmod>',
                f'        <changefreq>weekly</changefreq>',
                f'        <priority>0.8</priority>',
                '    </url>'
            ])

        # Add recently viewed movies
        if SITEMAP_CACHE['recently_viewed']:
            for movie in SITEMAP_CACHE['recently_viewed']:
                xml_parts.extend([
                    '    <url>',
                    f'        <loc>{movie["url"]}</loc>',
                    f'        <lastmod>{movie["lastmod"]}</lastmod>',
                    f'        <changefreq>weekly</changefreq>',
                    f'        <priority>{movie["priority"]}</priority>',
                    '    </url>'
                ])

        # Close urlset
        xml_parts.append('</urlset>')

        # Join all parts and create response
        xml_content = '\n'.join(xml_parts)
        
        # Set response headers
        response = make_response(xml_content)
        response.headers['Content-Type'] = 'application/xml; charset=UTF-8'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    except Exception as e:
        print(f"Error generating sitemap: {str(e)}")
        traceback.print_exc()
        return Response(status=500)

@app.route('/robots.txt')
def robots():
    """Generate robots.txt"""
    robots_content = f"""User-agent: *
Allow: /
Sitemap: {url_for('sitemap', _external=True)}

# Optimize crawling
Crawl-delay: 1
"""
    return Response(robots_content, mimetype='text/plain')

@app.route('/static/sitemap.xsl')
def serve_sitemap_xsl():
    """Serve the XSLT stylesheet for the sitemap"""
    try:
        with open('static/sitemap.xsl', 'r', encoding='utf-8') as f:
            xsl_content = f.read()
        response = make_response(xsl_content)
        response.headers['Content-Type'] = 'application/xslt+xml; charset=UTF-8'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    except Exception as e:
        print(f"Error serving sitemap.xsl: {str(e)}")
        return Response(status=404)

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
    if isinstance(e, IMDbError):
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

if __name__ == "__main__":
    # Create static directory if it doesn't exist
    os.makedirs('static', exist_ok=True)
    
    # In development
    if app.config['DEBUG']:
        app.run(debug=True, use_reloader=True, host='0.0.0.0', port=5000)
    else:
        # In production
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
