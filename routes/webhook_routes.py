from flask import Blueprint, request, jsonify
from services.alpaca_client import execute_trade, execute_sell
from services.price_fetcher import get_live_price_with_fallback
import logging

webhook_bp = Blueprint('webhook', __name__)

@webhook_bp.route('/', methods=['POST'])
def webhook():
    try:
        # Parse the incoming JSON request
        json_data = request.get_json()
        if not json_data or 'message' not in json_data or 'symbol' not in json_data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON data format'}), 400

        symbol = json_data['symbol']
        message = json_data['message'].lower()  # Normalize message case for comparison

        if message == 'buy':
            # Fetch the current price using the fallback method
            current_price = get_live_price_with_fallback(symbol)
            if current_price:
                execute_trade(symbol, 'buy')
                return jsonify({'status': 'success', 'message': f"Bought {symbol} at ${current_price:.2f}."})
            else:
                return jsonify({'status': 'error', 'message': f"Unable to fetch price for {symbol}."}), 500

        elif message == 'sell':
            # Execute sell action without checking the price
            execute_sell(symbol)
            return jsonify({'status': 'success', 'message': f"Sold {symbol}."})

        else:
            # Handle invalid message types
            return jsonify({'status': 'error', 'message': 'Invalid message type.'}), 400

    except Exception as e:
        # Log the error for debugging
        logging.error(f"Error processing webhook: {e}")
        return jsonify({'status': 'error', 'message': 'Server error.'}), 500

