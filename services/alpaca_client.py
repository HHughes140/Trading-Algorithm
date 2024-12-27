
import logging
from alpaca_trade_api.rest import REST
from config import ALPACA_API_KEY, ALPACA_SECRET_KEY, BASE_URL
from services.price_fetcher import get_live_price_with_fallback

# Alpaca trading client
trading_client = REST(ALPACA_API_KEY, ALPACA_SECRET_KEY, base_url=BASE_URL)

# Initialize logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# State variables
is_trading = True
TRADE_SYMBOLS = set()


def execute_trade(symbol, action):
    """Execute a trade for the given symbol and action."""
    global TRADE_SYMBOLS

    if not is_trading:
        logging.info("Trading is currently paused.")
        return

    try:
        # Get account information
        account_info = trading_client.get_account()
        usd_balance = float(account_info.cash)

        print(f"USD Balance: ${usd_balance:.2f}")
        logging.debug(f"Account balance: ${usd_balance:.2f}")

        # Get current price for the symbol
        current_price = get_live_price_with_fallback(symbol)
        if current_price is None or current_price <= 0:
            logging.error(f"Invalid current price for {symbol}: {current_price}")
            return

        # Get current positions
        positions = get_open_positions()

        # Calculate the market value of all positions
        total_market_value = 0
        for position in positions:
            pos_price = get_live_price_with_fallback(position['symbol'])
            if pos_price is None or pos_price <= 0:
                logging.error(f"Invalid price for {position['symbol']}: {pos_price}")
                continue
            total_market_value += float(position['market_value'])

        # Calculate target allocation based on total market value
        total_positions = len(positions) + 1  # Include the new position
        target_allocation = (total_market_value + usd_balance) / total_positions  # Equal allocation for all positions
        print(f"Target allocation per position: ${target_allocation:.2f}")

        # Sell excess for each existing position first
        total_freed_cash = 0
        for position in positions:
            # Find total portfolio value
            pos_price = get_live_price_with_fallback(position['symbol'])
            if pos_price is None or pos_price <= 0:
                logging.error(f"Invalid price for {position['symbol']}: {pos_price}")
                continue

            # Calculate the current value of the position
            position_value = float(position['market_value'])
            logging.debug(f"Current position value for {position['symbol']}: {position_value:.2f}")

            # If the position value exceeds the target allocation, sell the excess
            if position_value > target_allocation:
                excess_value = position_value - target_allocation
                excess_qty = excess_value / pos_price

                # Sell excess shares
                sell_order = trading_client.submit_order(
                    symbol=position['symbol'],
                    qty=excess_qty,
                    side='sell',
                    type='market',
                    time_in_force='day'
                )
                logging.info(f"Sold {excess_qty:.2f} shares of {position['symbol']} to free up ${excess_value:.2f}")
                total_freed_cash += excess_value

        # After selling excess positions, use the freed cash or balance to buy the new symbol
        total_available_cash = total_freed_cash + usd_balance  # Combine freed cash and cash balance
        if total_available_cash > 0:
            adjusted_cash = total_available_cash / 1.0105  # Apply 1.05% buffer
            qty_to_buy = adjusted_cash / current_price
            qty_to_buy = max(qty_to_buy, 0)  # Ensure no negative or zero quantities

            if action == 'buy':
                # Execute buy order for the new symbol
                buy_order = trading_client.submit_order(
                    symbol=symbol,
                    qty=qty_to_buy,
                    side='buy',
                    type='market',
                    time_in_force='day'
                )
                logging.info(f"Bought {qty_to_buy:.2f} shares of {symbol} for ${adjusted_cash:.2f} (adjusted for buffer).")

        # Rebalance portfolio
        logging.info("Portfolio rebalanced successfully.")

    except Exception as e:
        logging.error(f"Error executing trade for {symbol}: {e}")




def execute_sell(symbol):
    """Sell one position completely and rebalance remaining positions"""
    global TRADE_SYMBOLS

    if not is_trading:
        logging.info("Trading is currently paused.")
        return

    try:
        # Get account information
        account_info = trading_client.get_account()
        usd_balance = float(account_info.cash)

        # Get current prices for all positions
        positions = get_open_positions()
        current_prices = {position['symbol']: get_live_price_with_fallback(position['symbol']) for position in
                          positions}

        # Calculate the new allocation for each remaining position
        total_positions = len(positions)
        new_allocation = usd_balance / total_positions  # allocation for each position

        # Identify the position to sell
        position_to_sell = positions[0]  # Selling the first position
        sell_price = current_prices[position_to_sell['symbol']]
        sell_quantity = position_to_sell['quantity']  # Quantity to sell

        # Sell the identified position
        place_order(position_to_sell['symbol'], sell_quantity, 'sell')

        # Calculate how much to buy for each of the remaining positions
        total_proceeds = sell_price * sell_quantity
        remaining_positions = [pos for pos in positions if pos['symbol'] != position_to_sell['symbol']]
        remaining_count = len(remaining_positions)

        # Allocate the proceeds equally across the remaining positions
        amount_per_position = total_proceeds / remaining_count
        for position in remaining_positions:
            current_price = current_prices[position['symbol']]
            quantity_to_buy = max(amount_per_position / current_price, 0)  # Avoid negative or zero quantities

            # Buy the necessary amount of each remaining position
            place_order(position['symbol'], quantity_to_buy, 'buy')

        # Log portfolio status
        logging.info(f"Rebalanced portfolio. Each remaining position now holds approximately ${new_allocation:.2f}.")

    except Exception as e:
        logging.error(f"Error executing rebalancing after sell: {e}")


def place_order(symbol, quantity, action):
    """Helper function to place an order."""
    if quantity <= 0:
        logging.error(f"Invalid quantity for {action} order on {symbol}: {quantity}")
        return False  # Return False if the quantity is invalid

    try:
        order_data = {
            'symbol': symbol,
            'qty': quantity,
            'side': action,
            'type': 'market',
            'time_in_force': 'day',
        }
        order = trading_client.submit_order(**order_data)
        if order.status == 'accepted':  # Assuming 'accepted' is the status for a successful order
            logging.info(f"{action.capitalize()} {quantity} of {symbol}.")
            return True
        else:
            logging.error(f"Failed to place order for {symbol}. Status: {order.status}, Response: {order}")
            return False
    except Exception as e:
        logging.error(f"Error placing {action} order for {symbol}: {e}")
        return False


def get_open_positions():
    """Fetch and return all open positions in the portfolio."""
    try:
        positions = trading_client.list_positions()
        return [
            {
                "symbol": pos.symbol,
                "quantity": float(pos.qty),  # Use float for fractional shares
                "market_value": float(pos.market_value)
            }
            for pos in positions
        ]
    except Exception as e:
        logging.error(f"Error fetching open positions: {e}")
        return []


def get_position_count():
    """Return the count of open positions."""
    positions = get_open_positions()
    return len(positions)
