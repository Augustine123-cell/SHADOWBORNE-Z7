import logging
import os
import secrets
import sqlite3
import string
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

log = logging.getLogger(__name__)


def utcnow():
    return datetime.now(timezone.utc)


def now_iso():
    return utcnow().isoformat()


def iso_ago(hours=0, days=0):
    return (utcnow() - timedelta(hours=hours, days=days)).isoformat()


# Names are plain text: the emoji lives only in the icon column (keyboards print "icon name").
DEFAULT_CATEGORIES = [
    ('Books & PDFs', '📚'),
    ('Bots', '🤖'),
    ('Digital Tools', '🧰'),
    ('Developer Resources', '💻'),
    ('Databases & Files', '🗄️'),
    ('Templates & Design', '🎨'),
    ('Other Digital', '📦'),
]
PRODUCT_STATUSES = {'pending', 'approved', 'rejected'}
MAX_PENDING_REQUESTS = int(os.getenv('MAX_PENDING_REQUESTS', '3'))
DEFAULT_DB_PATH = os.getenv('DB_PATH', 'shadowborne_mart.db')


class Database:
    def __init__(self, path=DEFAULT_DB_PATH):
        self.path = path
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)

    def _connect(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=30000')
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('PRAGMA synchronous=NORMAL')
        return c

    @contextmanager
    def tx(self):
        c = self._connect()
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except Exception as e:
            c.rollback()
            log.exception('transaction rolled back: %s', e)
            raise
        finally:
            c.close()

    @contextmanager
    def read(self):
        c = self._connect()
        try:
            yield c
        finally:
            c.close()

    def _all(self, sql, params=()):
        with self.read() as c:
            return [dict(r) for r in c.execute(sql, params).fetchall()]

    def _one(self, sql, params=()):
        with self.read() as c:
            r = c.execute(sql, params).fetchone()
            return dict(r) if r else None

    def _scalar(self, sql, params=()):
        with self.read() as c:
            r = c.execute(sql, params).fetchone()
            return r[0] if r else None

    def init_db(self):
        with self.tx() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT NOT NULL DEFAULT '',
                coins INTEGER NOT NULL DEFAULT 0 CHECK(coins >= 0),
                is_banned INTEGER NOT NULL DEFAULT 0,
                is_premium INTEGER NOT NULL DEFAULT 0,
                premium_until TEXT,
                seller_status TEXT NOT NULL DEFAULT 'none',
                seller_code TEXT UNIQUE,
                premium_warn_14_sent TEXT,
                premium_warn_7_sent TEXT,
                premium_expiry_sent TEXT,
                seller_grace_sent TEXT,
                created_at TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                icon TEXT NOT NULL DEFAULT '📦',
                active INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                price INTEGER NOT NULL CHECK(price >= 0),
                stars_price INTEGER NOT NULL DEFAULT 0 CHECK(stars_price >= 0),
                content_type TEXT NOT NULL CHECK(content_type IN ('text','file')),
                content TEXT NOT NULL,
                premium_only INTEGER NOT NULL DEFAULT 0,
                seller_id INTEGER,
                status TEXT NOT NULL DEFAULT 'approved',
                active INTEGER NOT NULL DEFAULT 1,
                rating_avg REAL NOT NULL DEFAULT 0,
                rating_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(category_id) REFERENCES categories(id),
                FOREIGN KEY(seller_id) REFERENCES users(user_id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                price INTEGER NOT NULL,
                seller_share INTEGER NOT NULL DEFAULT 0,
                purchased_at TEXT NOT NULL,
                refunded INTEGER NOT NULL DEFAULT 0,
                UNIQUE(user_id, product_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS coin_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                kind TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS referrals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                referrer_id INTEGER NOT NULL,
                referred_id INTEGER NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                FOREIGN KEY(referrer_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY(referred_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY,
                coins INTEGER NOT NULL CHECK(coins > 0),
                max_uses INTEGER NOT NULL CHECK(max_uses > 0),
                uses INTEGER NOT NULL DEFAULT 0,
                expires_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS redeem_uses (
                code TEXT NOT NULL,
                user_id INTEGER NOT NULL,
                used_at TEXT NOT NULL,
                PRIMARY KEY(code, user_id),
                FOREIGN KEY(code) REFERENCES redeem_codes(code) ON DELETE CASCADE,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS coin_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                coins INTEGER NOT NULL CHECK(coins > 0),
                payment_reference TEXT NOT NULL,
                proof_file_id TEXT,
                proof_type TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS refund_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                purchase_id INTEGER NOT NULL UNIQUE,
                product_id INTEGER NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY(purchase_id) REFERENCES purchases(id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS ratings (
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                created_at TEXT NOT NULL,
                PRIMARY KEY(user_id, product_id),
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS seller_payouts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                seller_id INTEGER NOT NULL,
                amount_coins INTEGER NOT NULL CHECK(amount_coins > 0),
                gross_ngn REAL NOT NULL,
                gross_usdt REAL NOT NULL,
                fee_percent REAL NOT NULL,
                payout_method TEXT NOT NULL CHECK(payout_method IN ('bank','usdt')),
                account_number TEXT,
                account_name TEXT,
                bank_name TEXT,
                usdt_address TEXT,
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','paid','rejected')),
                requested_at TEXT NOT NULL,
                reviewed_at TEXT,
                paid_at TEXT,
                admin_note TEXT NOT NULL DEFAULT '',
                FOREIGN KEY(seller_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS star_product_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                buyer_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                seller_id INTEGER,
                charge_id TEXT NOT NULL UNIQUE,
                stars INTEGER NOT NULL CHECK(stars > 0),
                seller_stars INTEGER NOT NULL DEFAULT 0,
                admin_stars INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY(buyer_id) REFERENCES users(user_id) ON DELETE CASCADE,
                FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE RESTRICT,
                FOREIGN KEY(seller_id) REFERENCES users(user_id) ON DELETE SET NULL
            );
            CREATE TABLE IF NOT EXISTS premium_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan_days INTEGER NOT NULL,
                amount_ngn INTEGER NOT NULL CHECK(amount_ngn > 0),
                payment_reference TEXT NOT NULL DEFAULT '',
                proof_file_id TEXT,
                proof_type TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
                rejection_reason TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS wishlists (user_id INTEGER NOT NULL, product_id INTEGER NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(user_id,product_id), FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE, FOREIGN KEY(product_id) REFERENCES products(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS daily_checkins (user_id INTEGER PRIMARY KEY, last_day TEXT NOT NULL, streak INTEGER NOT NULL DEFAULT 1, FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS star_payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                charge_id TEXT NOT NULL UNIQUE,
                stars INTEGER NOT NULL,
                coins INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS manual_payment_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                request_type TEXT NOT NULL CHECK(request_type IN ('coins','premium')),
                base_coins INTEGER NOT NULL DEFAULT 0,
                bonus_coins INTEGER NOT NULL DEFAULT 0,
                plan_days INTEGER,
                amount_ngn INTEGER NOT NULL CHECK(amount_ngn > 0),
                proof_file_id TEXT,
                proof_unique_id TEXT,
                proof_type TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','rejected')),
                created_at TEXT NOT NULL,
                reviewed_at TEXT,
                reviewed_by INTEGER,
                FOREIGN KEY(user_id) REFERENCES users(user_id) ON DELETE CASCADE
            );
            ''')
            for name, icon in DEFAULT_CATEGORIES:
                # Older databases stored the emoji inside the name too (double emoji in menus). Fix in place.
                old_name = f'{icon} {name}'
                if c.execute('SELECT 1 FROM categories WHERE name=?', (old_name,)).fetchone() and \
                        not c.execute('SELECT 1 FROM categories WHERE name=?', (name,)).fetchone():
                    c.execute('UPDATE categories SET name=? WHERE name=?', (name, old_name))
                c.execute('INSERT OR IGNORE INTO categories(name, icon) VALUES (?, ?)', (name, icon))
            indexes = [
                'CREATE INDEX IF NOT EXISTS idx_purchases_time ON purchases(purchased_at)',
                'CREATE INDEX IF NOT EXISTS idx_products_cat ON products(category_id, active, status)',
                'CREATE INDEX IF NOT EXISTS idx_users_username ON users(lower(username))',
                'CREATE INDEX IF NOT EXISTS idx_refunds_status ON refund_requests(status, id)',
                'CREATE INDEX IF NOT EXISTS idx_requests_status ON coin_requests(status, id)',
                'CREATE INDEX IF NOT EXISTS idx_products_seller ON products(seller_id, active)',
                'CREATE INDEX IF NOT EXISTS idx_purchases_user ON purchases(user_id, refunded)',
                'CREATE INDEX IF NOT EXISTS idx_tx_user ON coin_transactions(user_id, id)',
                'CREATE INDEX IF NOT EXISTS idx_payouts_status ON seller_payouts(status, id)',
                'CREATE INDEX IF NOT EXISTS idx_payouts_seller ON seller_payouts(seller_id, id)',
                'CREATE INDEX IF NOT EXISTS idx_star_product_seller ON star_product_payments(seller_id, id)',
                'CREATE INDEX IF NOT EXISTS idx_premium_requests_status ON premium_requests(status, id)',
                'CREATE INDEX IF NOT EXISTS idx_premium_requests_user ON premium_requests(user_id, id)',
            ]
            for sql in indexes:
                c.execute(sql)
            user_cols = {r['name'] for r in c.execute('PRAGMA table_info(users)').fetchall()}
            for col, ddl in [('seller_tier',"TEXT NOT NULL DEFAULT 'standard'"),('seller_code','TEXT'),('premium_warn_14_sent','TEXT'),('premium_warn_7_sent','TEXT'),('premium_expiry_sent','TEXT'),('seller_grace_sent','TEXT')]:
                if col not in user_cols:
                    c.execute(f'ALTER TABLE users ADD COLUMN {col} {ddl}')
            cols = {r['name'] for r in c.execute('PRAGMA table_info(products)').fetchall()}
            if 'stars_price' not in cols:
                c.execute('ALTER TABLE products ADD COLUMN stars_price INTEGER NOT NULL DEFAULT 0')
            for col, ddl in [('author', "TEXT NOT NULL DEFAULT ''"), ('chapters', 'INTEGER NOT NULL DEFAULT 0'), ('cover_file_id', 'TEXT')]:
                if col not in cols:
                    c.execute(f'ALTER TABLE products ADD COLUMN {col} {ddl}')
            c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_users_seller_code ON users(seller_code) WHERE seller_code IS NOT NULL')
            # Seller IDs exist only for real sellers. Remove the ones older versions gave to everybody.
            c.execute("UPDATE users SET seller_code=NULL WHERE seller_code IS NOT NULL AND seller_status NOT IN ('approved','suspended')")
            c.execute("INSERT OR IGNORE INTO schema_meta(key,value) VALUES('instance_id',?)", (secrets.token_hex(3),))
            coin_cols = {r['name'] for r in c.execute('PRAGMA table_info(coin_requests)').fetchall()}
            if 'amount_ngn' not in coin_cols: c.execute('ALTER TABLE coin_requests ADD COLUMN amount_ngn INTEGER NOT NULL DEFAULT 0')
            manual_cols = {r['name'] for r in c.execute('PRAGMA table_info(manual_payment_requests)').fetchall()}
            if 'proof_file_id' not in manual_cols: c.execute('ALTER TABLE manual_payment_requests ADD COLUMN proof_file_id TEXT')
            if 'proof_type' not in manual_cols: c.execute("ALTER TABLE manual_payment_requests ADD COLUMN proof_type TEXT NOT NULL DEFAULT ''")
            if 'proof_unique_id' not in manual_cols: c.execute("ALTER TABLE manual_payment_requests ADD COLUMN proof_unique_id TEXT")
            c.execute("CREATE INDEX IF NOT EXISTS idx_manual_payment_status ON manual_payment_requests(status,id)")
            c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_manual_payment_proof_unique ON manual_payment_requests(proof_unique_id) WHERE proof_unique_id IS NOT NULL")
            c.execute("INSERT OR REPLACE INTO schema_meta(key,value) VALUES('schema_version','6')")

    def vacuum(self):
        c = self._connect()
        try:
            c.execute('VACUUM')
        finally:
            c.close()

    def backup_to(self, dest):
        os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
        src = self._connect()
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close(); src.close()

    def add_or_update_user(self, uid, username, first_name, pending_ref=None):
        now = now_iso()
        with self.tx() as c:
            existing = c.execute('SELECT user_id FROM users WHERE user_id=?', (uid,)).fetchone()
            if existing:
                c.execute('UPDATE users SET username=?, first_name=?, last_seen=? WHERE user_id=?',
                          (username, first_name or '', now, uid))
            else:
                c.execute('INSERT INTO users(user_id,username,first_name,created_at,last_seen) VALUES(?,?,?,?,?)',
                          (uid, username, first_name or '', now, now))
                if pending_ref and pending_ref != uid and c.execute('SELECT 1 FROM users WHERE user_id=?', (pending_ref,)).fetchone():
                    c.execute('INSERT OR IGNORE INTO referrals(referrer_id,referred_id,created_at) VALUES(?,?,?)',
                              (pending_ref, uid, now))
            admin_ids = {int(x.strip()) for x in os.getenv('ADMIN_IDS','').split(',') if x.strip().isdigit()}
            mono = int(os.getenv('MONOTECH_USER_ID','0') or 0)
            reserve = int(os.getenv('ADMIN_RESERVE_COINS','99999999999'))
            if uid in admin_ids and uid != mono:
                c.execute('UPDATE users SET coins=MAX(coins, ?) WHERE user_id=?', (reserve, uid))
            if uid in admin_ids or uid == mono:
                # Owner and co-admin always hold LIFETIME Premium (is_premium=1, premium_until=NULL).
                c.execute('UPDATE users SET is_premium=1, premium_until=NULL WHERE user_id=?', (uid,))

    def get_user(self, uid):
        return self._one('SELECT * FROM users WHERE user_id=?', (uid,))

    def ensure_lifetime_premium(self, uid):
        """Give an admin lifetime Premium, creating the user row first if they never started the bot."""
        if not uid or uid <= 0:
            return False
        now = now_iso()
        with self.tx() as c:
            if not c.execute('SELECT 1 FROM users WHERE user_id=?', (uid,)).fetchone():
                c.execute('INSERT INTO users(user_id,username,first_name,created_at,last_seen) VALUES(?,?,?,?,?)',
                          (uid, None, '', now, now))
            return c.execute('UPDATE users SET is_premium=1, premium_until=NULL WHERE user_id=?', (uid,)).rowcount == 1

    def find_user(self, target):
        target = str(target).strip()
        if target.startswith('@'):
            target = target[1:]
        if target.isdigit():
            return self.get_user(int(target))
        return self._one('SELECT * FROM users WHERE lower(username)=lower(?)', (target,))

    def get_all_users(self):
        return self._all('SELECT * FROM users ORDER BY created_at DESC')

    def active_users(self, hours=24):
        return self._all('SELECT * FROM users WHERE last_seen>=? ORDER BY last_seen DESC', (iso_ago(hours=hours),))

    def set_banned(self, uid, banned):
        with self.tx() as c:
            return c.execute('UPDATE users SET is_banned=? WHERE user_id=?', (1 if banned else 0, uid)).rowcount == 1

    def _ledger(self, c, uid, amount, kind, note=''):
        c.execute('INSERT INTO coin_transactions(user_id,amount,kind,note,created_at) VALUES(?,?,?,?,?)',
                  (uid, amount, kind, note, now_iso()))

    def create_manual_payment_request(self, uid, request_type, amount_ngn, base_coins=0, bonus_coins=0, plan_days=None):
        if request_type not in ("coins", "premium") or amount_ngn <= 0:
            return None
        if request_type == "coins" and (base_coins <= 0 or bonus_coins < 0 or plan_days is not None):
            return None
        if request_type == "premium" and (plan_days not in (0, 30, 60, 90, 365) or base_coins or bonus_coins):
            return None
        with self.tx() as c:
            u = c.execute("SELECT user_id,is_banned FROM users WHERE user_id=?", (uid,)).fetchone()
            if not u or u["is_banned"]:
                return None
            if c.execute("SELECT 1 FROM manual_payment_requests WHERE user_id=? AND status='pending' AND (proof_file_id IS NOT NULL OR created_at>?)", (uid, iso_ago(hours=1))).fetchone():
                return None
            cur = c.execute("""INSERT INTO manual_payment_requests
                (user_id,request_type,base_coins,bonus_coins,plan_days,amount_ngn,created_at)
                VALUES(?,?,?,?,?,?,?)""", (uid, request_type, base_coins, bonus_coins, plan_days, amount_ngn, now_iso()))
            return cur.lastrowid

    def attach_manual_payment_proof(self, request_id, uid, file_id, proof_type, unique_id=None):
        if not file_id or proof_type not in ("photo", "document"):
            return {"ok": False, "reason": "invalid_proof"}
        with self.tx() as c:
            r = c.execute("SELECT * FROM manual_payment_requests WHERE id=? AND user_id=?", (request_id, uid)).fetchone()
            if not r or r["status"] != "pending":
                return {"ok": False, "reason": "request_unavailable"}
            if r["proof_file_id"]:
                return {"ok": False, "reason": "proof_already_attached"}
            duplicate = c.execute("SELECT 1 FROM manual_payment_requests WHERE proof_file_id=? OR (? IS NOT NULL AND proof_unique_id=?)", (file_id, unique_id, unique_id)).fetchone()
            duplicate = duplicate or c.execute("SELECT 1 FROM coin_requests WHERE proof_file_id=?", (file_id,)).fetchone()
            duplicate = duplicate or c.execute("SELECT 1 FROM premium_requests WHERE proof_file_id=?", (file_id,)).fetchone()
            if duplicate:
                return {"ok": False, "reason": "duplicate_proof"}
            c.execute("UPDATE manual_payment_requests SET proof_file_id=?,proof_unique_id=?,proof_type=? WHERE id=? AND user_id=? AND status='pending' AND proof_file_id IS NULL", (file_id, unique_id, proof_type, request_id, uid))
            return {"ok": True, "request": dict(r)}

    def review_manual_payment_request(self, request_id, approve, admin_id):
        # Atomic and idempotent: a payment request can only be processed once.
        with self.tx() as c:
            r = c.execute("SELECT * FROM manual_payment_requests WHERE id=?", (request_id,)).fetchone()
            if not r or r["status"] != "pending":
                return {"ok": False, "reason": "already_handled"}
            if approve and not r["proof_file_id"]:
                return {"ok": False, "reason": "proof_missing"}
            if not approve:
                c.execute("UPDATE manual_payment_requests SET status='rejected',reviewed_at=?,reviewed_by=? WHERE id=? AND status='pending'", (now_iso(), admin_id, request_id))
                return {"ok": True, "status": "rejected", "request": dict(r)}
            u = c.execute("SELECT is_banned FROM users WHERE user_id=?", (r["user_id"],)).fetchone()
            if not u or u["is_banned"]:
                return {"ok": False, "reason": "user_unavailable"}
            until = None
            if r["request_type"] == "coins":
                total = int(r["base_coins"]) + int(r["bonus_coins"])
                c.execute("UPDATE users SET coins=coins+? WHERE user_id=?", (total, r["user_id"]))
                note = "Manual payment request #{} approved; base={}, bonus={}".format(request_id, r["base_coins"], r["bonus_coins"])
                self._ledger(c, r["user_id"], total, "coin_purchase", note)
            else:
                days = int(r["plan_days"])
                user = c.execute("SELECT premium_until,seller_status FROM users WHERE user_id=?", (r["user_id"],)).fetchone()
                now = utcnow()
                if days != 0:
                    base = datetime.fromisoformat(user["premium_until"]) if user["premium_until"] and datetime.fromisoformat(user["premium_until"]) > now else now
                    until = (base + timedelta(days=days)).isoformat()
                seller_status = "approved" if user["seller_status"] in ("approved", "suspended") else user["seller_status"]
                c.execute("""UPDATE users SET is_premium=1,premium_until=?,seller_status=?,premium_warn_14_sent=NULL,
                    premium_warn_7_sent=NULL,premium_expiry_sent=NULL,seller_grace_sent=NULL WHERE user_id=?""", (until, seller_status, r["user_id"]))
            cur = c.execute("UPDATE manual_payment_requests SET status='approved',reviewed_at=?,reviewed_by=? WHERE id=? AND status='pending'", (now_iso(), admin_id, request_id))
            if cur.rowcount != 1:
                raise RuntimeError("Payment request approval lost atomicity")
            return {"ok": True, "status": "approved", "request": dict(r), "total_coins": int(r["base_coins"]) + int(r["bonus_coins"]), "premium_until": until}

    def add_coins(self, uid, amount, kind='admin_credit', note=''):
        if amount == 0:
            return False
        if amount < 0 and kind not in ('refund', 'admin_debit', 'refund_reversal'):
            raise ValueError(f'negative amount requires a debit/refund kind (got {kind!r})')
        with self.tx() as c:
            cur = c.execute('UPDATE users SET coins=coins+? WHERE user_id=? AND coins+?>=0', (amount, uid, amount))
            if cur.rowcount != 1:
                return False
            self._ledger(c, uid, amount, kind, note)
            return True

    def recent_transactions(self, uid, limit=5):
        return self._all('SELECT amount,kind,note,created_at FROM coin_transactions WHERE user_id=? ORDER BY id DESC LIMIT ?', (uid, limit))

    def get_categories(self):
        return self._all('SELECT id,name,icon FROM categories WHERE active=1 ORDER BY id')

    def get_products(self, category_id):
        return self._all('''SELECT * FROM products WHERE category_id=? AND active=1 AND status='approved'
                            ORDER BY id DESC''', (category_id,))

    def get_product(self, pid):
        return self._one('''SELECT p.*, c.name category_name, c.icon category_icon
                            FROM products p JOIN categories c ON c.id=p.category_id WHERE p.id=?''', (pid,))

    def add_product(self, category_id, name, description, price, content_type, content,
                    premium_only=False, seller_id=None, status='approved', stars_price=0,
                    author='', chapters=0, cover_file_id=None):
        if status not in PRODUCT_STATUSES:
            raise ValueError(f'invalid product status: {status!r}')
        if price < 0 or stars_price < 0:
            raise ValueError('prices must be >= 0')
        if content_type not in ('text', 'file'):
            raise ValueError('content_type must be text or file')
        with self.tx() as c:
            cur = c.execute('''INSERT INTO products(category_id,name,description,price,stars_price,content_type,content,
                           premium_only,seller_id,status,created_at,author,chapters,cover_file_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (category_id, name.strip(), description.strip(), price, stars_price, content_type, content,
                             1 if premium_only else 0, seller_id, status, now_iso(), (author or '').strip(), int(chapters or 0), cover_file_id))
            return cur.lastrowid

    def delete_product(self, pid):
        with self.tx() as c:
            return c.execute('UPDATE products SET active=0 WHERE id=?', (pid,)).rowcount == 1

    def set_product_status(self, pid, status):
        if status not in PRODUCT_STATUSES:
            raise ValueError(f'invalid product status: {status!r}')
        with self.tx() as c:
            return c.execute('UPDATE products SET status=? WHERE id=?', (status, pid)).rowcount == 1

    def pending_products(self):
        return self._all('''SELECT p.*, u.username, u.first_name FROM products p LEFT JOIN users u ON u.user_id=p.seller_id
                            WHERE p.active=1 AND p.status='pending' ORDER BY p.id''')

    def purchase(self, uid, pid, commission=20):
        with self.tx() as c:
            u = c.execute('SELECT * FROM users WHERE user_id=?', (uid,)).fetchone()
            p = c.execute('SELECT * FROM products WHERE id=? AND active=1 AND status=\'approved\'', (pid,)).fetchone()
            if not u or u['is_banned'] or not p:
                return {'ok': False, 'reason': 'unavailable'}
            if p['seller_id'] == uid:
                return {'ok': False, 'reason': 'self'}
            existing = c.execute('SELECT * FROM purchases WHERE user_id=? AND product_id=?', (uid, pid)).fetchone()
            if existing and not existing['refunded']:
                return {'ok': False, 'reason': 'owned'}
            if existing and existing['refunded']:
                rr=c.execute("SELECT reviewed_at FROM refund_requests WHERE purchase_id=? AND status='approved' ORDER BY id DESC LIMIT 1",(existing['id'],)).fetchone()
                if rr and rr['reviewed_at'] and rr['reviewed_at'] > iso_ago(days=10): return {'ok':False,'reason':'refund_cooldown'}
            premium_active = bool(u['is_premium']) and (u['premium_until'] is None or u['premium_until'] > now_iso())
            if p['premium_only'] and not premium_active:
                return {'ok': False, 'reason': 'premium'}
            if u['coins'] < p['price']:
                return {'ok': False, 'reason': 'funds', 'price': p['price'], 'balance': u['coins']}
            from config import MONOTECH_USER_ID
            tier=c.execute('SELECT seller_tier FROM users WHERE user_id=?',(p['seller_id'],)).fetchone() if p['seller_id'] else None
            effective_commission=0 if p['seller_id'] and int(p['seller_id'])==MONOTECH_USER_ID else (10 if tier and tier['seller_tier']=='pro' else commission)
            seller_share = 0 if not p['seller_id'] else (p['price'] * (100 - effective_commission)) // 100
            c.execute('UPDATE users SET coins=coins-? WHERE user_id=?', (p['price'], uid))
            self._ledger(c, uid, -p['price'], 'purchase', f'Product #{pid}')
            if p['seller_id'] and seller_share:
                c.execute('UPDATE users SET coins=coins+? WHERE user_id=?', (seller_share, p['seller_id']))
                self._ledger(c, p['seller_id'], seller_share, 'sale', f'Product #{pid}')
            if existing and existing['refunded']:
                c.execute('UPDATE purchases SET price=?,seller_share=?,purchased_at=?,refunded=0 WHERE id=?',(p['price'],seller_share,now_iso(),existing['id']))
                purchase_id=existing['id']
            else:
                cur = c.execute('INSERT INTO purchases(user_id,product_id,price,seller_share,purchased_at) VALUES(?,?,?,?,?)',(uid, pid, p['price'], seller_share, now_iso())); purchase_id=cur.lastrowid
            return {'ok': True, 'balance': u['coins'] - p['price'], 'purchase_id': purchase_id}

    def already_purchased(self, uid, pid):
        return bool(self._scalar('SELECT 1 FROM purchases WHERE user_id=? AND product_id=? AND refunded=0', (uid, pid)))

    def library(self, uid):
        return self._all('''SELECT p.id,p.name,p.price,pu.purchased_at,pu.refunded FROM purchases pu
                            JOIN products p ON p.id=pu.product_id WHERE pu.user_id=? AND pu.refunded=0 ORDER BY pu.id DESC''', (uid,))

    def purchase_count(self, uid):
        return self._scalar('SELECT COUNT(*) FROM purchases WHERE user_id=? AND refunded=0', (uid,)) or 0

    def refund_eligible(self, uid, pid, hours):
        from config import REFUND_WINDOW_MAX_HOURS, REFUND_WINDOW_MIN_HOURS
        return bool(self._scalar('''SELECT 1 FROM purchases pu LEFT JOIN refund_requests rr ON rr.purchase_id=pu.id
                                   LEFT JOIN star_product_payments sp ON sp.product_id=pu.product_id AND sp.buyer_id=pu.user_id
                                   WHERE pu.user_id=? AND pu.product_id=? AND pu.refunded=0
                                   AND pu.purchased_at>=? AND pu.purchased_at<=? AND rr.id IS NULL AND sp.id IS NULL''', (uid, pid, iso_ago(hours=REFUND_WINDOW_MAX_HOURS), iso_ago(hours=REFUND_WINDOW_MIN_HOURS))))

    def request_refund(self, uid, pid, reason, hours):
        if hours <= 0 or not str(reason).strip():
            return {'ok': False, 'reason': 'reason_required'}
        with self.tx() as c:
            r = c.execute('''SELECT pu.id purchase_id, pu.product_id, pu.price FROM purchases pu
                             WHERE pu.user_id=? AND pu.product_id=? AND pu.refunded=0 AND pu.purchased_at>=? AND pu.purchased_at<=?''',
                          (uid, pid, iso_ago(hours=5), iso_ago(hours=2))).fetchone()
            if not r:
                return {'ok': False, 'reason': 'not_eligible'}
            if c.execute('SELECT 1 FROM refund_requests WHERE purchase_id=?', (r['purchase_id'],)).fetchone():
                return {'ok': False, 'reason': 'already_requested'}
            c.execute('INSERT INTO refund_requests(user_id,purchase_id,product_id,reason,created_at) VALUES(?,?,?,?,?)',
                      (uid, r['purchase_id'], pid, reason[:1000], now_iso()))
            return {'ok': True}

    def pending_refunds(self):
        return self._all('''SELECT rr.*, p.name product_name, p.price, u.username FROM refund_requests rr
                            JOIN products p ON p.id=rr.product_id JOIN users u ON u.user_id=rr.user_id
                            WHERE rr.status='pending' ORDER BY rr.id''')

    def review_refund(self, rid, approve):
        with self.tx() as c:
            r = c.execute('''SELECT rr.*, pu.price, pu.seller_share, pu.user_id, pu.product_id,
                                    p.seller_id
                             FROM refund_requests rr JOIN purchases pu ON pu.id=rr.purchase_id
                             JOIN products p ON p.id=rr.product_id WHERE rr.id=?''', (rid,)).fetchone()
            if not r or r['status'] != 'pending':
                return None
            r = dict(r)
            c.execute('UPDATE refund_requests SET status=?,reviewed_at=? WHERE id=?',
                      ('approved' if approve else 'rejected', now_iso(), rid))
            if approve:
                c.execute('UPDATE purchases SET refunded=1 WHERE id=?', (r['purchase_id'],))
                buyer = c.execute('SELECT 1 FROM users WHERE user_id=?', (r['user_id'],)).fetchone()
                if buyer:
                    c.execute('UPDATE users SET coins=coins+? WHERE user_id=?', (r['price'], r['user_id']))
                    self._ledger(c, r['user_id'], r['price'], 'refund', f"Product #{r['product_id']}")
                if r['seller_id'] and r['seller_share']:
                    seller = c.execute('SELECT coins FROM users WHERE user_id=?', (r['seller_id'],)).fetchone()
                    available = int(seller['coins']) if seller else 0
                    seller_debit = min(available, int(r['seller_share']))
                    if seller_debit:
                        c.execute('UPDATE users SET coins=coins-? WHERE user_id=?', (seller_debit, r['seller_id']))
                        self._ledger(c, r['seller_id'], -seller_debit, 'refund_reversal', f"Product #{r['product_id']}")
                    shortfall = int(r['seller_share']) - seller_debit
                    if shortfall > 0:
                        admin_ids = [int(x.strip()) for x in os.getenv('ADMIN_IDS','').split(',') if x.strip().isdigit()]
                        if admin_ids:
                            admin_id = admin_ids[0]
                            reserve = int(os.getenv('ADMIN_RESERVE_COINS','99999999999'))
                            c.execute('INSERT OR IGNORE INTO users(user_id,username,first_name,coins,created_at,last_seen) VALUES(?,?,?,?,?,?)',
                                      (admin_id, 'admin_reserve', 'Marketplace Reserve', reserve, now_iso(), now_iso()))
                            debited = c.execute('UPDATE users SET coins=coins-? WHERE user_id=? AND coins>=?', (shortfall, admin_id, shortfall)).rowcount
                            if debited == 1:
                                self._ledger(c, admin_id, -shortfall, 'admin_refund_reserve', f"Seller shortfall for refund #{rid}")
                            else:
                                log.error('Admin reserve could not cover refund shortfall %s for refund #%s', shortfall, rid)
                        else:
                            log.warning('No admin reserve configured for seller refund shortfall %s', shortfall)
            return r

    def rate(self, uid, pid, rating):
        if rating not in range(1, 6):
            return False
        with self.tx() as c:
            if not c.execute('SELECT 1 FROM purchases WHERE user_id=? AND product_id=? AND refunded=0', (uid, pid)).fetchone():
                return False
            c.execute('INSERT OR REPLACE INTO ratings(user_id,product_id,rating,created_at) VALUES(?,?,?,?)',
                      (uid, pid, rating, now_iso()))
            row = c.execute('SELECT AVG(rating) avg, COUNT(*) n FROM ratings WHERE product_id=?', (pid,)).fetchone()
            c.execute('UPDATE products SET rating_avg=?,rating_count=? WHERE id=?', (round(row['avg'], 2), row['n'], pid))
            return True

    def premium_info(self, uid):
        u = self.get_user(uid)
        if not u:
            return {'active': False, 'lifetime': False, 'until': None, 'days_left': None, 'grace_until': None, 'seller_code': None}
        now = utcnow()
        lifetime = bool(u['is_premium']) and u['premium_until'] is None
        until = datetime.fromisoformat(u['premium_until']) if u['premium_until'] else None
        active = lifetime or (bool(u['is_premium']) and until and until > now)
        grace_until = (until + timedelta(days=int(os.getenv('PREMIUM_GRACE_DAYS','7')))) if until else None
        days_left = None if not until else (max(0, int((until-now).total_seconds() // 86400) + (1 if (until-now).total_seconds() > 0 else 0)))
        return {'active': active, 'lifetime': lifetime, 'until': u['premium_until'], 'days_left': days_left,
                'grace_until': grace_until.isoformat() if grace_until else None, 'seller_code': u.get('seller_code')}

    def grant_premium_manual(self, uid, days):
        with self.tx() as c:
            u = c.execute('SELECT is_banned,is_premium,premium_until,seller_status FROM users WHERE user_id=?',(uid,)).fetchone()
            if not u or u['is_banned']: return None
            now = utcnow()
            if days == 0:
                until = None
            else:
                base = datetime.fromisoformat(u['premium_until']) if u['premium_until'] and datetime.fromisoformat(u['premium_until']) > now else now
                until = (base + timedelta(days=days)).isoformat()
            seller_status = 'approved' if u['seller_status'] in ('approved','suspended') else u['seller_status']
            c.execute("""UPDATE users SET is_premium=1,premium_until=?,seller_status=?,
                         premium_warn_14_sent=NULL,premium_warn_7_sent=NULL,premium_expiry_sent=NULL,seller_grace_sent=NULL
                         WHERE user_id=?""",(until,seller_status,uid))
            return {'until': until, 'lifetime': days == 0, 'seller_status': seller_status}

    def premium_request_exists(self, uid, days=None):
        if days is None:
            return bool(self._scalar("SELECT 1 FROM premium_requests WHERE user_id=? AND status='pending'", (uid,)))
        return bool(self._scalar("SELECT 1 FROM premium_requests WHERE user_id=? AND plan_days=? AND status='pending'", (uid,days)))

    def create_premium_request(self, uid, days, amount_ngn, proof_file_id, proof_type='', payment_reference=''):
        if days not in (0,30,60,90,365) or amount_ngn <= 0 or not proof_file_id: return None
        with self.tx() as c:
            if c.execute('SELECT 1 FROM coin_requests WHERE proof_file_id=?',(proof_file_id,)).fetchone() or c.execute('SELECT 1 FROM premium_requests WHERE proof_file_id=?',(proof_file_id,)).fetchone(): return None
            if c.execute("SELECT 1 FROM premium_requests WHERE user_id=? AND status='pending'",(uid,)).fetchone(): return None
            cur=c.execute("""INSERT INTO premium_requests(user_id,plan_days,amount_ngn,payment_reference,proof_file_id,proof_type,created_at)
                             VALUES(?,?,?,?,?,?,?)""",(uid,days,amount_ngn,payment_reference[:200],proof_file_id,proof_type,now_iso()))
            return cur.lastrowid

    def pending_premium_requests(self):
        return self._all("""SELECT pr.*,u.username,u.first_name,u.seller_status,u.seller_code
                           FROM premium_requests pr JOIN users u ON u.user_id=pr.user_id
                           WHERE pr.status='pending' ORDER BY pr.id""")

    def review_premium_request(self, rid, approve, reason=''):
        with self.tx() as c:
            r=c.execute('SELECT * FROM premium_requests WHERE id=?',(rid,)).fetchone()
            if not r or r['status']!='pending': return None
            if not approve:
                c.execute("UPDATE premium_requests SET status='rejected',rejection_reason=?,reviewed_at=? WHERE id=?",(reason[:500],now_iso(),rid))
                return dict(r) | {'status':'rejected','rejection_reason':reason[:500]}
            u=c.execute('SELECT * FROM users WHERE user_id=?',(r['user_id'],)).fetchone()
            if not u or u['is_banned']: return None
            now=utcnow()
            if r['plan_days']==0:
                until=None
            else:
                base=datetime.fromisoformat(u['premium_until']) if u['premium_until'] and datetime.fromisoformat(u['premium_until'])>now else now
                until=(base+timedelta(days=r['plan_days'])).isoformat()
            seller_status='approved' if u['seller_status'] in ('approved','suspended') else u['seller_status']
            c.execute("""UPDATE users SET is_premium=1,premium_until=?,seller_status=?,
                         premium_warn_14_sent=NULL,premium_warn_7_sent=NULL,premium_expiry_sent=NULL,seller_grace_sent=NULL
                         WHERE user_id=?""",(until,seller_status,r['user_id']))
            c.execute("UPDATE premium_requests SET status='approved',reviewed_at=? WHERE id=?",(now_iso(),rid))
            return dict(r) | {'status':'approved','premium_until':until,'seller_status':seller_status}

    def seller_access_sync(self, uid):
        with self.tx() as c:
            u=c.execute('SELECT * FROM users WHERE user_id=?',(uid,)).fetchone()
            if not u: return 'none'
            now=utcnow(); until=datetime.fromisoformat(u['premium_until']) if u['premium_until'] else None
            active=bool(u['is_premium']) and (until is None or until>now)
            if active and u['seller_status']=='suspended':
                c.execute("UPDATE users SET seller_status='approved',seller_grace_sent=NULL WHERE user_id=?",(uid,)); return 'approved'
            if u['seller_status']=='approved' and until and now > until + timedelta(days=int(os.getenv('PREMIUM_GRACE_DAYS','7'))):
                c.execute("UPDATE users SET seller_status='suspended' WHERE user_id=?",(uid,)); return 'suspended'
            return u['seller_status']

    def premium_notification_candidates(self):
        return self._all("SELECT * FROM users WHERE is_premium=1 AND premium_until IS NOT NULL ORDER BY user_id")

    def mark_premium_notification(self, uid, column):
        if column not in {'premium_warn_14_sent','premium_warn_7_sent','premium_expiry_sent','seller_grace_sent'}: return False
        with self.tx() as c:
            return c.execute(f'UPDATE users SET {column}=? WHERE user_id=? AND {column} IS NULL',(now_iso(),uid)).rowcount==1

    def seller_status(self, uid):
        self.seller_access_sync(uid)
        return self._scalar('SELECT seller_status FROM users WHERE user_id=?', (uid,)) or 'none'

    def seller_code(self, uid):
        return self._scalar('SELECT seller_code FROM users WHERE user_id=?',(uid,))

    def set_seller_status(self, uid, status):
        if status not in ('none','pending','approved','suspended'):
            raise ValueError('invalid seller status')
        with self.tx() as c:
            ok = c.execute('UPDATE users SET seller_status=? WHERE user_id=?',(status,uid)).rowcount == 1
            if ok and status == 'approved':
                # Seller ID is created at the moment the user becomes a verified seller (and never changes after).
                if not c.execute("SELECT seller_code FROM users WHERE user_id=? AND seller_code IS NOT NULL AND seller_code<>''",(uid,)).fetchone():
                    for _ in range(30):
                        code = 'SB-' + ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(8))
                        if not c.execute('SELECT 1 FROM users WHERE seller_code=?',(code,)).fetchone():
                            c.execute('UPDATE users SET seller_code=? WHERE user_id=?',(code,uid)); break
            return ok

    def instance_id(self):
        return self._scalar("SELECT value FROM schema_meta WHERE key='instance_id'") or '?'

    def seller_stats(self, uid):
        return {
            'sales': self._scalar('SELECT COUNT(*) FROM purchases pu JOIN products p ON p.id=pu.product_id WHERE p.seller_id=? AND pu.refunded=0', (uid,)) or 0,
            'earned': self._scalar('SELECT COALESCE(SUM(seller_share),0) FROM purchases pu JOIN products p ON p.id=pu.product_id WHERE p.seller_id=? AND pu.refunded=0', (uid,)) or 0,
            'products': self._scalar('SELECT COUNT(*) FROM products WHERE seller_id=? AND active=1', (uid,)) or 0,
            'top': self._all('''SELECT p.name, COUNT(*) n, COALESCE(SUM(pu.seller_share),0) earned
                               FROM purchases pu JOIN products p ON p.id=pu.product_id
                               WHERE p.seller_id=? AND pu.refunded=0 GROUP BY p.id ORDER BY n DESC, earned DESC LIMIT 5''', (uid,)),
        }

    def referral_count(self, uid):
        return self._scalar('SELECT COUNT(*) FROM referrals WHERE referrer_id=?', (uid,)) or 0

    def claim_referral(self, uid, reward_ref, reward_new, daily_cap=10):
        with self.tx() as c:
            row = c.execute('SELECT * FROM referrals WHERE referred_id=?', (uid,)).fetchone()
            if not row:
                return None
            if c.execute("SELECT 1 FROM coin_transactions WHERE user_id=? AND kind='referral_bonus' LIMIT 1", (uid,)).fetchone():
                return None
            since = iso_ago(hours=24)
            count = c.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id=? AND created_at>=?', (row['referrer_id'], since)).fetchone()[0]
            if count > daily_cap:
                return row['referrer_id']
            if reward_ref > 0:
                c.execute('UPDATE users SET coins=coins+? WHERE user_id=?', (reward_ref, row['referrer_id']))
                self._ledger(c, row['referrer_id'], reward_ref, 'referral', f'New referral {uid}')
            if reward_new > 0:
                c.execute('UPDATE users SET coins=coins+? WHERE user_id=?', (reward_new, uid))
                self._ledger(c, uid, reward_new, 'referral_bonus', 'Welcome referral bonus')
            return row['referrer_id']

    def create_redeem_code(self, coins, max_uses, expires_at=None):
        if coins <= 0 or max_uses <= 0:
            raise ValueError('coins and max_uses must be positive')
        alphabet = string.ascii_uppercase + string.digits
        with self.tx() as c:
            for _ in range(10):
                code = 'SB-' + ''.join(secrets.choice(alphabet) for _ in range(10))
                try:
                    c.execute('INSERT INTO redeem_codes(code,coins,max_uses,expires_at,created_at) VALUES(?,?,?,?,?)',
                              (code, coins, max_uses, expires_at, now_iso()))
                    return code
                except sqlite3.IntegrityError:
                    continue
        raise RuntimeError('Could not generate unique code')

    def redeem(self, code, uid):
        code = code.strip().upper()
        with self.tx() as c:
            if not c.execute('SELECT 1 FROM users WHERE user_id=?', (uid,)).fetchone():
                return 'no_user'
            row = c.execute('SELECT * FROM redeem_codes WHERE code=?', (code,)).fetchone()
            if not row:
                return 'not_found'
            if row['expires_at'] and row['expires_at'] <= now_iso():
                return 'expired'
            if c.execute('SELECT 1 FROM redeem_uses WHERE code=? AND user_id=?', (code, uid)).fetchone():
                return 'already_used'
            if row['uses'] >= row['max_uses']:
                return 'expired'
            c.execute('INSERT INTO redeem_uses(code,user_id,used_at) VALUES(?,?,?)', (code, uid, now_iso()))
            c.execute('UPDATE redeem_codes SET uses=uses+1 WHERE code=?', (code,))
            c.execute('UPDATE users SET coins=coins+? WHERE user_id=?', (row['coins'], uid))
            self._ledger(c, uid, row['coins'], 'redeem', code)
            return row['coins']

    def create_coin_request(self, uid, coins, ref, proof, proof_type='', amount_ngn=0):
        if coins <= 0:
            raise ValueError('coins must be > 0')
        with self.tx() as c:
            if proof and c.execute('SELECT 1 FROM coin_requests WHERE proof_file_id=? AND proof_type=?',(proof,proof_type)).fetchone(): return None
            pending = c.execute("SELECT COUNT(*) FROM coin_requests WHERE user_id=? AND status='pending'", (uid,)).fetchone()[0]
            if pending >= MAX_PENDING_REQUESTS:
                return None
            cur = c.execute('''INSERT INTO coin_requests(user_id,coins,payment_reference,proof_file_id,proof_type,created_at,amount_ngn)
                               VALUES(?,?,?,?,?,?,?)''', (uid, coins, ref[:200], proof, proof_type, now_iso(), int(amount_ngn or 0)))
            return cur.lastrowid

    def get_pending_requests(self):
        return self._all('''SELECT cr.*, u.username, u.first_name FROM coin_requests cr JOIN users u ON u.user_id=cr.user_id
                            WHERE cr.status='pending' ORDER BY cr.id''')

    def review_request(self, rid, approve):
        with self.tx() as c:
            r = c.execute('SELECT * FROM coin_requests WHERE id=?', (rid,)).fetchone()
            if not r or r['status'] != 'pending':
                return None
            status = 'approved' if approve else 'rejected'
            c.execute('UPDATE coin_requests SET status=?,reviewed_at=? WHERE id=?', (status, now_iso(), rid))
            if approve:
                c.execute('UPDATE users SET coins=coins+? WHERE user_id=?', (r['coins'], r['user_id']))
                self._ledger(c, r['user_id'], r['coins'], 'manual_topup', f'Request #{rid}')
            return dict(r)

    def seller_withdrawable(self, uid):
        # Only sale-earned coins are withdrawable; top-ups, referrals, redeem codes and check-ins never qualify.
        earned=int(self._scalar("SELECT COALESCE(SUM(amount),0) FROM coin_transactions WHERE user_id=? AND kind='sale'",(uid,)) or 0)
        reversed_sales=int(self._scalar("SELECT COALESCE(SUM(pu.seller_share),0) FROM refund_requests rr JOIN purchases pu ON pu.id=rr.purchase_id JOIN products p ON p.id=pu.product_id WHERE p.seller_id=? AND rr.status='approved'",(uid,)) or 0)
        earned-=reversed_sales
        paid_or_reserved=int(self._scalar("SELECT COALESCE(SUM(amount_coins),0) FROM seller_payouts WHERE seller_id=? AND status IN ('pending','approved','paid')",(uid,)) or 0)
        return max(0, earned-paid_or_reserved)

    def create_seller_payout(self, uid, amount_coins, method, account_number='', account_name='', bank_name='', usdt_address='', fee_percent=5.0, ngn_rate=1.0, usdt_rate=0.001):
        if amount_coins <= 0 or method not in ('bank','usdt'): return {'ok': False, 'reason': 'invalid'}
        with self.tx() as c:
            u=c.execute('SELECT coins,seller_status,is_banned,created_at FROM users WHERE user_id=?',(uid,)).fetchone()
            if not u or u['seller_status']!='approved' or u['is_banned']: return {'ok':False,'reason':'not_seller'}
            from config import WITHDRAWAL_MIN_ACCOUNT_AGE_DAYS
            if u['created_at'] > iso_ago(days=WITHDRAWAL_MIN_ACCOUNT_AGE_DAYS): return {'ok':False,'reason':'account_age'}
            available=self.seller_withdrawable(uid)
            if amount_coins>available: return {'ok':False,'reason':'funds','balance':max(0,available)}
            if amount_coins>int(u['coins']): return {'ok':False,'reason':'balance','balance':int(u['coins'])}
            if method=='bank' and (not account_number or not account_name or not bank_name): return {'ok':False,'reason':'bank_details'}
            if method=='usdt' and not usdt_address: return {'ok':False,'reason':'usdt_details'}
            gross_ngn=round(amount_coins*ngn_rate,2); gross_usdt=round(amount_coins*usdt_rate,6)
            net=round((gross_ngn if method=='bank' else gross_usdt)*(1-fee_percent/100),6)
            cur=c.execute('''INSERT INTO seller_payouts(seller_id,amount_coins,gross_ngn,gross_usdt,fee_percent,payout_method,account_number,account_name,bank_name,usdt_address,requested_at)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?)''',(uid,amount_coins,gross_ngn,gross_usdt,fee_percent,method,account_number[:100],account_name[:150],bank_name[:100],usdt_address[:120],now_iso()))
            c.execute('UPDATE users SET coins=coins-? WHERE user_id=? AND coins>=?', (amount_coins, uid, amount_coins))
            self._ledger(c, uid, -amount_coins, 'seller_payout_hold', f'Payout #{cur.lastrowid} reserved')
            return {'ok':True,'id':cur.lastrowid,'amount_coins':amount_coins,'net':net,'gross_ngn':gross_ngn,'gross_usdt':gross_usdt}

    def pending_seller_payouts(self):
        return self._all('''SELECT sp.*,u.username,u.first_name FROM seller_payouts sp JOIN users u ON u.user_id=sp.seller_id WHERE sp.status IN ('pending','approved') ORDER BY sp.id''')

    def review_seller_payout(self, payout_id, action, admin_id, note=''):
        if action not in ('approve','reject','paid'): return None
        with self.tx() as c:
            row=c.execute('SELECT * FROM seller_payouts WHERE id=?',(payout_id,)).fetchone()
            if not row: return None
            row=dict(row)
            if action=='approve' and row['status']!='pending': return None
            if action=='reject' and row['status'] not in ('pending','approved'): return None
            if action=='paid' and row['status']!='approved': return None
            if action=='reject':
                c.execute('UPDATE users SET coins=coins+? WHERE user_id=?',(row['amount_coins'],row['seller_id']))
                self._ledger(c,row['seller_id'],row['amount_coins'],'seller_payout_release',f"Payout #{payout_id} rejected")
                c.execute('UPDATE seller_payouts SET status="rejected",reviewed_at=?,admin_note=? WHERE id=?',(now_iso(),note[:500],payout_id)); return row
            if action=='approve': c.execute('UPDATE seller_payouts SET status="approved",reviewed_at=?,admin_note=? WHERE id=?',(now_iso(),note[:500],payout_id)); return row
            c.execute('UPDATE seller_payouts SET status="paid",paid_at=?,admin_note=? WHERE id=?',(now_iso(),note[:500],payout_id))
            return row

    def star_product_purchase(self, buyer_id, product_id, charge_id, stars, commission=20):
        if stars<=0 or not charge_id: return {'ok':False,'reason':'invalid'}
        with self.tx() as c:
            if c.execute('SELECT 1 FROM star_product_payments WHERE charge_id=?',(charge_id,)).fetchone(): return {'ok':False,'reason':'duplicate'}
            u=c.execute('SELECT * FROM users WHERE user_id=?',(buyer_id,)).fetchone(); p=c.execute('SELECT * FROM products WHERE id=? AND active=1 AND status="approved"',(product_id,)).fetchone()
            if not u or not p or u['is_banned']: return {'ok':False,'reason':'unavailable'}
            if p['seller_id']==buyer_id: return {'ok':False,'reason':'self'}
            if int(p['stars_price'])!=int(stars) or int(p['stars_price'])<=0: return {'ok':False,'reason':'price'}
            if p['premium_only'] and not (u['is_premium'] and (u['premium_until'] is None or u['premium_until']>now_iso())): return {'ok':False,'reason':'premium'}
            if c.execute('SELECT 1 FROM purchases WHERE user_id=? AND product_id=? AND refunded=0',(buyer_id,product_id)).fetchone(): return {'ok':False,'reason':'owned'}
            from config import MONOTECH_USER_ID
            seller_id=p['seller_id']
            tier=c.execute('SELECT seller_tier FROM users WHERE user_id=?',(seller_id,)).fetchone() if seller_id else None
            effective_commission=0 if seller_id and int(seller_id)==MONOTECH_USER_ID else (10 if tier and tier['seller_tier']=='pro' else commission)
            seller_stars=0 if not seller_id else (int(stars)*(100-effective_commission))//100; admin_stars=int(stars)-seller_stars
            cur=c.execute('INSERT INTO purchases(user_id,product_id,price,seller_share,purchased_at,refunded) VALUES(?,?,?,?,?,0)',(buyer_id,product_id,0,0,now_iso()))
            c.execute('INSERT INTO star_product_payments(buyer_id,product_id,seller_id,charge_id,stars,seller_stars,admin_stars,created_at) VALUES(?,?,?,?,?,?,?,?)',(buyer_id,product_id,p['seller_id'],charge_id,stars,seller_stars,admin_stars,now_iso()))
            self._ledger(c,buyer_id,0,'telegram_stars_product',f"Product #{product_id}, {stars} Stars")
            return {'ok':True,'purchase_id':cur.lastrowid,'seller_stars':seller_stars,'admin_stars':admin_stars}

    def set_product_price(self, pid, price):
        if price < 0: return False
        with self.tx() as c:
            return c.execute("UPDATE products SET price=? WHERE id=? AND active=1",(price,pid)).rowcount==1

    def wishlist_users(self, pid):
        return [int(r['user_id']) for r in self._all('SELECT user_id FROM wishlists WHERE product_id=?',(pid,))]

    def toggle_wishlist(self, uid, pid):
        with self.tx() as c:
            if not c.execute("SELECT 1 FROM products WHERE id=? AND active=1 AND status='approved'",(pid,)).fetchone(): return False
            if c.execute('SELECT 1 FROM wishlists WHERE user_id=? AND product_id=?',(uid,pid)).fetchone():
                c.execute('DELETE FROM wishlists WHERE user_id=? AND product_id=?',(uid,pid)); return False
            c.execute('INSERT INTO wishlists(user_id,product_id,created_at) VALUES(?,?,?)',(uid,pid,now_iso())); return True

    def wishlist(self, uid):
        return self._all("SELECT p.* FROM wishlists w JOIN products p ON p.id=w.product_id WHERE w.user_id=? AND p.active=1 AND p.status='approved' ORDER BY w.created_at DESC",(uid,))

    def daily_checkin(self, uid):
        from datetime import datetime, timezone, timedelta
        day=utcnow().date().isoformat()
        with self.tx() as c:
            row=c.execute('SELECT * FROM daily_checkins WHERE user_id=?',(uid,)).fetchone()
            if row and row['last_day']==day: return {'ok':False,'reason':'claimed','streak':row['streak'],'reward':0}
            streak=(int(row['streak'])+1 if row and row['last_day']==(utcnow().date()-timedelta(days=1)).isoformat() else 1)
            reward=min(100,10*streak)
            c.execute('INSERT INTO daily_checkins(user_id,last_day,streak) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET last_day=excluded.last_day,streak=excluded.streak',(uid,day,streak))
            c.execute('UPDATE users SET coins=coins+? WHERE user_id=?',(reward,uid)); self._ledger(c,uid,reward,'daily_checkin',f'Day {streak} streak')
            return {'ok':True,'streak':streak,'reward':reward}

    def set_seller_tier(self, uid, tier):
        if tier not in ('standard','pro'): return False
        with self.tx() as c:
            cols={r['name'] for r in c.execute('PRAGMA table_info(users)').fetchall()}
            if 'seller_tier' not in cols: c.execute("ALTER TABLE users ADD COLUMN seller_tier TEXT NOT NULL DEFAULT 'standard'")
            return c.execute('UPDATE users SET seller_tier=? WHERE user_id=?',(tier,uid)).rowcount==1

    def setup_monotech_partner(self, uid, starting_coins=2000):
        if not uid or uid <= 0: return False
        with self.tx() as c:
            now=now_iso()
            c.execute("INSERT OR IGNORE INTO users(user_id,username,first_name,coins,is_premium,premium_until,seller_status,seller_code,created_at,last_seen) VALUES(?,?,?,?,1,NULL,'approved',?,?,?)",(uid,'MONOTECH','MONOTECH Partner',0,'SB-MONOTECH',now,now))
            row=c.execute('SELECT * FROM users WHERE user_id=?',(uid,)).fetchone()
            if row:
                c.execute("UPDATE users SET is_premium=1,premium_until=NULL,seller_status='approved',seller_code=COALESCE(seller_code,'SB-MONOTECH') WHERE user_id=?",(uid,))
                # Starting coins are granted once, tracked by a unique ledger note.
                if not c.execute("SELECT 1 FROM coin_transactions WHERE user_id=? AND kind='monotech_seed'",(uid,)).fetchone():
                    c.execute('UPDATE users SET coins=coins+? WHERE user_id=?',(starting_coins,uid)); self._ledger(c,uid,starting_coins,'monotech_seed','Partner starting balance; spend-only')
                cols={r['name'] for r in c.execute('PRAGMA table_info(users)').fetchall()}
                if 'seller_tier' in cols: c.execute("UPDATE users SET seller_tier='pro' WHERE user_id=?",(uid,))
                return True
        return False

    def dashboard(self):
        now = now_iso()
        with self.read() as c:
            def one(sql, params=()):
                r = c.execute(sql, params).fetchone()
                return r[0] if r else 0
            out = {
                'users': one('SELECT COUNT(*) FROM users'),
                'active': one('SELECT COUNT(*) FROM users WHERE last_seen>=?', (iso_ago(hours=24),)),
                'banned': one('SELECT COUNT(*) FROM users WHERE is_banned=1'),
                'premium': one('''SELECT COUNT(*) FROM users WHERE (premium_until IS NOT NULL AND premium_until>?)
                                  OR (premium_until IS NULL AND is_premium=1)''', (now,)),
                'sellers': one("SELECT COUNT(*) FROM users WHERE seller_status='approved'"),
                'products': one("SELECT COUNT(*) FROM products WHERE active=1 AND status='approved'"),
                'pending_products': one("SELECT COUNT(*) FROM products WHERE active=1 AND status='pending'"),
                'pending_requests': one("SELECT COUNT(*) FROM coin_requests WHERE status='pending'"),
                'pending_refunds': one("SELECT COUNT(*) FROM refund_requests WHERE status='pending'"),
                'sales': one('SELECT COUNT(*) FROM purchases WHERE refunded=0'),
                'revenue': one('SELECT COALESCE(SUM(price),0) FROM purchases WHERE refunded=0'),
                'seller_payouts': one('SELECT COALESCE(SUM(seller_share),0) FROM purchases WHERE refunded=0'),
                'refunds': one("SELECT COUNT(*) FROM refund_requests WHERE status='approved'"),
                'stars': one('SELECT COALESCE(SUM(stars),0) FROM star_product_payments'),
                'stars_seller': one('SELECT COALESCE(SUM(seller_stars),0) FROM star_product_payments'),
                'stars_admin': one('SELECT COALESCE(SUM(admin_stars),0) FROM star_product_payments'),
                'stars_count': one('SELECT COUNT(*) FROM star_product_payments'),
                'manual_coins': one("SELECT COALESCE(SUM(coins),0) FROM coin_requests WHERE status='approved'"),
            }
            for label, hrs in (('today', 24), ('week', 24 * 7), ('month', 24 * 30)):
                cutoff = iso_ago(hours=hrs)
                out['sales_' + label] = one('SELECT COUNT(*) FROM purchases WHERE refunded=0 AND purchased_at>=?', (cutoff,))
                out['rev_' + label] = one('SELECT COALESCE(SUM(price),0) FROM purchases WHERE refunded=0 AND purchased_at>=?', (cutoff,))
            series = []
            for i in range(6, -1, -1):
                start = (utcnow() - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
                end = start + timedelta(days=1)
                series.append(one('SELECT COUNT(*) FROM purchases WHERE refunded=0 AND purchased_at>=? AND purchased_at<?',
                                  (start.isoformat(), end.isoformat())))
            out['series'] = series
            out['top'] = [dict(r) for r in c.execute('''SELECT p.name, COUNT(*) n, COALESCE(SUM(pu.price),0) rev
                                                        FROM purchases pu JOIN products p ON p.id=pu.product_id
                                                        WHERE pu.refunded=0 GROUP BY p.id ORDER BY n DESC, rev DESC LIMIT 5''').fetchall()]
            return out
