import os
import sqlite3
import tempfile
import unittest

from database import Database


class OwnerFeatureTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.db'); os.close(fd); os.unlink(self.path)
        self.db = Database(self.path); self.db.init_db()

    def tearDown(self):
        for suffix in ('', '-wal', '-shm'):
            try: os.remove(self.path + suffix)
            except FileNotFoundError: pass

    def test_admin_gets_lifetime_premium_even_before_start(self):
        self.assertTrue(self.db.ensure_lifetime_premium(555))
        info = self.db.premium_info(555)
        self.assertTrue(info['active']); self.assertTrue(info['lifetime'])

    def test_admin_env_ids_get_lifetime_on_first_start(self):
        os.environ['ADMIN_IDS'] = '700'; os.environ['MONOTECH_USER_ID'] = '800'
        try:
            for uid in (700, 800):
                self.db.add_or_update_user(uid, 'x', 'X')
                self.assertTrue(self.db.premium_info(uid)['lifetime'], uid)
            self.assertGreater(self.db.get_user(700)['coins'], 10**9)   # owner reserve
            self.assertLess(self.db.get_user(800)['coins'], 10**9)       # co-admin does not get the reserve
        finally:
            os.environ.pop('ADMIN_IDS'); os.environ.pop('MONOTECH_USER_ID')

    def test_normal_user_is_not_premium(self):
        self.db.add_or_update_user(9, 'bob', 'Bob')
        self.assertFalse(self.db.premium_info(9)['active'])

    def test_owner_can_grant_premium_and_lifetime(self):
        self.db.add_or_update_user(9, 'bob', 'Bob')
        self.assertTrue(self.db.grant_premium_manual(9, 30)['until'])
        self.assertTrue(self.db.premium_info(9)['active'])
        self.assertTrue(self.db.grant_premium_manual(9, 0)['lifetime'])
        self.assertTrue(self.db.premium_info(9)['lifetime'])

    def test_find_user_by_id_and_username(self):
        self.db.add_or_update_user(9, 'Bob_X', 'Bob')
        self.assertEqual(self.db.find_user('9')['user_id'], 9)
        self.assertEqual(self.db.find_user('@bob_x')['user_id'], 9)
        self.assertIsNone(self.db.find_user('@nobody'))

    def test_ban_unban_and_credit(self):
        self.db.add_or_update_user(9, 'bob', 'Bob')
        self.assertTrue(self.db.set_banned(9, True)); self.assertEqual(self.db.get_user(9)['is_banned'], 1)
        self.assertTrue(self.db.set_banned(9, False)); self.assertEqual(self.db.get_user(9)['is_banned'], 0)
        before = self.db.get_user(9)['coins']
        self.assertTrue(self.db.add_coins(9, 250, 'admin_credit', 'gift'))
        self.assertEqual(self.db.get_user(9)['coins'], before + 250)

    def test_active_users_lists_recent(self):
        self.db.add_or_update_user(9, 'bob', 'Bob')
        self.assertIn(9, [u['user_id'] for u in self.db.active_users(24)])

    def test_product_with_cover_author_chapters(self):
        cat = self.db.get_categories()[0]['id']
        pid = self.db.add_product(cat, 'Book', 'desc', 10, 'file', 'FILEID', author='Ada', chapters=12, cover_file_id='COVERID')
        p = self.db.get_product(pid)
        self.assertEqual((p['author'], p['chapters'], p['cover_file_id']), ('Ada', 12, 'COVERID'))
        pid2 = self.db.add_product(cat, 'Old style', 'd', 5, 'text', 'hi', seller_id=None)   # existing callers still work
        self.assertEqual(self.db.get_product(pid2)['chapters'], 0)

    def test_categories_have_no_double_emoji(self):
        names = [c['name'] for c in self.db.get_categories()]
        self.assertIn('Books & PDFs', names)
        self.assertFalse(any(n[0] in '📚🤖🧰💻🗄🎨📦' for n in names))

    def test_old_database_is_upgraded_in_place(self):
        fd, old = tempfile.mkstemp(suffix='.db'); os.close(fd); os.unlink(old)
        try:
            c = sqlite3.connect(old)
            c.executescript('''CREATE TABLE categories(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL UNIQUE,icon TEXT NOT NULL DEFAULT '📦',active INTEGER NOT NULL DEFAULT 1);
                INSERT INTO categories(name,icon) VALUES('📚 Books & PDFs','📚');''')
            c.commit(); c.close()
            db = Database(old); db.init_db(); db.init_db()          # twice = idempotent
            names = [x['name'] for x in db.get_categories()]
            self.assertEqual(names.count('Books & PDFs'), 1)
            self.assertNotIn('📚 Books & PDFs', names)
            cols = {r['name'] for r in db._all('PRAGMA table_info(products)')}
            self.assertTrue({'author', 'chapters', 'cover_file_id'} <= cols)
        finally:
            for suffix in ('', '-wal', '-shm'):
                try: os.remove(old + suffix)
                except FileNotFoundError: pass


if __name__ == '__main__':
    unittest.main()


class SellerIdAndMenuTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.db'); os.close(fd); os.unlink(self.path)
        self.db = Database(self.path); self.db.init_db()

    def tearDown(self):
        for suffix in ('', '-wal', '-shm'):
            try: os.remove(self.path + suffix)
            except FileNotFoundError: pass

    def test_new_user_has_no_seller_id(self):
        self.db.add_or_update_user(5, 'x', 'X')
        self.assertFalse(self.db.seller_code(5))

    def test_seller_id_created_only_on_becoming_seller_and_is_stable(self):
        self.db.add_or_update_user(5, 'x', 'X')
        self.assertTrue(self.db.set_seller_status(5, 'approved'))
        code = self.db.seller_code(5)
        self.assertTrue(code and code.startswith('SB-'))
        self.db.set_seller_status(5, 'suspended'); self.db.set_seller_status(5, 'approved')
        self.assertEqual(self.db.seller_code(5), code)

    def test_old_seller_ids_removed_from_non_sellers_on_upgrade(self):
        self.db.add_or_update_user(5, 'x', 'X'); self.db.add_or_update_user(6, 'y', 'Y')
        with self.db.tx() as c:
            c.execute("UPDATE users SET seller_code='SB-OLDCODE1' WHERE user_id=5")
            c.execute("UPDATE users SET seller_code='SB-REAL0001', seller_status='approved' WHERE user_id=6")
        self.db.init_db()
        self.assertFalse(self.db.seller_code(5))
        self.assertEqual(self.db.seller_code(6), 'SB-REAL0001')

    def test_instance_id_is_stable(self):
        a = self.db.instance_id(); self.db.init_db()
        self.assertEqual(a, self.db.instance_id())

    def test_redeem_code_limits_users(self):
        code = self.db.create_redeem_code(30, 2)
        for uid in (1, 2, 3): self.db.add_or_update_user(uid, f'u{uid}', 'U')
        self.assertEqual(self.db.redeem(code, 1), 30)
        self.assertEqual(self.db.redeem(code, 2), 30)
        self.assertEqual(self.db.redeem(code, 3), 'expired')       # limit of 2 users reached
        self.assertEqual(self.db.get_user(1)['coins'], 30)

    def test_menu_hides_buy_coins_for_admins_only(self):
        import sys, types
        # keyboards imports aiogram; use a tiny stub only if aiogram is missing
        try:
            import aiogram  # noqa
        except ImportError:
            self.skipTest('aiogram not installed in this environment')
        from keyboards import main_menu
        def labels(kb): return [b.text for row in kb.keyboard for b in row]
        self.assertIn('💳 Buy Coins', labels(main_menu(False, False)))
        self.assertNotIn('💳 Buy Coins', labels(main_menu(False, True)))
        self.assertIn('🏪 Become a Seller', labels(main_menu(False, False)))
        self.assertIn('👨‍💼 Seller Panel', labels(main_menu(True, False)))
