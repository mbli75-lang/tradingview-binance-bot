from flask import Flask, request, jsonify
import os
import json
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
import time
import re

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Binance API credentials from environment variables
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_SECRET_KEY = os.getenv('BINANCE_SECRET_KEY')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'my_secret_123')

# Trading settings
RISK_PERCENTAGE = float(os.getenv('RISK_PERCENTAGE', '5.0'))  # % av saldo per trade
MIN_USDT_BALANCE = float(os.getenv('MIN_USDT_BALANCE', '10.0'))  # Minsta balans att behålla

# Initialize Binance client
if BINANCE_API_KEY and BINANCE_SECRET_KEY:
    binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY, testnet=False)
else:
    binance_client = None
    logger.warning("Binance API keys not configured!")

@app.route('/')
def home():
    return f"""
    <h1>🚀 TradingView to Binance Bot</h1>
    <p>✅ Bot is running successfully!</p>
    <p>📍 Webhook endpoint: <code>/webhook</code></p>
    <p>💰 Risk per trade: <strong>{RISK_PERCENTAGE}%</strong> of USDT balance</p>
    <p>🔧 Environment variables:</p>
    <ul>
        <li>BINANCE_API_KEY: {'✅ Set' if BINANCE_API_KEY else '❌ Missing'}</li>
        <li>BINANCE_SECRET_KEY: {'✅ Set' if BINANCE_SECRET_KEY else '❌ Missing'}</li>
        <li>WEBHOOK_SECRET: {'✅ Set' if WEBHOOK_SECRET else '❌ Missing'}</li>
        <li>RISK_PERCENTAGE: {RISK_PERCENTAGE}%</li>
    </ul>
    """

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # Try to get JSON data first
        data = None
        try:
            data = request.get_json()
        except:
            pass
        
        # If no JSON, try to parse text from TradingView
        if not data:
            text_data = request.get_data(as_text=True)
            logger.info(f"Received text data: {text_data}")
            data = parse_tradingview_text(text_data)
        
        if not data:
            return jsonify({'error': 'No valid data received'}), 400
        
        logger.info(f"Parsed webhook data: {data}")
        
        # Extract trading signal data
        action = data.get('action') or data.get('side', '').lower()  # 'buy' or 'sell'
        symbol = data.get('symbol', 'BTCUSDT')
        
        # Ignore quantity from TradingView - we calculate based on balance
        # quantity = data.get('quantity') or data.get('amount', 0.001)  
        
        if not action:
            return jsonify({'error': 'No action specified'}), 400
        
        # Execute trade if Binance client is configured
        if binance_client:
            result = execute_trade_with_percentage(action, symbol)
            return jsonify(result)
        else:
            logger.info(f"Would execute: {action} {symbol} ({RISK_PERCENTAGE}% of balance)")
            return jsonify({
                'status': 'success',
                'message': f'Signal received: {action} {symbol}',
                'note': 'Binance API not configured - simulation mode'
            })
            
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({'error': str(e)}), 500

def parse_tradingview_text(text):
    """Parse TradingView text alerts like 'BUY BTCUSDT QTY=0.0083'"""
    try:
        # Remove extra whitespace
        text = text.strip()
        
        # Pattern 1: "BUY BTCUSDT QTY=0.0083"
        pattern1 = r'(BUY|SELL)\s+(\w+)\s+QTY=([0-9.]+)'
        match1 = re.match(pattern1, text, re.IGNORECASE)
        
        if match1:
            action = match1.group(1).lower()
            symbol = match1.group(2).upper()
            # Ignore the quantity - we'll calculate it based on balance
            return {
                'action': action,
                'symbol': symbol,
                'source': 'tradingview_text'
            }
        
        # Pattern 2: "CLOSE LONG BTCUSDT" or "CLOSE SHORT BTCUSDT"
        pattern2 = r'CLOSE\s+(LONG|SHORT)\s+(\w+)'
        match2 = re.match(pattern2, text, re.IGNORECASE)
        
        if match2:
            direction = match2.group(1).lower()
            symbol = match2.group(2).upper()
            # Convert to sell action
            return {
                'action': 'sell' if direction == 'long' else 'buy',  # Close long = sell, close short = buy
                'symbol': symbol,
                'source': 'tradingview_close'
            }
        
        logger.warning(f"Could not parse TradingView text: {text}")
        return None
        
    except Exception as e:
        logger.error(f"Error parsing TradingView text: {e}")
        return None

def execute_trade_with_percentage(action, symbol):
    """Execute buy/sell order using percentage of USDT balance"""
    try:
        # Get current USDT balance
        usdt_balance = binance_client.get_asset_balance(asset='USDT')
        available_usdt = float(usdt_balance['free'])
        
        logger.info(f"Available USDT balance: {available_usdt}")
        
        if available_usdt < MIN_USDT_BALANCE:
            return {'error': f'Insufficient USDT balance. Available: {available_usdt}, Minimum: {MIN_USDT_BALANCE}'}
        
        # Calculate trade amount (percentage of available balance)
        usdt_to_trade = (available_usdt - MIN_USDT_BALANCE) * (RISK_PERCENTAGE / 100)
        
        if usdt_to_trade < 10:  # Binance minimum is usually around $10
            return {'error': f'Trade amount too small: ${usdt_to_trade:.2f}. Need at least $10.'}
        
        # Get current price
        ticker = binance_client.get_symbol_ticker(symbol=symbol.upper())
        current_price = float(ticker['price'])
        
        # Calculate quantity to buy/sell
        if action.lower() == 'buy':
            quantity = usdt_to_trade / current_price
            
            # Adjust quantity to match Binance's precision requirements
            symbol_info = binance_client.get_symbol_info(symbol.upper())
            step_size = None
            for f in symbol_info['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    step_size = float(f['stepSize'])
                    break
            
            if step_size:
                precision = len(str(step_size).split('.')[-1]) if '.' in str(step_size) else 0
                quantity = round(quantity, precision)
            else:
                quantity = round(quantity, 6)  # Default precision
            
            # Market buy order
            order = binance_client.order_market_buy(
                symbol=symbol.upper(),
                quantity=quantity
            )
            logger.info(f"BUY order executed: {order}")
            
        elif action.lower() == 'sell':
            # For sell orders, we need to check how much of the asset we own
            asset = symbol.replace('USDT', '')  # BTCUSDT -> BTC
            asset_balance = binance_client.get_asset_balance(asset=asset)
            available_asset = float(asset_balance['free'])
            
            if available_asset == 0:
                return {'error': f'No {asset} balance to sell'}
            
            # Sell all available amount or calculate percentage
            quantity = available_asset
            
            # Market sell order
            order = binance_client.order_market_sell(
                symbol=symbol.upper(),
                quantity=quantity
            )
            logger.info(f"SELL order executed: {order}")
            
        else:
            return {'error': f'Invalid action: {action}'}
        
        return {
            'status': 'success',
            'action': action,
            'symbol': symbol,
            'quantity': quantity,
            'usdt_amount': usdt_to_trade if action.lower() == 'buy' else quantity * current_price,
            'price': current_price,
            'order_id': order.get('orderId'),
            'message': f'{action.upper()} order executed successfully'
        }
        
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e}")
        return {'error': f'Binance API error: {str(e)}'}
    except Exception as e:
        logger.error(f"Trade execution error: {e}")
        return {'error': f'Trade execution error: {str(e)}'}

@app.route('/balance')
def get_balance():
    """Get account balance from Binance"""
    if not binance_client:
        return jsonify({'error': 'Binance API not configured'})
    
    try:
        account = binance_client.get_account()
        balances = []
        
        for balance in account['balances']:
            if float(balance['free']) > 0 or float(balance['locked']) > 0:
                balances.append({
                    'asset': balance['asset'],
                    'free': balance['free'],
                    'locked': balance['locked']
                })
        
        return jsonify({'balances': balances})
        
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/test', methods=['GET', 'POST'])
def test_webhook():
    """Test endpoint"""
    if request.method == 'GET':
        return """
        <h2>Test Webhook</h2>
        <p>Test formats:</p>
        <ul>
            <li><code>BUY BTCUSDT QTY=0.001</code></li>
            <li><code>SELL BTCUSDT QTY=0.001</code></li>
            <li><code>CLOSE LONG BTCUSDT</code></li>
        </ul>
        <p>Or send JSON: <code>{"action": "buy", "symbol": "BTCUSDT"}</code></p>
        """
    
    # Simulate webhook call for testing
    test_data = {
        'action': 'buy',
        'symbol': 'BTCUSDT',
        'source': 'test'
    }
    
    if binance_client:
        result = execute_trade_with_percentage('buy', 'BTCUSDT')
        return jsonify(result)
    else:
        return jsonify({
            'status': 'test_success',
            'message': f'Would execute: BUY BTCUSDT ({RISK_PERCENTAGE}% of balance)',
            'note': 'Binance API not configured - test mode'
        })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
