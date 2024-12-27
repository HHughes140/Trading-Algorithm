import time
import logging
import requests
from flask import Flask, request, jsonify
from alpaca_trade_api.rest import REST
from yahoo_fin import stock_info
import yfinance as yf
import os
from datetime import datetime
from urllib.parse import urlparse
import json

# Create a Flask app
app = Flask(__name__)

# Configure logging
logging.basicConfig(filename='trading_decisions.log', level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Alpaca API setup using environment variables
ALPACA_API_KEY = os.getenv('APCA_API_KEY_ID')
ALPACA_SECRET_KEY = os.getenv('APCA_API_SECRET_KEY')
BASE_URL = 'https://paper-api.alpaca.markets'
TRADE_SYMBOLS = set()  # Set to keep track of actively traded symbols

# Verify environment variables
if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
    raise ValueError("Environment variables for Alpaca API credentials are not set.")

print("APCA_API_KEY_ID:", ALPACA_API_KEY)
print("APCA_API_SECRET_KEY:", ALPACA_SECRET_KEY)

# Convert ParseResult to URL
base_url_parsed = urlparse(BASE_URL)
base_url = base_url_parsed.geturl()

trading_client = REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=base_url)

# Flag to control trading status
is_trading = True


def format_symbol(symbol):
    if "TCU" in symbol:
        return symbol.replace('TCU', 'TC-U')
    if "THU" in symbol:
        return symbol.replace('THU', "TH-U")
    return symbol


def execute_trade(symbol, action):
    global is_trading, TRADE_SYMBOLS
    if not is_trading:
        return

    # Get the account information to retrieve the available USD balance
    account_info = trading_client.get_account()
    usd_balance = float(account_info.cash)

    try:
        # Get the current price for the symbol

        current_price = stock_info.get_live_price(format_symbol(symbol))
        if current_price is not None:
            # Calculate the trade amount as 1/2 of the portfolio's entire balance
            trade_amount = usd_balance / 2
            # Calculate the quantity based on the trade amount and current price
            quantity = trade_amount / current_price

            # Set a fixed adjustment percentage
            adjustment_percentage = 1  # 100% of the calculated quantity
            # Calculate the adjusted quantity
            adjusted_quantity = quantity * adjustment_percentage

            # Preparing market order
            market_order_data = {
                'symbol': symbol,
                'qty': adjusted_quantity,
                'side': action,
                'type': 'market',
                'time_in_force': 'day',
            }

            # Place market order
            order = trading_client.submit_order(**market_order_data)

            # Log the trading decision in a more organized manner
            log_message = f"{order.submitted_at} - Symbol: {symbol}, Decision: {action}, " \
                          f"Price: ${current_price}, Amount: ${quantity * current_price:.2f}"
            logging.info(log_message)

            # Add the symbol to the set of actively traded symbols
            TRADE_SYMBOLS.add(symbol)

        else:
            logging.error(f"Unable to retrieve current price for {symbol}")

    except Exception as e:
        logging.error(f"Error placing order: {e}")


def get_live_price_with_fallback(format_symbol_for_yahoo):
    try:
        # Try Yahoo Finance
        data = yf.Ticker(format_symbol_for_yahoo).history(period='1d')
        if not data.empty:
            return data['Close'].iloc[-1]
        else:
            raise ValueError("No data returned from Yahoo Finance.")
    except Exception as e:
        logging.error(f"Error retrieving price from Yahoo Finance for {format_symbol_for_yahoo}: {e}")
        # Fallback to another source or handle the error
        return None


def process_last_two_filled_sells():
    url_activities = f"{BASE_URL}/v2/account/activities?activity_types=&category=trade_activity&direction=desc&page_size=100"
    url_positions = f"{BASE_URL}/v2/positions"

    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
    }

    # Retrieve account activities
    response_activities = requests.get(url_activities, headers=headers)
    if response_activities.status_code == 200:
        activities_data = response_activities.json()

        # Filter for filled sell orders
        filled_sells = [act for act in activities_data if
                        act['side'] == 'sell' and act.get('qty') is not None and act.get('price') is not None]

        last_two_filled_sells = []

        for i in range(len(filled_sells) - 1):
            if filled_sells[i]['symbol'] == filled_sells[i + 1]['symbol']:
                last_two_filled_sells = [
                    {'symbol': filled_sells[i]['symbol'], 'qty': float(filled_sells[i]['qty']),
                     'price': float(filled_sells[i]['price'])},
                    {'symbol': filled_sells[i + 1]['symbol'], 'qty': float(filled_sells[i + 1]['qty']),
                     'price': float(filled_sells[i + 1]['price'])}
                ]
                break

        if last_two_filled_sells:
            qty1 = last_two_filled_sells[0]['qty']
            qty2 = last_two_filled_sells[1]['qty']
            price1 = last_two_filled_sells[0]['price']
            price2 = last_two_filled_sells[1]['price']

            total_qty = qty1 + qty2
            average_price = (price1 + price2) / 2
            total_value = total_qty * average_price

            logging.info(f"Last two filled sells with the same symbol: {last_two_filled_sells}")
            logging.info(f"Total Quantity: {total_qty}")
            logging.info(f"Average Price: {average_price}")
            logging.info(f"Total Value: {total_value}")

            # Retrieve open positions
            response_positions = requests.get(url_positions, headers=headers)
            if response_positions.status_code == 200:
                positions_data = response_positions.json()
                num_positions = len(positions_data)

                if num_positions > 0:
                    amount_per_position = float(total_value) / num_positions
                    logging.info(f"Number of open positions: {num_positions}")
                    logging.info(f"Amount to invest per position: {amount_per_position}")

                    # Fetch current prices for each symbol using Yahoo Finance
                    for pos in positions_data:
                        symbol = pos['symbol']
                        qty_available = float(pos['qty_available'])  # Ensure to convert qty_available to float

                        # Skip symbols that were just sold
                        if symbol in [s['symbol'] for s in last_two_filled_sells]:
                            continue

                        # Fetch the current price of the symbol using yfinance
                        try:
                            stock = yf.Ticker(symbol)
                            current_price = stock.history(period='1d')['Close'].iloc[-1]  # Get the latest closing price

                            # Calculate quantity to buy
                            qty_to_buy = float(amount_per_position) / current_price

                            # Place a buy order
                            buy_url = f"{BASE_URL}/v2/orders"
                            buy_payload = {
                                "side": "buy",
                                "type": "market",
                                "time_in_force": "day",
                                "symbol": symbol,
                                "qty": str(round(qty_to_buy, 2))  # Round quantity to 2 decimal places
                            }

                            buy_response = requests.post(buy_url, json=buy_payload, headers=headers)

                            if buy_response.status_code == 200:
                                logging.info(f"Successfully placed buy order for {symbol}. Quantity: {qty_to_buy}")
                            else:
                                logging.error(f"Failed to place buy order for {symbol}: {buy_response.text}")
                        except Exception as e:
                            logging.error(f"Failed to retrieve current price for {symbol}: {e}")
                else:
                    logging.info("No open positions found.")
            else:
                logging.error(f"Failed to retrieve open positions: {response_positions.text}")
        else:
            logging.info("No consecutive filled sells with the same symbol found.")
    else:
        logging.error(f"Failed to retrieve account activities: {response_activities.text}")


@app.route('/webhook', methods=['POST'])
def webhook():
    global is_trading
    try:
        json_data = request.get_json()
        logging.info(f"Received raw webhook data: {json_data}")
        if not json_data or 'message' not in json_data or 'symbol' not in json_data:
            return jsonify({'status': 'error', 'message': 'Invalid JSON data format'}), 400

        logging.info(f"Parsed JSON data: {json_data}")
        symbol = json_data['symbol']
        message = json_data['message']

        if message == 'on':
            logging.info(f"Received 'on' message for symbol: {symbol}")

            if not is_trading:
                # If trading is turned off, check for an open position and sell if one exists
                if has_open_position(symbol):
                    logging.info(f"Trading is turned off. Selling open position for {symbol}.")
                    execute_sell(symbol)
                    return jsonify({'status': 'success', 'message': f"Sold {symbol} as trading is turned off."})

            elif len(TRADE_SYMBOLS) < 2:
                if symbol not in TRADE_SYMBOLS:
                    TRADE_SYMBOLS.add(symbol)
                    logging.info(f"Added {symbol} to actively traded symbols.")

                    # Execute a buy for the specified symbol
                    if is_trading and symbol in TRADE_SYMBOLS:
                        current_price = get_live_price_with_fallback(format_symbol(symbol))
                        if current_price is not None:
                            logging.info(f"Current Price for {symbol}: {current_price}")
                            execute_trade(symbol, 'buy')
                            return jsonify({'status': 'success', 'message': f"Bought {symbol}."})
                        else:
                            return jsonify(
                                {'status': 'error', 'message': f"Unable to retrieve current price for {symbol}."}), 500
                else:
                    return jsonify({'status': 'success', 'message': f"{symbol} is already actively traded."})

            else:
                return jsonify(
                    {'status': 'error', 'message': 'Maximum number of actively traded symbols reached.'}), 400

        elif message == 'off':
            logging.info(f"Received 'off' message for symbol: {symbol}")

            if symbol in TRADE_SYMBOLS:
                execute_sell(symbol)
                TRADE_SYMBOLS.remove(symbol)
                logging.info(f"Trading is turned off for {symbol}. Sold all positions.")
                return jsonify(
                    {'status': 'success', 'message': f"Trading is turned off for {symbol}. Sold all positions."})
            else:
                logging.info(f"{symbol} is not actively traded. No action taken for turning off trading.")
                return jsonify({'status': 'success',
                                'message': f"{symbol} is not actively traded. No action taken for turning off trading."})

        else:
            return jsonify({'status': 'error', 'message': 'Invalid message type.'}), 400

    except json.JSONDecodeError:
        logging.error("Error decoding JSON data.")
        return jsonify({'status': 'error', 'message': 'Invalid JSON data'}), 400


def has_open_position(symbol):
    # Get all open positions
    positions = trading_client.list_positions()

    # Check if there is an open position for the given symbol
    for position in positions:
        if position.symbol == format_symbol(symbol):
            return True

    return False


def execute_sell(symbol):
    try:
        # Introduce a delay before retrieving positions information
        time.sleep(2)  # Wait for 3 seconds

        # Get position information using the Alpaca API
        url_positions = f"{BASE_URL}/v2/positions"
        headers_positions = {
            "accept": "application/json",
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
        }

        response_positions = requests.get(url_positions, headers=headers_positions)

        if response_positions.status_code != 200:
            logging.error(f"Error retrieving positions. HTTP Status Code: {response_positions.status_code}")
            logging.info(f"Response Content: {response_positions.text}")
            return 0  # Return 0 if there was an error

        # Parse the response content to obtain position_data
        position_data = response_positions.json()
        logging.info(f"Retrieved positions: {position_data}")

        # Find the position for the specified symbol
        position_to_sell = None
        for pos in position_data:
            if pos["symbol"] == format_symbol(symbol):
                position_to_sell = pos
                break

        if not position_to_sell:
            logging.info(f"No position found for {symbol}.")
            return 0  # Return 0 if no position found

        # Calculate the amount to sell
        qty_to_sell = float(position_to_sell["qty"]) * 0.99
        current_price = float(position_to_sell["current_price"])  # Get current price
        amount_sold = qty_to_sell * current_price  # Calculate total amount from sale

        # Execute sell order
        trading_client.submit_order(
            symbol=format_symbol(symbol),
            qty=round(qty_to_sell, 3),  # Round quantity to 2 decimal places
            side='sell',
            type='market',
            time_in_force='day'
        )

        logging.info(f"Sold {qty_to_sell} of {symbol}. Amount obtained: ${amount_sold:.2f}")
        return amount_sold  # Return the amount obtained from the sale

    except Exception as e:
        logging.error(f"Error during sell execution: {e}")
        return 0  # Return 0 in case of an error


if __name__ == '__main__':
    # Optionally, process last two filled sells at startup or on a schedule
    process_last_two_filled_sells()
    app.run(port=5001, debug=True)