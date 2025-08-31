# backend/plaid_server.py
import os
import plaid
from plaid.api import plaid_api

PLAID_CLIENT_ID = os.getenv('PLAID_CLIENT_ID')
PLAID_SECRET = os.getenv('PLAID_SECRET')

configuration = plaid.Configuration(
    host=plaid.Environment.Sandbox,
    api_key={'clientId': PLAID_CLIENT_ID, 'secret': PLAID_SECRET}
)
api_client = plaid.ApiClient(configuration)
plaid_client = plaid_api.PlaidApi(api_client)

# Use string literals for broad SDK compatibility
plaid_products = ["transactions"]
plaid_country_codes = ["US"]