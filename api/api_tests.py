import base64
import btc2fiat
from datetime import datetime, timedelta
import dateutil.parser
import ecdsa
import requests
import time
import unittest

from main import app
from utils import usd2sats

# just a one-pixel PNG used for testing
ONE_PIXEL_PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIW2P4v5ThPwAG7wKklwQ/bwAAAABJRU5ErkJggg==")

# an XPUB to use for tests and some addresses belonging to it
XPUB = "xpub6CUGRUonZSQ4TWtTMmzXdrXDtypWKiKrhko4egpiMZbpiaQL2jkwSB1icqYh2cfDfVxdx4df189oLKnC5fSwqPfgyP3hooxujYzAu3fDVmz"
ADDRESSES = ["1EfgV2Hr5CDjXPavHDpDMjmU33BA2veHy6", "12iNxzdF6KFZ14UyRTYCRuptxkKSSVHzqF", "1CcEugXu9Yf9Qw5cpB8gHUK4X9683WyghM", "15xANZb5vJv5RGL263NFuh8UGgHT7noXeZ", "1PJMBXKBYEBMRDmpAoBRbDff26gHJrawSp", "16ZBYSHkLkRFHAuZvyzosXYgU1UDJxRV1R", "1EHeVKfjjq6FJpix86G2yzFeRbZ6RNg2Zm"]

# an XPUB to test campaigns, different from the other one
CAMPAIGN_XPUB = "xpub661MyMwAqRbcG8Zah6TcX3QpP5yJApaXcyLK8CJcZkuYjczivsHxVL5qm9cw8BYLYehgFeddK5WrxhntpcvqJKTVg96dUVL9P7hZ7Kcvqvd"
CAMPAIGN_ADDRESSES = ["1FbrmmxQGH46x9BqXr5H4p2JK91PRpKkYE", "162cdnDPmqXkuu77PWWi9LugaXuyvsebmP", "1EFfsY9VzwC1RbrfU4xnNCyLfq9NzmeoSh"]

ONE_DOLLAR_SATS = usd2sats(1, btc2fiat.get_value('kraken'))

class TestApi(unittest.TestCase):
    def do(self, f, path, params=None, json=None, headers=None, files=None):
        if files is None:
            files = {}
        BASE_URL = app.config['BASE_URL']
        response = f(f"{BASE_URL}{path}", params=params, json=json, headers=headers, files=files)
        return response.status_code, response.json() if response.status_code in (200, 400, 401, 403, 404) else None

    def get(self, path, params=None, headers=None):
        return self.do(requests.get, path, params=params, headers=headers)

    def post(self, path, json, headers=None, files=None):
        return self.do(requests.post, path, json=json, headers=headers, files=files)

    def put(self, path, json, headers=None, files=None):
        return self.do(requests.put, path, json=json, headers=headers, files=files)

    def delete(self, path, headers=None):
        return self.do(requests.delete, path, headers=headers)

    def get_auth_headers(self, token):
        return {'X-Access-Token': token}

    def update_user(self, token, expect_success=True, **kwargs):
        code, response = self.put("/api/users/me", kwargs,
            headers=self.get_auth_headers(token))
        if expect_success:
            self.assertEqual(code, 200)
        return code, response

    def create_user(self, **kwargs):
        code, response = self.get("/api/login")
        self.assertEqual(code, 200)
        self.assertIn('k1', response)
        self.assertIn('svg', response['qr'])

        k1 = response['k1']

        sk = ecdsa.SigningKey.generate(curve=ecdsa.SECP256k1)
        sig = sk.sign_digest(bytes.fromhex(k1), sigencode=ecdsa.util.sigencode_der)

        code, response = self.get("/api/login",
            {'k1': k1,
             'key': sk.verifying_key.to_string().hex(),
             'sig': sig.hex()})
        self.assertEqual(code, 200)
        self.assertNotIn('token', response)

        code, response = self.get("/api/login",
            {'k1': k1})
        self.assertEqual(code, 200)
        self.assertIn('token', response)

        token = response['token']

        code, response = self.get("/api/users/me", headers=self.get_auth_headers(token))
        self.assertEqual(code, 200)
        app.logger.info(f"Created user: ID={response['user']['id']}")
        self.assertIsNone(response['user']['twitter_username'])
        self.assertIsNone(response['user']['contribution_percent'])

        self.update_user(token, **kwargs)

        return k1, token

    def test_campaigns(self):
        _, token_1 = self.create_user(contribution_percent=1)
        _, token_2 = self.create_user()
        _, token_3 = self.create_user(twitter_username='buyer')

        # creating a campaign requires log in
        code, response = self.post("/api/users/me/campaigns", {})
        self.assertEqual(code, 401)
        self.assertIn("missing token", response['message'].lower())

        # GET my campaigns to see there are none
        code, response = self.get("/api/users/me/campaigns",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['campaigns']), 0)

        # can't create a campaign without name, description or XPUB
        for what in ['name', 'description']:
            code, response = self.post("/api/users/me/campaigns",
                {k: v for k, v in {'xpub': CAMPAIGN_XPUB, 'name': "T", 'description': "D"}.items() if k != what},
                headers=self.get_auth_headers(token_1))
            self.assertEqual(code, 400)
            self.assertIn("missing", response['message'].lower())
            self.assertIn(what, response['message'].lower())

        # finally create a campaign
        code, response = self.post("/api/users/me/campaigns",
            {'xpub': CAMPAIGN_XPUB,
             'name': "My campaign",
             'description': "A very noble cause"},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertIn('campaign', response)

        campaign_key = response['campaign']['key']

        # GET campaigns to find our campaign
        code, response = self.get("/api/users/me/campaigns",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['campaigns']), 1)
        self.assertEqual(response['campaigns'][0]['key'], campaign_key)

        # GET the newly created campaign by key (even unauthenticated!)
        code, response = self.get(f"/api/campaigns/{campaign_key}")
        self.assertEqual(code, 200)
        self.assertEqual(response['campaign']['key'], campaign_key)

        # create a 2nd campaign, this time for the 2nd user
        code, response = self.post("/api/users/me/campaigns",
            {'name': "His campaign",
             'description': "Another noble cause",
             'xpub': CAMPAIGN_XPUB},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertIn('campaign', response)

        campaign_key_2 = response['campaign']['key']

        # the two campaigns differ indeed
        self.assertNotEqual(campaign_key, campaign_key_2)

        # listing one user's campaigns does not return the other one
        code, response = self.get("/api/users/me/campaigns",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['campaigns']), 1)
        self.assertEqual(response['campaigns'][0]['key'], campaign_key_2)

        # edit the campaign
        code, response = self.put(f"/api/campaigns/{campaign_key_2}",
            {'xpub': XPUB, # this will not change!
             'name': "His brilliant campaign",
             'description': "Another brilliant cause"},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)

        # check that the edit worked
        code, response = self.get(f"/api/campaigns/{campaign_key_2}",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(response['campaign']['xpub'], CAMPAIGN_XPUB) # note that the XPUB of a campaign does not change
        self.assertEqual(response['campaign']['name'], "His brilliant campaign")
        self.assertEqual(response['campaign']['description'], "Another brilliant cause")

        # can't edit somebody else's campaign
        code, response = self.put(f"/api/campaigns/{campaign_key_2}",
            {'name': "A fake cause"},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 401)

        # add a listing to the campaign
        code, response = self.post(f"/api/campaigns/{campaign_key_2}/listings",
            {'title': "A listing for a cause",
             'description': "Selling something boring to raise money for good",
             'shipping_domestic_usd': 5,
             'shipping_worldwide_usd': 10,
             'price_usd': 10,
             'available_quantity': 5},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertIn('listing', response)

        listing_key = response['listing']['key']

        # add an auction to the campaign
        code, response = self.post(f"/api/campaigns/{campaign_key_2}/auctions",
            {'title': "An auction for a cause",
             'description': "Auctioning something boring to raise money for good",
             'start_date': (datetime.utcnow() + timedelta(days=1)).replace(tzinfo=dateutil.tz.tzutc()).isoformat(),
             'duration_hours': 0.005, # 18 seconds
             'shipping_domestic_usd': 5,
             'shipping_worldwide_usd': 10,
             'starting_bid': 10,
             'reserve_bid': 10},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertIn('auction', response)

        auction_key = response['auction']['key']

        # check user details
        code, response = self.get("/api/users/me",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(response['user']['has_items'], True)
        self.assertEqual(response['user']['has_own_items'], False) # campaign items do not count as "own" items

        # same seller, add a listing outside of the campaign
        code, response = self.post(f"/api/users/me/listings",
            {'title': "A selfish listing",
             'description': "Selling something boring to clear up space",
             'shipping_domestic_usd': 5,
             'shipping_worldwide_usd': 10,
             'price_usd': 10,
             'available_quantity': 5},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertIn('listing', response)

        listing_key_2 = response['listing']['key']

        self.assertNotEqual(listing_key, listing_key_2)

        # same seller, add an auction outside the campaign
        code, response = self.post(f"/api/users/me/auctions",
            {'title': "A selfish auction",
             'description': "Auctioning something boring to clear up space",
             'start_date': (datetime.utcnow() + timedelta(days=1)).replace(tzinfo=dateutil.tz.tzutc()).isoformat(),
             'duration_hours': 0.005, # 18 seconds
             'shipping_domestic_usd': 5,
             'shipping_worldwide_usd': 10,
             'starting_bid': 10,
             'reserve_bid': 10},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertIn('auction', response)

        auction_key_2 = response['auction']['key']

        # can start the campaign listing even before setting the XPUB (because it is part of the campaign!)
        code, response = self.put(f"/api/listings/{listing_key}/publish", {},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # can start the campaign auction even before setting the XPUB (because it is part of the campaign!)
        code, response = self.put(f"/api/auctions/{auction_key}/publish", {},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # set the xpub
        _, response = self.update_user(token_1, xpub=XPUB)
        self.assertEqual(response['user']['xpub_index'], 0)

        # start the listing
        code, response = self.put(f"/api/listings/{listing_key_2}/publish", {},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # start the auction
        code, response = self.put(f"/api/auctions/{auction_key_2}/publish", {},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # bidding on both auctions
        code, response = self.post(f"/api/auctions/{auction_key}/bids", {'amount': 888},
            headers=self.get_auth_headers(token_3))
        self.assertEqual(code, 200)
        code, response = self.post(f"/api/auctions/{auction_key_2}/bids", {'amount': 999},
            headers=self.get_auth_headers(token_3))
        self.assertEqual(code, 200)

        # buying the two items
        code, response = self.put(f"/api/listings/{listing_key}/buy", {},
            headers=self.get_auth_headers(token_3))
        self.assertEqual(code, 200)
        code, response = self.put(f"/api/listings/{listing_key_2}/buy", {},
            headers=self.get_auth_headers(token_3))
        self.assertEqual(code, 200)

        time.sleep(20)

        # the seller has four sales
        code, response = self.get("/api/users/me/sales", {},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['sales']), 4)
        address_for_campaign_listing = [s['address'] for s in response['sales'] if s['item_title'] == "A listing for a cause"][0]
        self.assertIn(address_for_campaign_listing, CAMPAIGN_ADDRESSES)
        address_for_normal_listing = [s['address'] for s in response['sales'] if s['item_title'] == "A selfish listing"][0]
        self.assertIn(address_for_normal_listing, ADDRESSES)
        self.assertNotEqual(address_for_campaign_listing, address_for_normal_listing)
        address_for_campaign_auction = [s['address'] for s in response['sales'] if s['item_title'] == "An auction for a cause"][0]
        self.assertIn(address_for_campaign_auction, CAMPAIGN_ADDRESSES)
        address_for_normal_auction = [s['address'] for s in response['sales'] if s['item_title'] == "A selfish auction"][0]
        self.assertIn(address_for_normal_auction, ADDRESSES)
        self.assertNotEqual(address_for_campaign_auction, address_for_normal_auction)

    def test_listings(self):
        _, token_1 = self.create_user(twitter_username='fixie')
        _, token_2 = self.create_user(twitter_username='fixie_buyer')

        # GET listings to see there are none there
        code, response = self.get("/api/users/fixie/listings",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['listings']), 0)

        # can't create a listing without price
        code, response = self.post("/api/users/me/listings",
            {'title': "My 1st fixie",
             'description': "Selling something cool for a fixed price",
             'available_quantity': 10},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 400)
        self.assertIn("missing", response['message'].lower())
        self.assertIn("price", response['message'].lower())

        # finally create a listing
        code, response = self.post("/api/users/me/listings",
            {'title': "My 1st fixie",
             'description': "Selling something cool for a fixed price",
             'shipping_domestic_usd': 5,
             'shipping_worldwide_usd': 10,
             'price_usd': 10,
             'available_quantity': 5},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertIn('listing', response)

        listing_key = response['listing']['key']

        # GET listings to see our new listing
        code, response = self.get("/api/users/fixie/listings?filter=new",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['listings']), 1)
        self.assertEqual(response['listings'][0]['key'], listing_key)
        self.assertEqual(response['listings'][0]['available_quantity'], 5)

        # anonymous users can't buy
        code, response = self.put(f"/api/listings/{listing_key}/buy", {})
        self.assertEqual(code, 401)
        self.assertIn("missing token", response['message'].lower())

        # can't buy because the listing has not started yet
        code, response = self.put(f"/api/listings/{listing_key}/buy", {},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 403)
        self.assertIn("not active", response['message'].lower())

        # the listing is not featured
        code, response = self.get("/api/listings/featured")
        self.assertEqual(code, 200)
        self.assertNotIn(listing_key, [l['key'] for l in response['listings']])

        # can't start the listing before setting the XPUB
        code, response = self.put(f"/api/listings/{listing_key}/publish", {},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 400)
        self.assertIn("xpub", response['message'].lower())

        # set the xpub
        _, response = self.update_user(token_1, xpub=XPUB)
        self.assertEqual(response['user']['xpub_index'], 0)

        # start the listing
        code, response = self.put(f"/api/listings/{listing_key}/publish", {'twitter': True},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # the listing is featured now
        code, response = self.get("/api/listings/featured")
        self.assertEqual(code, 200)
        self.assertIn(listing_key, [l['key'] for l in response['listings']])

        # listing should have 4 images (the ones from Twitter)
        code, response = self.get(f"/api/listings/{listing_key}")
        self.assertEqual(len(response['listing']['media']), 4)

        # other users cannot add images
        code, response = self.post(f"/api/listings/{listing_key}/media",
            headers=self.get_auth_headers(token_2), json={},
            files={'media': ('one_pixel.png', ONE_PIXEL_PNG)})
        self.assertEqual(code, 401)
        code, response = self.get(f"/api/listings/{listing_key}")
        self.assertEqual(len(response['listing']['media']), 4)

        # the owner however, can!
        code, response = self.post(f"/api/listings/{listing_key}/media",
            headers=self.get_auth_headers(token_1), json={},
            files={'media': ('one_pixel.png', ONE_PIXEL_PNG)})
        self.assertEqual(code, 200)
        self.assertTrue(response['media']['url'].endswith('.png'))
        self.assertEqual(response['media']['index'], 5)
        media_hash = response['media']['hash']

        code, response = self.get(f"/api/listings/{listing_key}")
        self.assertEqual(len(response['listing']['media']), 5)
        self.assertIn(media_hash, [m['hash'] for m in response['listing']['media']])

        # other users cannot delete images...
        code, response = self.delete(f"/api/listings/{listing_key}/media/{media_hash}",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 401)
        code, response = self.get(f"/api/listings/{listing_key}")
        self.assertEqual(code, 200)
        self.assertEqual(len(response['listing']['media']), 5)

        # CAN EDIT the listing once started, unlike auctions!
        code, response = self.put(f"/api/listings/{listing_key}",
            {'available_quantity': 10, 'media': [{'hash': media_hash, 'index': 500}]},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # anyone looking at our listing will see the changes
        code, response = self.get("/api/users/fixie/listings")
        self.assertEqual(code, 200)
        self.assertEqual(len(response['listings']), 1)
        self.assertEqual(response['listings'][0]['key'], listing_key)
        self.assertEqual(response['listings'][0]['available_quantity'], 10)
        self.assertEqual([m for m in response['listings'][0]['media'] if m['hash'] == media_hash][0]['index'], 500)

        # ... but the owner CAN delete images!
        code, response = self.delete(f"/api/listings/{listing_key}/media/{media_hash}",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # and we are back to 4 now!
        code, response = self.get(f"/api/listings/{listing_key}")
        self.assertEqual(code, 200)
        self.assertEqual(len(response['listing']['media']), 4)
        self.assertNotIn(media_hash, [m['hash'] for m in response['listing']['media']])

        # the seller has no sales
        code, response = self.get("/api/users/me/sales", {},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['sales']), 0)

        # the buyer has no sales
        code, response = self.get("/api/users/me/sales", {},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['sales']), 0)

        # buying an item
        # NB: the seller didn't set a contribution yet, so the default is being used
        code, response = self.put(f"/api/listings/{listing_key}/buy", {},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        fifty_cent_sats = ONE_DOLLAR_SATS / 2
        ten_dollars_sats = ONE_DOLLAR_SATS * 10
        self.assertAlmostEqual(response['sale']['contribution_amount'], fifty_cent_sats, delta=fifty_cent_sats/100)
        self.assertIn('contribution_payment_request', response['sale'])
        self.assertIn('contribution_payment_qr', response['sale'])
        self.assertAlmostEqual(response['sale']['amount'], ten_dollars_sats - fifty_cent_sats, delta=((ten_dollars_sats - fifty_cent_sats) / 100))
        self.assertIn(response['sale']['address'], ADDRESSES)

        self.update_user(token_1, contribution_percent=1.0)

        # buying an item again, after the seller has changed the contribution
        code, response = self.put(f"/api/listings/{listing_key}/buy", {},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        ten_cent_sats = ONE_DOLLAR_SATS / 10
        ten_dollars_sats = ONE_DOLLAR_SATS * 10
        self.assertAlmostEqual(response['sale']['contribution_amount'], ten_cent_sats, delta=ten_cent_sats/100)
        self.assertIn('contribution_payment_request', response['sale'])
        self.assertIn('contribution_payment_qr', response['sale'])
        self.assertAlmostEqual(response['sale']['amount'], ten_dollars_sats - ten_cent_sats, delta=((ten_dollars_sats - ten_cent_sats) / 100))
        self.assertIn(response['sale']['address'], ADDRESSES)

        code, response = self.get(f"/api/listings/{listing_key}", {},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertIsNone(response['listing']['sales'][0]['contribution_settled_at'])
        self.assertIsNone(response['listing']['sales'][0]['settled_at'])

        code, response = self.get("/api/users/me", headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertTrue(response['user']['xpub_index'] > 0)

        time.sleep(5)

        # now the available quantity is two less, and we have two settled sales!
        code, response = self.get(f"/api/listings/{listing_key}", {},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(response['listing']['available_quantity'], 8)
        self.assertEqual(len(response['listing']['sales']), 2)
        for s in response['listing']['sales']:
            self.assertIsNotNone(s['contribution_settled_at'])
            self.assertIsNotNone(s['settled_at'])
            self.assertTrue(s['settled_at'] > s['contribution_settled_at'])
            self.assertTrue(s['txid'].startswith('MOCK_'))
            self.assertIsNone(s['expired_at'])

        # the seller has two sales
        code, response = self.get("/api/users/me/sales", {},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['sales']), 2)
        self.assertIn(response['sales'][0]['address'], ADDRESSES)
        self.assertIn(response['sales'][1]['address'], ADDRESSES)

        # the buyer has no sales
        code, response = self.get("/api/users/me/sales", {},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['sales']), 0)

        # can simply DELETE the listing while active, unlike auctions!
        code, response = self.delete(f"/api/listings/{listing_key}",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # and... GONE it is
        code, response = self.get(f"/api/listings/{listing_key}", {},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 404)

    def test_000_user(self):
        code, response = self.get("/api/login")
        self.assertEqual(code, 200)
        self.assertIn('k1', response)
        self.assertIn('svg', response['qr'])

        k1 = response['k1']

        sk = ecdsa.SigningKey.generate(curve=ecdsa.SECP256k1)
        sig = sk.sign_digest(bytes.fromhex(k1), sigencode=ecdsa.util.sigencode_der)

        # not logged in yet...
        code, response = self.get("/api/login", {'k1': k1})
        self.assertEqual(code, 200)
        self.assertFalse(response['success'])

        # try sending another k1 (but properly signed)...
        another_k1 = list(bytes.fromhex(k1))
        another_k1[0] = (another_k1[0] + 1) % 255
        another_k1 = bytes(another_k1)
        another_sig = sk.sign_digest(another_k1, sigencode=ecdsa.util.sigencode_der)
        code, response = self.get("/api/login",
            {'k1': another_k1.hex(),
             'key': sk.verifying_key.to_string().hex(),
             'sig': another_sig.hex()})
        self.assertEqual(code, 400)
        self.assertIn("verification failed", response['message'].lower())

        # try sending a wrong signature
        code, response = self.get("/api/login",
            {'k1': k1,
             'key': sk.verifying_key.to_string().hex(),
             'sig': another_sig.hex()})
        self.assertEqual(code, 400)
        self.assertIn("verification failed", response['message'].lower())

        code, response = self.get("/api/login",
            {'k1': k1,
             'key': sk.verifying_key.to_string().hex(),
             'sig': sig.hex()})
        self.assertEqual(code, 200)
        self.assertNotIn('token', response)

        code, response = self.get("/api/login",
            {'k1': k1})
        self.assertEqual(code, 200)
        self.assertIn('token', response)
        self.assertIn('user', response)
        self.assertIsNone(response['user']['twitter_username'])

        token_1 = response['token']

        # can't request the token again if we already got it once
        code, response = self.get("/api/login",
            {'k1': k1,
             'key': sk.verifying_key.to_string().hex(),
             'sig': sig.hex()},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 400)

        code, response = self.get("/api/users/me", headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertTrue(response['user']['is_moderator']) # because this is the first user created, so it has the ID=1

        # set user details
        self.update_user(token_1, twitter_username='username1', contribution_percent=1)

        # check user details again
        code, response = self.get("/api/users/me",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(response['user']['twitter_username'], 'username1')
        self.assertFalse(response['user']['twitter_username_verified'])
        self.assertIn("/mock-s3-files/", response['user']['profile_image_url'])
        self.assertEqual(response['user']['contribution_percent'], 1)
        self.assertEqual(response['user']['has_items'], False)
        self.assertEqual(response['user']['has_own_items'], False)

        code, response = self.update_user(token_1, False, email="brokenemail")
        self.assertEqual(code, 400)
        self.assertIn("not valid", response['message'])

        code, response = self.update_user(token_1, False, email="brokenemail@plebinexistingdomain.com")
        self.assertEqual(code, 400)
        self.assertIn("not valid", response['message']) # inexisting domain

        _, response = self.update_user(token_1, email="goodemail@plebeian.market")
        self.assertEqual(response['user']['email'], "goodemail@plebeian.market")

        # try to verify the Twitter username
        code, response = self.put("/api/users/me/verify/twitter",
            {'phrase': "i hate you"},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 400)

        # check user details (again)
        code, response = self.get("/api/users/me",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(response['user']['twitter_username'], 'username1')
        self.assertFalse(response['user']['twitter_username_verified'])

        # verify Twitter for good now
        code, response = self.put("/api/users/me/verify/twitter",
            {'phrase': "i am ME"},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # check user details (yet again)
        code, response = self.get("/api/users/me",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(response['user']['twitter_username'], 'username1')
        self.assertTrue(response['user']['twitter_username_verified'])

        # check user notifications
        code, response = self.get("/api/users/me/notifications",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertTrue(len(response['notifications']) > 0)
        self.assertTrue(all(n['action'] == 'NONE' for n in response['notifications']))

        # set a notification for the user
        first_notification_type = response['notifications'][0]['notification_type']
        code, response = self.put("/api/users/me/notifications",
            {'notifications': [{'notification_type': first_notification_type, 'action': 'TWITTER_DM'}]},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # check user notifications again and we should find the one just set
        code, response = self.get("/api/users/me/notifications",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertTrue(len(response['notifications']) > 0)
        self.assertEqual([n for n in response['notifications'] if n['notification_type'] == first_notification_type][0]['action'], 'TWITTER_DM')

        # create another user
        k1_2, token_2 = self.create_user(contribution_percent=1)
        self.assertNotEqual(k1, k1_2)
        self.assertNotEqual(token_1, token_2)

        # set user details
        code, response = self.update_user(token_2, twitter_username='username2')
        self.assertEqual(code, 200)

        # can't use the same Twitter username
        code, response = self.update_user(token_2, twitter_username='username1', expect_success=False)
        self.assertEqual(code, 400)
        self.assertIn("already registered", response['message'])

        # can't set the same email
        code, response = self.update_user(token_2, email="goodemail@plebeian.market", expect_success=False)
        self.assertEqual(code, 400)
        self.assertIn("already registered", response['message'])

        # ... but can set another email
        code, response = self.update_user(token_2, email="goodemail2@plebeian.market")
        self.assertEqual(code, 200)

        # 2nd user is not a moderator!
        code, response = self.get("/api/users/me",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(response['user']['twitter_username'], 'username2')
        self.assertFalse(response['user']['twitter_username_verified'])
        self.assertEqual(response['user']['email'], "goodemail2@plebeian.market")
        self.assertIsNotNone(response['user']['contribution_percent'])
        self.assertIsNone(response['user'].get('is_moderator'))

        # create an auction
        code, response = self.post("/api/users/me/auctions",
            {'title': "An auction from user 2",
             'description': "Selling something",
             'start_date': (datetime.utcnow() + timedelta(days=1)).replace(tzinfo=dateutil.tz.tzutc()).isoformat(),
             'duration_hours': 24,
             'shipping_domestic_usd': 5,
             'shipping_worldwide_usd': 10,
             'starting_bid': 10,
             'reserve_bid': 10},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertIn('auction', response)

        auction_key = response['auction']['key']

        # the auction is not featured
        code, response = self.get("/api/auctions/featured")
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 0)

        # can't start the auction without xpub
        code, response = self.put(f"/api/auctions/{auction_key}/publish", {},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 400)
        self.assertIn("xpub", response['message'].lower())

        # set the xpub
        _, response = self.update_user(token_2, xpub=XPUB)
        self.assertEqual(response['user']['xpub_index'], 0)

        # start the auction
        code, response = self.put(f"/api/auctions/{auction_key}/publish", {},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)

        # now the auction is "featured"
        code, response = self.get("/api/auctions/featured")
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 1)
        self.assertEqual(set(a['key'] for a in response['auctions']), {auction_key})

        # a normal user can't unfeature an auction (even if he is the owner!)
        code, response = self.put(f"/api/auctions/{auction_key}",
            {'is_hidden': True},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 401)

        # a moderator can however unfeature an auction
        code, response = self.put(f"/api/auctions/{auction_key}",
            {'is_hidden': True},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # but the same moderator can't EDIT another user's auction
        code, response = self.put(f"/api/auctions/{auction_key}",
            {'starting_bid': 100},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 401)

        # the auction has now been unfeatured
        code, response = self.get("/api/auctions/featured")
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 0)

    def test_auctions(self):
        _, token_1 = self.create_user(twitter_username='auction_user_1', contribution_percent=1, xpub=XPUB)
        _, token_2 = self.create_user(twitter_username='auction_user_2', xpub=XPUB)

        # GET user auctions if not logged in is OK
        code, response = self.get("/api/users/auction_user_1/auctions")
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 0)  # no auctions yet

        # creating auctions requires log in
        code, response = self.post("/api/users/me/auctions",
            {'starting_bid': 10})
        self.assertEqual(code, 401)
        self.assertFalse(response['success'])
        self.assertIn("missing token", response['message'].lower())

        # GET auctions if logged in as well to see there are none there
        code, response = self.get("/api/users/me/auctions",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 0)

        # can't create an auction without dates or duration
        code, response = self.post("/api/users/me/auctions",
            {'title': "My 1st",
             'description': "Selling something",
             'starting_bid': 10,
             'reserve_bid': 10},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 400)
        self.assertIn("missing", response['message'].lower())
        self.assertIn("duration", response['message'].lower())

        # dates must be UTC
        code, response = self.post("/api/users/me/auctions",
            {'title': "My 1st",
             'description': "Selling something",
             'start_date': "2020-10-10T11:11:00",
             'duration_hours': 24,
             'shipping_domestic_usd': 5,
             'shipping_worldwide_usd': 10,
             'starting_bid': 10,
             'reserve_bid': 10},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 400)
        self.assertIn("must be in utc", response['message'].lower())

        # finally create an auction (with token_1)
        code, response = self.post("/api/users/me/auctions",
            {'title': "My 1st",
             'description': "Selling something",
             'start_date': (datetime.utcnow() + timedelta(days=1)).replace(tzinfo=dateutil.tz.tzutc()).isoformat(),
             'duration_hours': 0.003, # 10 seconds
             'shipping_domestic_usd': 5,
             'shipping_worldwide_usd': 10,
             'starting_bid': 10,
             'reserve_bid': 10},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertIn('auction', response)

        auction_key = response['auction']['key']

        # fail to see auction that is not running yet by user that did not create it
        code, response = self.get("/api/users/auction_user_1/auctions?filter=new")
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 0)

        # the auction is not featured because it is not running
        code, response = self.get("/api/auctions/featured")
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 0)

        # the user now has_items
        code, response = self.get("/api/users/me",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(response['user']['has_items'], True)
        self.assertEqual(response['user']['has_own_items'], True)

        # GET auctions to find auction in our "not running" section
        code, response = self.get("/api/users/me/auctions?filter=new",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 1)
        self.assertEqual(response['auctions'][0]['key'], auction_key)
        self.assertEqual(response['auctions'][0]['started'], False)
        self.assertEqual(response['auctions'][0]['ended'], False)

        # GET the newly created auction by key (even unauthenticated!)
        code, response = self.get(f"/api/auctions/{auction_key}")
        self.assertEqual(code, 200)
        self.assertEqual(response['auction']['key'], auction_key)

        # create a 2nd auction, this time for the 2nd user
        code, response = self.post("/api/users/me/auctions",
            {'title': "His 2st",
             'description': "Selling something else",
             'start_date': (datetime.utcnow() + timedelta(days=1)).replace(tzinfo=dateutil.tz.tzutc()).isoformat(),
             'duration_hours': 24,
             'shipping_domestic_usd': 5,
             'shipping_worldwide_usd': 10,
             'starting_bid': 10,
             'reserve_bid': 10},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertIn('auction', response)

        auction_key_2 = response['auction']['key']

        # the two auctions differ indeed
        self.assertNotEqual(auction_key, auction_key_2)

        # listing one user's auctions does not return the other one
        code, response = self.get("/api/users/auction_user_2/auctions",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 1)
        self.assertEqual(response['auctions'][0]['key'], auction_key_2)

        # the first user does not, by default, follow the second auction
        code, response = self.get(f"/api/auctions/{auction_key_2}",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertFalse(response['auction']['following'])

        # start following the auction
        code, response = self.put(f"/api/auctions/{auction_key_2}/follow",
            {'follow': True},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(response['message'], "Started following the auction.")
        app.logger.info(f"{response['message']} {auction_key_2=}")

        # the user is now following the auction
        code, response = self.get(f"/api/auctions/{auction_key_2}",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertTrue(response['auction']['following'])

        # can't DELETE an auction if not logged in
        code, response = self.delete(f"/api/auctions/{auction_key_2}")
        self.assertEqual(code, 401)

        # also can't DELETE another user's auction
        code, response = self.delete(f"/api/auctions/{auction_key_2}",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 401)

        # also can't EDIT another user's auction
        code, response = self.put(f"/api/auctions/{auction_key_2}",
            {'starting_bid': 100},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 401)

        # can EDIT the auction with the proper user
        code, response = self.put(f"/api/auctions/{auction_key_2}",
            {'starting_bid': 888, 'key': 'NEW_KEY_WONT_WORK'},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)

        # GET the newly edited auction to see the new starting_bid
        # (note that the key did not change, since we can't edit the key!)
        code, response = self.get(f"/api/auctions/{auction_key_2}")
        self.assertEqual(code, 200)
        self.assertEqual(response['auction']['key'], auction_key_2) # didn't change
        self.assertEqual(response['auction']['starting_bid'], 888)

        # can DELETE the auction with the proper auth headers
        code, response = self.delete(f"/api/auctions/{auction_key_2}",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)

        # can't GET the deleted auction anymore
        code, response = self.get(f"/api/auctions/{auction_key_2}")
        self.assertEqual(code, 404)

        # anonymous users can't place a bid
        code, response = self.post(f"/api/auctions/{auction_key}/bids", {'amount': 100})
        self.assertEqual(code, 401)
        self.assertIn("missing token", response['message'].lower())

        # can't place a bid because the auction has not started yet
        code, response = self.post(f"/api/auctions/{auction_key}/bids", {'amount': 888},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 403)
        self.assertIn("not started", response['message'].lower())

        # start the auction
        code, response = self.put(f"/api/auctions/{auction_key}",
            {'start_date': datetime.utcnow().replace(tzinfo=dateutil.tz.tzutc()).isoformat(),
             'duration_hours': 0.003}, # 10 seconds
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)

        # now the auction is "featured"
        code, response = self.get("/api/auctions/featured")
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 1)
        self.assertEqual(response['auctions'][0]['key'], auction_key)

        # all users can list the auction now that its started
        # from the stall view in the "running" tag
        # user 1 (owner)
        code, response = self.get("/api/users/auction_user_1/auctions",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 1)
        # user 2 (logged in - not owner)
        code, response = self.get(
            "/api/users/auction_user_1/auctions",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 1)
        # unauthenticated user
        code, response = self.get("/api/users/auction_user_1/auctions")
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auctions']), 1)

        # can't EDIT the auction once started
        code, response = self.put(f"/api/auctions/{auction_key}",
            {'starting_bid': 101},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 403)
        self.assertIn("cannot edit auctions once started", response['message'].lower())

        # also can't DELETE the auction once started
        code, response = self.delete(f"/api/auctions/{auction_key}",
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 403)
        self.assertIn("cannot edit auctions once started", response['message'].lower())

        _, token_3 = self.create_user()

        # subscribe to new bid notifications and start following, both with the user that will bid and with a 3rd one
        for t in [token_2, token_3]:
            code, response = self.put("/api/users/me/notifications",
                {'notifications': [{'notification_type': 'NEW_BID', 'action': 'TWITTER_DM'}]},
                headers=self.get_auth_headers(t))
            self.assertEqual(code, 200)
            code, response = self.put(f"/api/auctions/{auction_key}/follow",
                {'follow': True},
                headers=self.get_auth_headers(t))
            self.assertEqual(code, 200)
            self.assertEqual(response['message'], "Started following the auction.")
            app.logger.info(f"{response['message']} {auction_key=}")

        # the user has no messages yet
        code, response = self.get("/api/users/me/messages?via=all",
            headers=self.get_auth_headers(token_3))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['messages']), 0)

        # users can place a bid
        code, response = self.post(f"/api/auctions/{auction_key}/bids", {'amount': 888},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertIn('payment_request', response)
        self.assertTrue(response['payment_request'].startswith('MOCK'))
        self.assertIn('svg', response['qr'])
        self.assertEqual(len(response['messages']), 1) # no message about follow, since we already did that

        bid_payment_request = response['payment_request']

        # auction has no (settled) bids... yet
        code, response = self.get(f"/api/auctions/{auction_key}",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auction']['bids']), 0)

        app.logger.warning("Waiting for the bid to settle...")
        time.sleep(4)

        # the user was notified of the new bid!
        code, response = self.get("/api/users/me/messages?via=all",
            headers=self.get_auth_headers(token_3))
        self.assertEqual(code, 200)
        app.logger.warn(f"{response['messages']}")
        self.assertEqual(len(response['messages']), 1)
        self.assertIn("new bid", response['messages'][0]['body'].lower())
        self.assertEqual(response['messages'][0]['notified_via'], 'TWITTER_DM')

        # the bidder however was not...
        code, response = self.get("/api/users/me/messages?via=all",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['messages']), 0)

        # auction has our settled bid! but no winner decided.
        code, response = self.get(f"/api/auctions/{auction_key}",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auction']['bids']), 1)
        self.assertEqual(response['auction']['bids'][0]['payment_request'], bid_payment_request)
        self.assertIsNone(response['auction']['has_winner'])

        # can't place a bid lower than the previous one now
        code, response = self.post(f"/api/auctions/{auction_key}/bids", {'amount': 777},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 400)
        self.assertIn("your bid needs to be higher", response['message'].lower())

        # create an auction without a start date
        code, response = self.post("/api/users/me/auctions",
            {'title': "Auction without start date",
             'description': "Selling something on Twitter",
             'duration_hours': 24,
             'shipping_domestic_usd': 5,
             'shipping_worldwide_usd': 10,
             'starting_bid': 10,
             'reserve_bid': 10},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertIn('auction', response)

        auction_key_3 = response['auction']['key']

        # another user can't start my auction
        code, response = self.put(f"/api/auctions/{auction_key_3}/publish", {},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 401)

        # start the auction and get images from Twitter
        code, response = self.put(f"/api/auctions/{auction_key_3}/publish", {'twitter': True},
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)

        time.sleep(1) # this is not needed for the start to work, but we use it to make sure start_date is in the past

        # starting the auction verified the Twitter account (even though the user didn't "like" the pinned tweet)
        code, response = self.get("/api/users/me",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(response['user']['twitter_username'], 'auction_user_2')
        self.assertTrue(response['user']['twitter_username_verified'])

        code, response = self.get(f"/api/auctions/{auction_key_3}",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertIn('auction', response)
        self.assertTrue(response['auction']['start_date'] < (datetime.utcnow().isoformat() + "Z"))
        self.assertEqual(response['auction']['started'], True)
        self.assertEqual(response['auction']['ended'], False)
        self.assertEqual(dateutil.parser.isoparse(response['auction']['start_date']) + timedelta(hours=24), dateutil.parser.isoparse(response['auction']['end_date']))
        self.assertEqual(len(response['auction']['media']), 4)
        self.assertIn("/mock-s3-files/", response['auction']['media'][0]['url'])

        # Create an auction with malicious input to description
        malicious_desc = '''<script type="text/javascript">alert("malicious")</script>'''
        code, response = self.post("/api/users/me/auctions",
            {'title': "My 1st",
             'description': malicious_desc,
             'start_date': (datetime.utcnow() + timedelta(days=1)).replace(tzinfo=dateutil.tz.tzutc()).isoformat(),
             'duration_hours': 24,
             'shipping_domestic_usd': 5,
             'shipping_worldwide_usd': 10,
             'starting_bid': 10,
             'reserve_bid': 10},
            headers=self.get_auth_headers(token_1))
        self.assertEqual(code, 200)
        self.assertIn('auction', response)
        cleaned_description = response['auction']['description']
        expected_cleaned_description = """&lt;script type="text/javascript"&gt;alert("malicious")&lt;/script&gt;"""
        self.assertEqual(cleaned_description, expected_cleaned_description)

        app.logger.warning("Waiting for the auction to finalize...")
        time.sleep(15)

        # auction should have a winner now, and the winner (token_2) can even see a Sale!
        code, response = self.get(f"/api/auctions/{auction_key}",
            headers=self.get_auth_headers(token_2))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auction']['bids']), 1)
        self.assertTrue(response['auction']['has_winner'])
        self.assertIsNone(response['auction']['sales'][0]['contribution_settled_at'])
        self.assertIsNotNone(response['auction']['sales'][0]['settled_at'])
        self.assertTrue(response['auction']['sales'][0]['txid'].startswith('MOCK_'))
        self.assertIsNone(response['auction']['sales'][0]['expired_at'])
        self.assertIn(response['auction']['sales'][0]['address'], ADDRESSES)

        # another user however, cannot see the sale (but it can see the auction has a winner)
        code, response = self.get(f"/api/auctions/{auction_key}",
            headers=self.get_auth_headers(token_3))
        self.assertEqual(code, 200)
        self.assertEqual(len(response['auction']['bids']), 1)
        self.assertTrue(response['auction']['has_winner'])
        self.assertEqual(response['auction']['sales'], [])
