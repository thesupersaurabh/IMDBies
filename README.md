# IMDBies - Movie Streaming Platform

A modern movie and TV show streaming platform built with Flask and IMDbPY. Watch your favorite content with a beautiful, responsive interface.

## Features

- 🎬 Stream movies and TV shows for free
- 🔍 Advanced search with filters
- 📱 Responsive design for all devices
- 🎯 Personalized watchlist
- 🌙 Dark/Light mode
- 🚀 Fast loading with caching
- 📊 IMDb ratings and details
- 🔒 SEO optimized
- 🛡️ Rate limiting protection
- 🎨 Modern UI with Bootstrap 5

## Tech Stack

- Python 3.9+
- Flask 3.0.2
- IMDbPY 2022.7.9
- Bootstrap 5.3
- Font Awesome 6.5
- Flask-Limiter 3.5.0
- Flask-Talisman 1.1.0

## Quick Start

1. Clone the repository:
```bash
git clone https://github.com/yourusername/imdbie.git
cd imdbie
```

2. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Create a `.env` file:
```env
FLASK_ENV=development
FLASK_DEBUG=True
SECRET_KEY=your-secret-key
VIDSRC_BASE_URL=https://vidsrc.icu/
CACHE_TYPE=simple
CACHE_DEFAULT_TIMEOUT=3600
MAX_SEARCH_RESULTS=20
FORCE_HTTPS=false
```

5. Run the development server:
```bash
python app.py
```

6. Visit http://localhost:5000 in your browser

## Common Issues & Solutions

### Rate Limiting
The application uses Flask-Limiter for rate limiting:
- Default: 200 requests per day, 50 per hour
- Search endpoint: 60 requests per minute
- Movie details: 120 requests per minute

### Static Files (404 Errors)
If you see 404 errors for static files:
1. Create the static directory:
```bash
mkdir static
```

2. Generate favicon files:
```bash
python generate_favicons.py
```

3. Verify file permissions on the static directory

### Error Messages

1. **ModuleNotFoundError**
   Solution: Run `pip install -r requirements.txt`

2. **Rate Limit Exceeded**
   Solution: Wait for the limit to reset or adjust limits in app.py

3. **Movie Not Found**
   - Check IMDb ID format
   - Verify API connectivity
   - Ensure valid search parameters

4. **Static Files Missing**
   Solution: Run `python generate_favicons.py`

5. **Server Error (500)**
   - Check application logs
   - Verify environment variables
   - Check API connectivity

## Development Guidelines

### Code Style
- Follow PEP 8 guidelines
- Use type hints
- Add docstrings
- Keep functions focused

### Adding New Features
1. Create a new branch
2. Write tests if applicable
3. Update documentation
4. Submit a pull request

## API Endpoints

- `/search_movies` - Search for movies
- `/get_movie_details` - Get movie information
- `/get_similar_movies` - Get recommendations
- `/stream` - Get streaming URL
- `/sitemap.xml` - Dynamic sitemap
- `/robots.txt` - Search engine configuration

## Security Features

- HTTPS enforcement (production)
- Content Security Policy
- Rate limiting
- Input validation
- XSS protection

## Performance Tips

1. Enable caching in production
2. Use a CDN for static files
3. Optimize images
4. Minimize API calls

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Author

Created by [Saurabh](https://thesaurabh.tech)

## Acknowledgements

- IMDbPY for movie data
- VidSrc for streaming
- Flask framework
- Bootstrap for UI
- Font Awesome for icons

---

**Note:** For an optimal experience, we recommend using uBlock Origin for an ad-free movie-watching session. 