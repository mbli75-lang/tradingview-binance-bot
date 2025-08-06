from flask import Flask, request, jsonify
import os
import json
import logging
from binance.client import Client
from binance.exceptions import BinanceAPIException
import time

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Binance API credentials from environment variables
BINANCE_API_KEY = os.getenv('BINANCE_API_KEY')
BINANCE_SECRET_KEY = os.getenv('BINANCE_SECRET_KEY')
WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'your_secret_key')

# Initialize Binance client
if BINANCE_API_KEY and BINANCE_SECRET_KEY:
    binance_client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY, testnet=False)
else:
    binance_client = None
    logger.warning("Binance API keys not configured!")

@app.route('/')
def home():
    return """
    <h1>🚀 TradingView to Binance Bot</h1>
    <p>✅ Bot is running successfully!</p>
    <p>📍 Webhook endpoint: <code>/webhook</code></p>
    <p>🔧 Configure your environment variables:</p>
    <ul>
        <li>BINANCE_API_KEY</li>
        <li>BINANCE_SECRET_KEY</li>
        <li>WEBHOOK_SECRET</li>
    </ul>
    """

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # Get JSON data from TradingView
        data = request.get_json()
        
        if not data:
            return jsonify({'error': 'No JSON data received'}), 400
        
        logger.info(f"Received webhook data: {data}")
        
        # Check webhook secret for security
        webhook_secret = data.get('secret')
        if webhook_secret != WEBHOOK_SECRET:
            logger.warning("Invalid webhook secret!")
            return jsonify({'error': 'Invalid secret'}), 401
        
        # Extract trading signal data
        action = data.get('action')  # 'buy' or 'sell'
        symbol = data.get('symbol', 'BTCUSDT')  # Default to BTCUSDT
        quantity = data.get('quantity', 0.001)  # Default small quantity
        
        if not action:
            return jsonify({'error': 'No action specified'}), 400
        
        # Execute trade if Binance client is configured
        if binance_client:
            result = execute_trade(action, symbol, quantity)
            return jsonify(result)
        else:
            logger.info(f"Would execute: {action} {quantity} {symbol}")
            return jsonify({
                'status': 'success',
                'message': f'Signal received: {action} {quantity} {symbol}',
                'note': 'Binance API not configured - simulation mode'
            })
            
    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        return jsonify({'error': str(e)}), 500

def execute_trade(action, symbol, quantity):
    """Execute buy/sell order on Binance"""
    try:
        if action.lower() == 'buy':
            # Market buy order
            order = binance_client.order_market_buy(
                symbol=symbol.upper(),
                quantity=quantity
            )
            logger.info(f"BUY order executed: {order}")
            
        elif action.lower() == 'sell':
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
            'order_id': order.get('orderId'),
            'message': f'{action.upper()} order executed successfully'
        }
        
    except BinanceAPIException as e:
        logger.error(f"Binance API error: {e}")
        return {'error': f'Binance API error: {str(e)}'}
    except Exception as e:
        logger.error(f"Trade execution error: {e}")
        return {'error': f'Trade execution error: {str(e)}'}

@app.route('/test', methods=['POST'])
def test_webhook():
    """Test endpoint to simulate TradingView webhook"""
    test_data = {
        'action': 'buy',
        'symbol': 'BTCUSDT',
        'quantity': 0.001,
        'secret': WEBHOOK_SECRET
    }
    
    # Simulate webhook call
    with app.test_client() as client:
        response = client.post('/webhook', 
                             json=test_data,
                             headers={'Content-Type': 'application/json'})
        return response.get_json()

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
