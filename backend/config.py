"""Configuration management for the application."""
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class Config:
    """Base configuration class."""
    # Database configuration
    # Normalize PostgreSQL URLs to use the installed psycopg2 driver.
    _raw_db_url = os.getenv('DATABASE_URL', 'sqlite:///reviews.db')
    if _raw_db_url.startswith(('postgres://', 'postgresql://')):
        _raw_db_url = 'postgresql+psycopg2://' + _raw_db_url.split('://', 1)[1]
    DATABASE_URL = _raw_db_url
    
    # MediaCloud API configuration
    MEDIACLOUD_API_KEY = os.getenv('MEDIACLOUD_API_KEY')
    # Optional alternate base URL for write operations (eg staging/dev MediaCloud API).
    MEDIACLOUD_UPLOAD_BASE_URL = os.getenv('MEDIACLOUD_UPLOAD_BASE_URL')
    MEDIACLOUD_PUBLISH_ENABLED = os.getenv('MEDIACLOUD_PUBLISH_ENABLED', 'true').lower() in ('1', 'true', 'yes', 'y')
    # When false, publish ignores apply_metadata_updates_to_existing_sources (opt-in per request).
    MEDIACLOUD_PUBLISH_METADATA_UPDATES_ENABLED = os.getenv(
        'MEDIACLOUD_PUBLISH_METADATA_UPDATES_ENABLED', 'true'
    ).lower() in ('1', 'true', 'yes', 'y')
    # Optional base URL for building MediaCloud web links in the UI/API responses.
    MEDIACLOUD_SEARCH_BASE_URL = os.getenv('MEDIACLOUD_SEARCH_BASE_URL', 'https://search.mediacloud.org')
    # Collection AI reviewer: the only address the backend fetches AI reviews from and sends decisions to.
    # Unset disables import by URL and sending back (an AI review can still be imported as JSON).
    AI_REVIEWER_BASE_URL = os.getenv('AI_REVIEWER_BASE_URL', '')
    # Bearer token for the AI reviewer's API; only ever sent to AI_REVIEWER_BASE_URL.
    AI_REVIEWER_TOKEN = os.getenv('AI_REVIEWER_TOKEN', '')

    # Flask configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
    DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    # SQLAlchemy configuration
    SQLALCHEMY_DATABASE_URI = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS = False


def get_config():
    """Get configuration instance."""
    return Config()
