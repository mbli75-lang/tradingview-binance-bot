from flask import Flask, request, jsonify
from binance.client import Client
import os

app = Flask(__name__)

# Läs API-nycklar från Render-miljövariablerna
api_key = os.getenv("API_Key")        # OBS! matchar KEY-namnen du använt
api_secret = os.getenv("Secret_API")

client = Client(api_key, api_secret)

@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json()

    print("Webhook received:", data)

    symbol = data.get("symbol", "BTCUSDT")
    side = data.get("side", "BUY").upper()
    amount = float(data.get("amount", 0.001))

    try:
        if side == "BUY":
            order = client.order_market_buy(symbol=symbol, quantity=amount)
        elif side == "SELL":
            order = client.order_market_sell(symbol=symbol, quantity=amount)
        else:
            return jsonify({"error": "Invalid side"}), 400

        return jsonify({"status": "success", "order": order})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
# add webhook + binance order logic
