
from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

# ✅ PythonAnywhere 원본 서버 주소
PYTHONANYWHERE_BASE = "https://kimwooju.pythonanywhere.com"

# 🔁 전략 트리거 중계 (POST)
@app.route("/relay", methods=["POST"])
def relay():
    try:
        data = request.get_json()
        resp = requests.post(f"{PYTHONANYWHERE_BASE}/relay", json=data)
        return (resp.text, resp.status_code)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 🔍 상태 확인 (GET)
@app.route("/status", methods=["GET"])
def status():
    try:
        resp = requests.get(f"{PYTHONANYWHERE_BASE}/api/status")
        return (resp.text, resp.status_code)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# 🧾 실시간 주가 중계 Relay (PythonAnywhere로 전송)
@app.route("/price", methods=["GET"])
def price():
    ticker = request.args.get("ticker")
    try:
        resp = requests.get(f"{PYTHONANYWHERE_BASE}/price?ticker={ticker}")
        return (resp.text, resp.status_code)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
