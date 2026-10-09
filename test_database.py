import os
import tempfile
import unittest

from database import Database


class DatabaseSmokeTest(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        os.unlink(self.path)
        self.db = Database(self.path)
        self.db.init_db()
        self.db.add_or_update_user(1, 'alice', 'Alice')
        self.db.add_or_update_user(2, 'bob', 'Bob')
        self.db.add_coins(1, 100)
        self.db.add_coins(2, 100)

    def tearDown(self):
        for suffix in ('', '-wal', '-shm'):
            try: os.remove(self.path + suffix)
            except FileNotFoundError: pass

    def test_purchase_rating_refund(self):
        pid = self.db.add_product(self.db.get_categories()[0]['id'], 'Test', 'desc', 40, 'text', 'hello', seller_id=1, status='approved')
        self.assertTrue(self.db.purchase(2, pid, 20)['ok'])
        self.assertTrue(self.db.rate(2, pid, 5))
        from database import iso_ago
        with self.db.tx() as c: c.execute('UPDATE purchases SET purchased_at=? WHERE user_id=2 AND product_id=?',(iso_ago(hours=3),pid))
        self.assertTrue(self.db.request_refund(2, pid, 'The product does not match the description', 5)['ok'])
        self.assertTrue(self.db.review_refund(1, True))
        self.assertEqual(self.db.get_user(2)['coins'], 100)

    def test_redeem_is_idempotent_per_user(self):
        code = self.db.create_redeem_code(25, 1)
        self.assertEqual(self.db.redeem(code, 2), 25)
        self.assertEqual(self.db.redeem(code, 2), 'already_used')

    def test_stars_product_purchase_is_idempotent_and_not_coins(self):
        pid = self.db.add_product(self.db.get_categories()[0]['id'], 'Star Product', 'x', 100, 'text', 'payload', stars_price=20, seller_id=1, status='approved')
        self.assertTrue(self.db.star_product_purchase(2, pid, 'charge-1', 20, 20)['ok'])
        self.assertEqual(self.db.get_user(2)['coins'], 100)
        self.assertFalse(self.db.star_product_purchase(2, pid, 'charge-1', 20, 20)['ok'])

    def test_seller_payout(self):
        self.db.set_seller_status(1, 'approved')
        self.db.add_coins(1, 5000, 'sale', 'seed sale earnings')
        from database import iso_ago
        with self.db.tx() as c: c.execute('UPDATE users SET created_at=? WHERE user_id=1',(iso_ago(days=30),))
        p = self.db.create_seller_payout(1, 2000, 'bank', '08012345678', 'Test Seller', 'OPay', '', 5, 7.5, 0.005)
        self.assertTrue(p['ok'])
        self.assertEqual(self.db.seller_withdrawable(1), 3000)
        self.assertTrue(self.db.review_seller_payout(p['id'], 'approve', 1))
        self.assertTrue(self.db.review_seller_payout(p['id'], 'paid', 1))
        self.assertEqual(self.db.get_user(1)['coins'], 3100)

    def test_manual_coin_request(self):
        rid = self.db.create_coin_request(2, 100, 'ref', 'proof', 'photo')
        self.assertIsNotNone(rid)
        self.assertIsNotNone(self.db.review_request(rid, True))
        self.assertEqual(self.db.get_user(2)['coins'], 200)


    def test_manual_premium_renews_and_restores_seller(self):
        self.db.set_seller_status(1, 'approved')
        rid = self.db.create_premium_request(1, 30, 2500, 'proof-1', 'photo')
        self.assertIsNotNone(rid)
        row = self.db.review_premium_request(rid, True)
        self.assertEqual(row['status'], 'approved')
        self.assertTrue(self.db.premium_info(1)['active'])
        self.assertEqual(self.db.seller_status(1), 'approved')
        old_until = self.db.premium_info(1)['until']
        rid2 = self.db.create_premium_request(1, 60, 5000, 'proof-2', 'photo')
        self.assertIsNotNone(rid2)
        self.db.review_premium_request(rid2, True)
        self.assertGreater(self.db.premium_info(1)['until'], old_until)

    def test_premium_request_rejects_with_reason(self):
        rid = self.db.create_premium_request(2, 90, 7500, 'proof-2', 'photo')
        row = self.db.review_premium_request(rid, False, 'Wrong amount')
        self.assertEqual(row['status'], 'rejected')
        self.assertEqual(row['rejection_reason'], 'Wrong amount')
        self.assertFalse(self.db.premium_info(2)['active'])

if __name__ == '__main__':
    unittest.main()
