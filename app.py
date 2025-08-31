import os
import traceback
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
import plaid
from plaid.api import plaid_api
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.country_code import CountryCode
from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
from plaid.model.transactions_sync_request import TransactionsSyncRequest
import sqlite3

# --- 1. SETUP ---
# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
# Enable CORS to allow the frontend to communicate with this server
CORS(app)

# Configure the Plaid client
host = plaid.Environment.Sandbox
configuration = plaid.Configuration(
    host=host,
    api_key={
        'clientId': os.getenv('PLAID_CLIENT_ID'),
        'secret': os.getenv('PLAID_SECRET'),
    }
)
api_client = plaid.ApiClient(configuration)
plaid_client = plaid_api.PlaidApi(api_client)

# --- DATABASE HELPER ---
# Note: The database is in the parent directory
DB_PATH = '../finance_tracker.db'

def get_db_connection():
    """Creates a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# --- 2. API ENDPOINTS ---

@app.route('/api/create_link_token', methods=['POST'])
def create_link_token():
    """Creates a Plaid link_token for the frontend to use."""
    try:
        request_data = LinkTokenCreateRequest(
            user=LinkTokenCreateRequestUser(client_user_id='user-id'), # A unique ID for the end user
            client_name='Personal Finance Tracker',
            products=[Products('transactions')],
            country_codes=[CountryCode('US')],
            language='en'
        )
        response = plaid_client.link_token_create(request_data)
        return jsonify(response.to_dict())
    except Exception as e:
        # Provide detailed error logging in the terminal
        print("--- ERROR IN /api/create_link_token ---")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/set_access_token', methods=['POST'])
def set_access_token():
    """Exchanges a public_token for an access_token and saves it."""
    try:
        data = request.get_json()
        public_token = data.get('public_token')
        user_id = data.get('user_id')

        if not public_token or not user_id:
            return jsonify({'status': 'error', 'error': 'Missing public_token or user_id'}), 400

        # Exchange public token for access token
        exchange_request = ItemPublicTokenExchangeRequest(public_token=public_token)
        exchange_response = plaid_client.item_public_token_exchange(exchange_request)
        access_token = exchange_response['access_token']
        item_id = exchange_response['item_id']

        # Save the access_token and item_id to the database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR REPLACE INTO plaid_items (user_id, access_token, item_id) VALUES (?, ?, ?)",
            (user_id, access_token, item_id)
        )
        conn.commit()
        conn.close()

        print(f"✅ --- Access Token captured and saved for user_id: {user_id} --- ✅")
        return jsonify({'status': 'success'})

    except Exception as e:
        print("--- ERROR IN /api/set_access_token ---")
        traceback.print_exc()
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/api/sync_transactions', methods=['POST'])
def sync_transactions():
    """Fetches new transactions from Plaid and saves them to the database."""
    try:
        data = request.get_json()
        user_id = data.get('user_id')

        conn = get_db_connection()
        cursor = conn.cursor()
        # Get the access token for the user
        cursor.execute("SELECT access_token FROM plaid_items WHERE user_id = ?", (user_id,))
        item = cursor.fetchone()
        
        if not item:
            return jsonify({'status': 'error', 'error': 'No linked account found for this user.'}), 404
        
        access_token = item['access_token']

        # Fetch transactions from Plaid
        plaid_request = TransactionsSyncRequest(access_token=access_token)
        response = plaid_client.transactions_sync(plaid_request)
        transactions = response['added']
        
        # Save new transactions to our database
        category_map = {row['name']: row['id'] for row in cursor.execute("SELECT id, name FROM categories").fetchall()}
        
        new_transaction_count = 0
        for t in transactions:
            # Auto-categorize the transaction based on its name
            category_name = categorize_transaction(t['name'])
            category_id = category_map.get(category_name, category_map['Uncategorized'])
            
            cursor.execute(
                "INSERT INTO transactions (user_id, transaction_date, description, amount, category_id) VALUES (?, ?, ?, ?, ?)",
                (user_id, t['date'], t['name'], t['amount'], category_id)
            )
            new_transaction_count += 1

        conn.commit()
        conn.close()
        
        print(f"✅ --- Synced {new_transaction_count} new transactions for user_id: {user_id} --- ✅")
        return jsonify({'status': 'success', 'new_transactions': new_transaction_count})

    except Exception as e:
        print("--- ERROR IN /api/sync_transactions ---")
        traceback.print_exc()
        return jsonify({'status': 'error', 'error': str(e)}), 500

# Helper function for the backend to categorize transactions
def categorize_transaction(description):
    """A simple keyword-based categorizer for the backend."""
    KEYWORD_MAP = {
        'Food': ['restaurant', 'cafe', 'groceries', 'starbucks', 'mcdonalds'],
        'Transport': ['uber', 'lyft', 'gas', 'metro'],
        'Shopping': ['amazon', 'target', 'walmart', 'store'],
        'Utilities': ['electric', 'comcast', 'verizon', 'water'],
        'Entertainment': ['movies', 'concert', 'netflix', 'spotify'],
        'Housing': ['rent', 'mortgage']
    }
    for category, keywords in KEYWORD_MAP.items():
        if any(keyword in description.lower() for keyword in keywords):
            return category
    return 'Uncategorized'


if __name__ == '__main__':
    app.run(port=5001, debug=True)

