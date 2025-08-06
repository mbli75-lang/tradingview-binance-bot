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

# Initialize Binance client with better error handling
if BINANCE_API_KEY and BINANCE_SECRET_KEY:
    try:
        # Strip whitespace from API keys
        clean_api_key = BINANCE_API_KEY.strip()
        clean_secret_key = BINANCE_SECRET_KEY.strip()
        
        # Log key info (first/last 4 chars only for security)
        logger.info(f"API Key starts with: {clean_api_key[:4]}...{clean_api_key[-4:]}")
        
        binance_client = Client(clean_api_key, clean_secret_key, testnet=False)
        
        # Test connection
        binance_client.ping()
        logger.info("✅ Binance client initialized and connected successfully!")
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Binance client: {e}")
        binance_client = None
else:
    binance_client = None
    logger.warning("⚠️ Binance API keys not configured!")

@app.route('/')
def home():
    # Test Binance connection status
    binance_status = "❌ Not connected"
    if binance_client:
        try:
            binance_client.ping()
            binance_status = "✅ Connected"
        except:
            binance_status = "❌ Connection failed"
    
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
        <li>Binance Connection: {binance_status}</li>
    </ul>
    <p>🧪 Test endpoints:</p>
    <ul>
        <li><a href="/test">/test</a> - Test webhook</li>
        <li><a href="/balance">/balance</a> - Check balance</li>
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
        
        # Check webhook secret if provided
        webhook_secret = data.get('secret')
        if webhook_secret and webhook_secret != WEBHOOK_SECRET:
            logger.warning("⚠️ Invalid webhook secret!")
            return jsonify({'error': 'Invalid secret'}), 401
        
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
        
        logger.info(f"💰 Available USDT balance: {available_usdt}")
        
        if available_usdt < MIN_USDT_BALANCE:
            return {'error': f'Insufficient USDT balance. Available: {available_usdt}, Minimum: {MIN_USDT_BALANCE}'}
        
        # Calculate trade amount (percentage of available balance)
        usdt_to_trade = (available_usdt - MIN_USDT_BALANCE) * (RISK_PERCENTAGE / 100)
        
        logger.info(f"💵 USDT to trade ({RISK_PERCENTAGE}%): ${usdt_to_trade:.2f}")
        
        if usdt_to_trade < 10:  # Binance minimum is usually around $10
            return {'error': f'Trade amount too small: ${usdt_to_trade:.2f}. Need at least $10.'}
        
        # Get current price
        ticker = binance_client.get_symbol_ticker(symbol=symbol.upper())
        current_price = float(ticker['price'])
        logger.info(f"📈 Current {symbol} price: ${current_price}")
        
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
                # Calculate precision based on step size
                precision = len(str(step_size).split('.')[-1].rstrip('0')) if '.' in str(step_size) else 0
                quantity = round(quantity, precision)
            else:
                quantity = round(quantity, 6)  # Default precision
            
            logger.info(f"🚀 Executing BUY: {quantity} {symbol} for ~${usdt_to_trade:.2f}")
            
            # Market buy order
            order = binance_client.order_market_buy(
                symbol=symbol.upper(),
                quantity=quantity
            )
            logger.info(f"✅ BUY order executed: {order}")
            
        elif action.lower() == 'sell':
            # For sell orders, we need to check how much of the asset we own
            asset = symbol.replace('USDT', '')  # BTCUSDT -> BTC
            asset_balance = binance_client.get_asset_balance(asset=asset)
            available_asset = float(asset_balance['free'])
            
            logger.info(f"💼 Available {asset} balance: {available_asset}")
            
            if available_asset == 0:
                return {'error': f'No {asset} balance to sell'}
            
            # Sell all available amount or calculate percentage
            quantity = available_asset
            
            logger.info(f"📉 Executing SELL: {quantity} {symbol} for ~${quantity * current_price:.2f}")
            
            # Market sell order
            order = binance_client.order_market_sell(
                symbol=symbol.upper(),
                quantity=quantity
            )
            logger.info(f"✅ SELL order executed: {order}")
            
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
            'message': f'✅ {action.upper()} order executed successfully!'
        }
        
    except BinanceAPIException as e:
        logger.error(f"❌ Binance API error: {e}")
        return {'error': f'Binance API error: {str(e)}'}
    except Exception as e:
        logger.error(f"❌ Trade execution error: {e}")
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
            free_balance = float(balance['free'])
            locked_balance = float(balance['locked'])
            if free_balance > 0 or locked_balance > 0:
                balances.append({
                    'asset': balance['asset'],
                    'free': balance['free'],
                    'locked': balance['locked'],
                    'total': free_balance + locked_balance
                })
        
        # Sort by total balance (highest first)
        balances.sort(key=lambda x: x['total'], reverse=True)
        
        return jsonify({
            'status': 'success',
            'balances': balances,
            'count': len(balances)
        })
        
    except Exception as e:
        logger.error(f"Balance error: {e}")
        return jsonify({'error': str(e)})

@app.route('/test', methods=['GET', 'POST'])
def test_webhook():
    """Test endpoint"""
    if request.method == 'GET':
        return """
        <h2>🧪 Test Webhook</h2>
        <p><strong>Supported formats:</strong></p>
        <ul>
            <li><code>BUY BTCUSDT QTY=0.001</code></li>
            <li><code>SELL BTCUSDT QTY=0.001</code></li>
            <li><code>CLOSE LONG BTCUSDT</code></li>
        </ul>
        <p><strong>Or send JSON:</strong></p>
        <code>{"action": "buy", "symbol": "BTCUSDT"}</code>
        
        <h3>Quick Test:</h3>
        <p>POST to this endpoint with text: <code>BUY BTCUSDT QTY=0.001</code></p>
        """
    
    # Handle POST request - simulate webhook
    try:
        # Try to get test data
        test_data = request.get_json() or {
            'action': 'buy',
            'symbol': 'BTCUSDT',
            'source': 'test'
        }
        
        logger.info(f"🧪 Test webhook data: {test_data}")
        
        if binance_client:
            # Don't actually execute trades in test mode - just simulate
            return jsonify({
                'status': 'test_success',
                'message': f'✅ Would execute: {test_data.get("action", "buy").upper()} {test_data.get("symbol", "BTCUSDT")}',
                'risk_percentage': f'{RISK_PERCENTAGE}%',
                'binance_connected': True,
                'note': '🧪 Test mode - no actual trades executed'
            })
        else:
            return jsonify({
                'status': 'test_success',
                'message': f'Would execute: {test_data.get("action", "buy").upper()} {test_data.get("symbol", "BTCUSDT")}',
                'risk_percentage': f'{RISK_PERCENTAGE}%',
                'binance_connected': False,
                'note': '⚠️ Binance API not configured - simulation mode'
            })
    except Exception as e:
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"🚀 Starting bot on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
