import requests
from flask import Flask, request, jsonify, session, redirect, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bleach  # A library for HTML sanitization
import secrets
import os
import time

app = Flask(__name__)
app.secret_key = os.urandom(24)  # Generate a secret key for session management
limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["100 per day", "10 per minute"]
)

# eBay Browse API base URL
API_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"

# Replace with your eBay API key
API_KEY = "YOUR_EBAY_API_KEY"

@limiter.request_filter
def exempt_users():
    # You can add logic here to exempt certain users or IPs from rate limiting.
    return False

def sanitize_html(text):
    # Use bleach to sanitize HTML input
    allowed_tags = ["a", "abbr", "acronym", "b", "blockquote", "code", "em", "i", "li", "ol", "strong", "ul"]
    return bleach.clean(text, tags=allowed_tags, attributes={}, strip=True)

def generate_csrf_token():
    # Generate a CSRF token and store it in the user's session
    csrf_token = secrets.token_hex(16)
    session["csrf_token"] = csrf_token
    return csrf_token

def fetch_ebay_data(query, retry_count=3):
    # Define the query parameters
    params = {
        "q": query,            # The sanitized search query
        "limit": 10,           # Limit the results to 10 items
    }

    # Define the headers with your eBay API key
    headers = {
        "Authorization": f"Bearer {API_KEY}",
    }

    for attempt in range(retry_count):
        try:
            # Send a GET request to the eBay API
            response = requests.get(API_URL, params=params, headers=headers)

            # Check if the request was successful
            if response.status_code == 200:
                data = response.json()
                # Parse and return the product information with HTML output encoding
                products = []
                for item in data["itemSummaries"]:
                    product = {
                        "title": bleach.linkify(item["title"]),  # Automatically create links from URLs
                        "price": bleach.clean(f"{item['price']['value']} {item['price']['currency']}"),
                        "url": bleach.clean(item["itemWebUrl"])
                    }
                    products.append(product)
                
                # Store the results in the SQLite database using parameterized query
                cursor.executemany("INSERT INTO products (title, price, url) VALUES (?, ?, ?)", [(p["title"], p["price"], p["url"]) for p in products])
                conn.commit()

                return products
            else:
                # Retry the request after a brief delay
                time.sleep(2)
        except Exception as e:
            print(f"An error occurred during eBay API request (attempt {attempt + 1}): {str(e)}")

    # If all retry attempts fail, raise a custom exception
    raise Exception("Failed to fetch data from eBay")

@app.route("/search", methods=["GET"])
@limiter.limit("10 per minute")  # Adjust the rate limit as needed
def search_ebay():
    try:
        # Check for a valid CSRF token in the request
        csrf_token = request.args.get("csrf_token")
        if not csrf_token or csrf_token != session.get("csrf_token"):
            raise ValueError("Invalid CSRF token")

        query = request.args.get("q")
        if not query:
            raise ValueError("Missing 'q' parameter")

        # Sanitize the input query to prevent XSS attacks
        query = sanitize_html(query)

        # Fetch eBay data with retries
        ebay_data = fetch_ebay_data(query)

        return jsonify(ebay_data)
    except ValueError as ve:
        return jsonify({"error": str(ve)}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/search_form", methods=["GET"])
def search_form():
    # Generate a CSRF token for the search form
    csrf_token = generate_csrf_token()
    return f'''
    <form action="{url_for('search_ebay')}" method="get">
        <input type="text" name="q" placeholder="Search query">
        <input type="hidden" name="csrf_token" value="{csrf_token}">
        <input type="submit" value="Search">
    </form>
    '''

if __name__ == "__main__":
    app.run()
