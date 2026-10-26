"""Run all database migrations in order.

This script runs all manual migration scripts in the correct order.
It's designed to be idempotent - safe to run multiple times.
Works with both SQLite and PostgreSQL.

Usage:
    python backend/run_migrations.py
"""
import sys
import os
from pathlib import Path

# Add backend to path
backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

# Set up environment for Flask app
os.environ.setdefault('FLASK_APP', 'app:create_app')

def run_all_migrations():
    """Run all migrations using SQLAlchemy."""
    from app import create_app
    from database import db
    from sqlalchemy import inspect, text
    
    app = create_app()
    
    with app.app_context():
        # Get database connection info
        engine = db.engine
        inspector = inspect(engine)
        is_sqlite = 'sqlite' in str(engine.url)
        
        print("Starting database migrations...")
        print(f"Database: {engine.url.drivername}")
        
        # Get connection for raw SQL
        conn = engine.connect()
        trans = conn.begin()
        
        try:
            # Migration 1: collection_name
            print("\nRunning migration: collection_name")
            if is_sqlite:
                # SQLite: Check if column exists
                result = conn.execute(text("PRAGMA table_info(reviews)"))
                columns = [row[1] for row in result]
                if 'collection_name' in columns:
                    print("Column 'collection_name' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN collection_name TEXT"))
                    print("Successfully added 'collection_name' column.")
            else:
                # PostgreSQL: Check if column exists
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='reviews' AND column_name='collection_name'
                """))
                if result.fetchone():
                    print("Column 'collection_name' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN collection_name TEXT"))
                    print("Successfully added 'collection_name' column.")
            
            # Migration 2: removal_reason
            print("\nRunning migration: removal_reason")
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(review_items)"))
                columns = [row[1] for row in result]
                if 'removal_reason' in columns:
                    print("Column 'removal_reason' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE review_items ADD COLUMN removal_reason TEXT"))
                    print("Successfully added 'removal_reason' column.")
            else:
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='review_items' AND column_name='removal_reason'
                """))
                if result.fetchone():
                    print("Column 'removal_reason' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE review_items ADD COLUMN removal_reason TEXT"))
                    print("Successfully added 'removal_reason' column.")
            
            # Migration 3: source_metadata
            print("\nRunning migration: source_metadata")
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(review_items)"))
                columns = [row[1] for row in result]
                if 'source_metadata' in columns:
                    print("Column 'source_metadata' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE review_items ADD COLUMN source_metadata TEXT"))
                    print("Successfully added 'source_metadata' column.")
            else:
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='review_items' AND column_name='source_metadata'
                """))
                if result.fetchone():
                    print("Column 'source_metadata' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE review_items ADD COLUMN source_metadata TEXT"))
                    print("Successfully added 'source_metadata' column.")
            
            # Migration 4: guidelines_template
            print("\nRunning migration: guidelines_template")
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(reviews)"))
                columns = [row[1] for row in result]
                if 'guidelines_template' in columns:
                    print("Column 'guidelines_template' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN guidelines_template TEXT DEFAULT 'default'"))
                    print("Successfully added 'guidelines_template' column.")
            else:
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='reviews' AND column_name='guidelines_template'
                """))
                if result.fetchone():
                    print("Column 'guidelines_template' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN guidelines_template TEXT DEFAULT 'default'"))
                    print("Successfully added 'guidelines_template' column.")
            
            # Migration 5: edit_metadata flag on reviews
            print("\nRunning migration: edit_metadata")
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(reviews)"))
                columns = [row[1] for row in result]
                if 'edit_metadata' in columns:
                    print("Column 'edit_metadata' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN edit_metadata BOOLEAN DEFAULT 0"))
                    print("Successfully added 'edit_metadata' column.")
            else:
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name='reviews' AND column_name='edit_metadata'
                """))
                if result.fetchone():
                    print("Column 'edit_metadata' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN edit_metadata BOOLEAN DEFAULT FALSE"))
                    print("Successfully added 'edit_metadata' column.")

            # Migration 6: review_project_id and queue_guid fields
            print("\nRunning migration: review_project queue fields")
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(reviews)"))
                columns = [row[1] for row in result]

                if 'review_project_id' not in columns:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN review_project_id INTEGER"))
                    print("Successfully added 'review_project_id' column.")
                else:
                    print("Column 'review_project_id' already exists. No migration needed.")

                if 'queue_guid' not in columns:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN queue_guid TEXT"))
                    print("Successfully added 'queue_guid' column.")
                else:
                    print("Column 'queue_guid' already exists. No migration needed.")

                if 'queue_index' not in columns:
                    conn.execute(text("ALTER TABLE reviews ADD COLUMN queue_index INTEGER"))
                    print("Successfully added 'queue_index' column.")
                else:
                    print("Column 'queue_index' already exists. No migration needed.")
            else:
                # PostgreSQL: Check each column independently
                for col_name, col_def in [
                    ('review_project_id', 'INTEGER'),
                    ('queue_guid', 'VARCHAR(36)'),
                    ('queue_index', 'INTEGER'),
                ]:
                    result = conn.execute(text("""
                        SELECT column_name 
                        FROM information_schema.columns 
                        WHERE table_name='reviews' AND column_name=:col_name
                    """), {"col_name": col_name})

                    if result.fetchone():
                        print(f"Column '{col_name}' already exists. No migration needed.")
                    else:
                        conn.execute(text(f"ALTER TABLE reviews ADD COLUMN {col_name} {col_def}"))
                        print(f"Successfully added '{col_name}' column.")

            # Migration 7: collection_names_json on review_projects
            print("\nRunning migration: ReviewProject collection_names_json")
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(review_projects)"))
                columns = [row[1] for row in result]
                if 'collection_names_json' not in columns:
                    conn.execute(text("ALTER TABLE review_projects ADD COLUMN collection_names_json TEXT DEFAULT '[]'"))
                    print("Successfully added 'collection_names_json' column to review_projects table.")
                else:
                    print("Column 'collection_names_json' already exists. No migration needed.")
            else:
                result = conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='review_projects' AND column_name='collection_names_json'
                """))
                if result.fetchone():
                    print("Column 'collection_names_json' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE review_projects ADD COLUMN collection_names_json TEXT DEFAULT '[]'"))
                    print("Successfully added 'collection_names_json' column to review_projects table.")

            # Migration 8: add 'SKIP' value to decision enum (PostgreSQL only)
            print("\nRunning migration: decision enum 'SKIP' value")
            if is_sqlite:
                print("SQLite database detected; no enum migration needed.")
            else:
                # Our SQLAlchemy Enum(Decision) stores the ENUM *name*, e.g. 'SKIP'
                # so we only need to ensure the uppercase 'SKIP' label exists.
                result = conn.execute(text("""
                    SELECT 1
                    FROM pg_type t
                    JOIN pg_enum e ON t.oid = e.enumtypid
                    WHERE t.typname = 'decision' AND e.enumlabel = 'SKIP'
                """))
                if result.fetchone():
                    print("Enum value 'SKIP' already exists on type 'decision'. No migration needed.")
                else:
                    conn.execute(text("ALTER TYPE decision ADD VALUE 'SKIP'"))
                    print("Successfully added enum value 'SKIP' to type 'decision'.")

            # Migration 9: guidelines_custom_markdown on review_projects
            print("\nRunning migration: guidelines_custom_markdown")
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(review_projects)"))
                columns = [row[1] for row in result]
                if 'guidelines_custom_markdown' not in columns:
                    conn.execute(text("ALTER TABLE review_projects ADD COLUMN guidelines_custom_markdown TEXT"))
                    print("Successfully added 'guidelines_custom_markdown' column to review_projects table.")
                else:
                    print("Column 'guidelines_custom_markdown' already exists. No migration needed.")
            else:
                result = conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='review_projects' AND column_name='guidelines_custom_markdown'
                """))
                if result.fetchone():
                    print("Column 'guidelines_custom_markdown' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE review_projects ADD COLUMN guidelines_custom_markdown TEXT"))
                    print("Successfully added 'guidelines_custom_markdown' column to review_projects table.")

            # Migration 10: skip_note on review_items (optional note when skipping)
            print("\nRunning migration: skip_note on review_items")
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(review_items)"))
                columns = [row[1] for row in result]
                if 'skip_note' in columns:
                    print("Column 'skip_note' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE review_items ADD COLUMN skip_note TEXT"))
                    print("Successfully added 'skip_note' column to review_items table.")
            else:
                result = conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='review_items' AND column_name='skip_note'
                """))
                if result.fetchone():
                    print("Column 'skip_note' already exists. No migration needed.")
                else:
                    conn.execute(text("ALTER TABLE review_items ADD COLUMN skip_note TEXT"))
                    print("Successfully added 'skip_note' column to review_items table.")

            # Migration 11: reviewer landing virtual queue links toggle on review_projects
            print("\nRunning migration: reviewer landing virtual queue links toggle")
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(review_projects)"))
                columns = [row[1] for row in result]
                if 'show_virtual_queue_links_on_reviewer_landing' in columns:
                    print("Column 'show_virtual_queue_links_on_reviewer_landing' already exists. No migration needed.")
                else:
                    conn.execute(
                        text(
                            "ALTER TABLE review_projects "
                            "ADD COLUMN show_virtual_queue_links_on_reviewer_landing BOOLEAN DEFAULT 1"
                        )
                    )
                    print(
                        "Successfully added 'show_virtual_queue_links_on_reviewer_landing' column "
                        "to review_projects table."
                    )
            else:
                result = conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='review_projects' AND column_name='show_virtual_queue_links_on_reviewer_landing'
                """))
                if result.fetchone():
                    print("Column 'show_virtual_queue_links_on_reviewer_landing' already exists. No migration needed.")
                else:
                    conn.execute(text(
                        "ALTER TABLE review_projects "
                        "ADD COLUMN show_virtual_queue_links_on_reviewer_landing BOOLEAN DEFAULT TRUE"
                    ))
                    print(
                        "Successfully added 'show_virtual_queue_links_on_reviewer_landing' column "
                        "to review_projects table."
                    )

            # Migration 12: publish_to_collection on review_projects
            print("\nRunning migration: publish_to_collection on review_projects")
            if is_sqlite:
                result = conn.execute(text("PRAGMA table_info(review_projects)"))
                columns = [row[1] for row in result]
                if 'publish_to_collection' in columns:
                    print("Column 'publish_to_collection' already exists. No migration needed.")
                else:
                    conn.execute(
                        text("ALTER TABLE review_projects ADD COLUMN publish_to_collection INTEGER")
                    )
                    print("Successfully added 'publish_to_collection' column to review_projects table.")
            else:
                result = conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='review_projects' AND column_name='publish_to_collection'
                """))
                if result.fetchone():
                    print("Column 'publish_to_collection' already exists. No migration needed.")
                else:
                    conn.execute(
                        text("ALTER TABLE review_projects ADD COLUMN publish_to_collection INTEGER")
                    )
                    print("Successfully added 'publish_to_collection' column to review_projects table.")

            # Migration 13: AI reviewer import (projects, project sources, items)
            print("\nRunning migration: AI reviewer import columns")
            for table, column in [
                ('review_projects', 'ai_source_url'),
                ('review_projects', 'ai_callback_url'),
                ('review_projects', 'ai_proposal_json'),
                ('review_project_sources', 'ai_json'),
                ('review_items', 'ai_json'),
            ]:
                if is_sqlite:
                    result = conn.execute(text(f"PRAGMA table_info({table})"))
                    exists = column in [row[1] for row in result]
                else:
                    result = conn.execute(text(f"""
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name='{table}' AND column_name='{column}'
                    """))
                    exists = result.fetchone() is not None
                if exists:
                    print(f"Column '{column}' already exists on {table}. No migration needed.")
                else:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} TEXT"))
                    print(f"Successfully added '{column}' column to {table} table.")

            trans.commit()
            print("\n✓ All migrations completed successfully.")
            
        except Exception as e:
            trans.rollback()
            print(f"\n✗ Error during migration: {e}")
            raise
        finally:
            conn.close()

if __name__ == '__main__':
    run_all_migrations()
