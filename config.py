import os
from datetime import timedelta
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError("No SECRET_KEY set in environment variables!")
        
    DEBUG = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    TESTING = False
    
    # Security headers
    SECURITY_HEADERS = {
        'X-Frame-Options': 'SAMEORIGIN',
        'X-XSS-Protection': '1; mode=block',
        'X-Content-Type-Options': 'nosniff',
        'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
        'Content-Security-Policy': "default-src 'self' https:; script-src 'self' 'unsafe-inline' https:; style-src 'self' 'unsafe-inline' https:; img-src 'self' data: https:; font-src 'self' https:; connect-src 'self' https:;",
        'Referrer-Policy': 'strict-origin-when-cross-origin'
    }
    
    # Cache settings
    CACHE_TYPE = os.environ.get('CACHE_TYPE', 'simple')
    CACHE_DEFAULT_TIMEOUT = int(os.environ.get('CACHE_DEFAULT_TIMEOUT', 3600))
    
    # Rate limiting
    RATELIMIT_DEFAULT = os.environ.get('RATELIMIT_DEFAULT', "200 per day;50 per hour;1 per second")
    RATELIMIT_STORAGE_URL = "memory://"
    
    # Video source configuration
    VIDSRC_BASE_URL = os.environ.get('VIDSRC_BASE_URL', "https://vidsrc.icu/")
    
    # IMDb configuration
    IMDB_CACHE_TIMEOUT = timedelta(hours=1)
    MAX_SEARCH_RESULTS = 20
    
    # Error reporting
    PROPAGATE_EXCEPTIONS = True

class DevelopmentConfig(Config):
    DEBUG = True
    
class ProductionConfig(Config):
    DEBUG = False
    # Force HTTPS in production
    FORCE_HTTPS = True
    # Stricter CSP in production
    SECURITY_HEADERS = {
        **Config.SECURITY_HEADERS,
        'Content-Security-Policy': Config.SECURITY_HEADERS['Content-Security-Policy'].replace("'unsafe-inline'", "'nonce-{nonce}'")
    }

class TestingConfig(Config):
    TESTING = True
    DEBUG = True
    # Use a fixed key for testing
    SECRET_KEY = 'test-key-do-not-use-in-production'

# Dictionary to map environment names to config classes
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
} 