import argparse
import os
from datetime import datetime

from config import DB_PATH
from database import Database


def main():
    parser = argparse.ArgumentParser(description='Initialize/upgrade SHADOWBORNE MART database')
    parser.add_argument('--db', default=DB_PATH, help='SQLite database path')
    parser.add_argument('--backup', action='store_true', help='Backup an existing database before migration')
    args = parser.parse_args()

    db = Database(args.db)
    if args.backup and os.path.exists(args.db):
        stamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
        dest = f'{args.db}.{stamp}.bak'
        db.backup_to(dest)
        print(f'Backup created: {dest}')
    db.init_db()
    version = db._scalar("SELECT value FROM schema_meta WHERE key='schema_version'")
    print(f'Database ready: {args.db} (schema v{version})')


if __name__ == '__main__':
    main()
