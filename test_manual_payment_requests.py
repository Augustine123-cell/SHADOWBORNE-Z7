import os
import tempfile
import unittest

from database import Database


class ManualPaymentRequestTests(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        os.unlink(self.path)
        self.db = Database(self.path)
        self.db.init_db()
        self.db.add_or_update_user(101, 'buyer_a', 'Buyer A')
        self.db.add_or_update_user(102, 'buyer_b', 'Buyer B')

    def tearDown(self):
        for suffix in ('', '-wal', '-shm'):
            try:
                os.remove(self.path + suffix)
            except FileNotFoundError:
                pass

    def test_coin_approval_requires_proof_and_only_credits_once(self):
        rid = self.db.create_manual_payment_request(101, 'coins', 25000, 1000, 100)
        self.assertIsNotNone(rid)
        self.assertEqual(self.db.review_manual_payment_request(rid, True, 700)['reason'], 'proof_missing')
        self.assertEqual(self.db.get_user(101)['coins'], 0)
        self.assertTrue(self.db.attach_manual_payment_proof(rid, 101, 'unique-file-a', 'photo', 'unique-proof-a')['ok'])
        approved = self.db.review_manual_payment_request(rid, True, 700)
        self.assertTrue(approved['ok'])
        self.assertEqual(approved['total_coins'], 1100)
        self.assertEqual(self.db.get_user(101)['coins'], 1100)
        self.assertEqual(self.db.review_manual_payment_request(rid, True, 700)['reason'], 'already_handled')
        self.assertEqual(self.db.get_user(101)['coins'], 1100)

    def test_duplicate_proof_rejected_across_requests(self):
        one = self.db.create_manual_payment_request(101, 'coins', 25000, 1000, 100)
        two = self.db.create_manual_payment_request(102, 'coins', 25000, 1000, 100)
        self.assertTrue(self.db.attach_manual_payment_proof(one, 101, 'same-file', 'photo', 'same-unique-proof')['ok'])
        result = self.db.attach_manual_payment_proof(two, 102, 'different-file-id', 'photo', 'same-unique-proof')
        self.assertEqual(result['reason'], 'duplicate_proof')

    def test_premium_approval_grants_once(self):
        rid = self.db.create_manual_payment_request(101, 'premium', 2500, plan_days=30)
        self.assertTrue(self.db.attach_manual_payment_proof(rid, 101, 'premium-proof', 'photo')['ok'])
        result = self.db.review_manual_payment_request(rid, True, 700)
        self.assertTrue(result['ok'])
        self.assertTrue(self.db.premium_info(101)['active'])
        self.assertEqual(self.db.review_manual_payment_request(rid, True, 700)['reason'], 'already_handled')


if __name__ == '__main__':
    unittest.main()
