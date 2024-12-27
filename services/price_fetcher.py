import yfinance as yf
import logging

def get_live_price_with_fallback(symbol):
    try:
        data = yf.Ticker(symbol).history(period='1d')
        if not data.empty:
            return data['Close'].iloc[-1]
        else:
            raise ValueError("No data from Yahoo Finance.")
    except Exception as e:
        logging.error(f"Error fetching price for {symbol}: {e}")
        return None
