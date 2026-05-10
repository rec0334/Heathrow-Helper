from flask import Flask, render_template, request, jsonify
from bot import respond

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    msg = (request.json or {}).get("message", "").strip()
    return jsonify({"reply": respond(msg)})


if __name__ == "__main__":
    app.run(debug=True, port=5000)
