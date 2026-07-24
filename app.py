from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import hashlib
import uuid
import json
from time import time
from datetime import datetime
import qrcode
import io
import base64

app = Flask(__name__)
app.secret_key = "crypto_secret_key"


# ---------------- BLOCKCHAIN ---------------- #
class Blockchain:
    def __init__(self):
        self.chain = []
        self.pending_transactions = []
        self.create_block(proof=1, previous_hash='0')

    def create_block(self, proof, previous_hash):
        block = {
            'index': len(self.chain) + 1,
            'timestamp': time(),
            'transactions': self.pending_transactions,
            'proof': proof,
            'previous_hash': previous_hash
        }
        self.pending_transactions = []
        self.chain.append(block)
        return block

    def get_previous_block(self):
        return self.chain[-1]

    def proof_of_work(self, previous_proof):
        new_proof = 1
        while True:
            hash_operation = hashlib.sha256(
                str(new_proof**2 - previous_proof**2).encode()
            ).hexdigest()

            if hash_operation[:4] == '0000':
                return new_proof
            new_proof += 1

    def hash(self, block):
        encoded_block = json.dumps(block, sort_keys=True).encode()
        return hashlib.sha256(encoded_block).hexdigest()

    def add_transaction(self, sender, receiver, amount):
        self.pending_transactions.append({
            'sender': sender,
            'receiver': receiver,
            'amount': amount
        })

    def is_chain_valid(self):
        previous_block = self.chain[0]
        block_index = 1

        while block_index < len(self.chain):
            block = self.chain[block_index]

            if block['previous_hash'] != self.hash(previous_block):
                return False

            previous_proof = previous_block['proof']
            proof = block['proof']

            hash_operation = hashlib.sha256(
                str(proof**2 - previous_proof**2).encode()
            ).hexdigest()

            if hash_operation[:4] != '0000':
                return False

            previous_block = block
            block_index += 1

        return True


blockchain = Blockchain()


# ---------------- DATABASE ---------------- #

def get_user_db():
    conn = sqlite3.connect("users.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_wallet_db():
    conn = sqlite3.connect("wallet.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    # USERS DB
    conn1 = get_user_db()
    cursor1 = conn1.cursor()

    cursor1.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        wallet_address TEXT UNIQUE NOT NULL,
        balance REAL DEFAULT 100.0
    )
    """)

    conn1.commit()
    conn1.close()

    # WALLET DB
    conn2 = get_wallet_db()
    cursor2 = conn2.cursor()

    cursor2.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT NOT NULL,
        receiver TEXT NOT NULL,
        amount REAL NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn2.commit()
    conn2.close()


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


init_db()


# ---------------- ROUTES ---------------- #

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        wallet_address = str(uuid.uuid4()).replace("-", "")[:16]
        hashed_password = hash_password(password)

        conn = get_user_db()
        cursor = conn.cursor()

        try:
            cursor.execute("""
            INSERT INTO users (username, password, wallet_address, balance)
            VALUES (?, ?, ?, ?)
            """, (username, hashed_password, wallet_address, 100.0))
            conn.commit()
            flash("Registration successful!", "success")
            return redirect(url_for("login"))

        except sqlite3.IntegrityError:
            flash("Username already exists!", "danger")

        finally:
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = hash_password(request.form["password"])

        conn = get_user_db()
        cursor = conn.cursor()

        cursor.execute("""
        SELECT * FROM users WHERE username = ? AND password = ?
        """, (username, password))

        user = cursor.fetchone()
        conn.close()

        if user:
            session["username"] = user["username"]
            return redirect(url_for("dashboard"))
        else:
            flash("Invalid username or password", "danger")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return redirect(url_for("login"))

    # Get user
    conn = get_user_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM users WHERE username = ?",
        (session["username"],)
    )
    user = cursor.fetchone()
    conn.close()

    # Get transactions
    conn = get_wallet_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM transactions
        WHERE sender = ? OR receiver = ?
        ORDER BY id DESC
    """, (user["username"], user["username"]))
    transactions = cursor.fetchall()
    conn.close()

    # Get mining and validation results
    mine_result = session.get("mine_result")
    validation_result = session.get("validation_result")

    return render_template(
        "dashboard.html",
        user=user,
        transactions=transactions,
        chain=blockchain.chain,
        mine_result=mine_result,
        validation_result=validation_result
    )

    
@app.route("/send", methods=["GET", "POST"])
def send():
    if "username" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        receiver_wallet = request.form["receiver_wallet"].strip()
        amount = float(request.form["amount"])

        conn = get_user_db()
        cursor = conn.cursor()

        # Sender
        cursor.execute(
            "SELECT * FROM users WHERE username = ?",
            (session["username"],)
        )
        sender = cursor.fetchone()

        # Receiver (search by wallet address)
        cursor.execute(
            "SELECT * FROM users WHERE wallet_address = ?",
            (receiver_wallet,)
        )
        receiver = cursor.fetchone()

        if not receiver:
            flash("Receiver not found!", "danger")
            conn.close()
            return redirect(url_for("send"))

        if sender["balance"] < amount:
            flash("Insufficient balance!", "danger")
            conn.close()
            return redirect(url_for("send"))

        # Update balances
        cursor.execute(
            "UPDATE users SET balance = balance - ? WHERE username = ?",
            (amount, sender["username"])
        )

        cursor.execute(
            "UPDATE users SET balance = balance + ? WHERE username = ?",
            (amount, receiver["username"])
        )

        conn.commit()
        conn.close()

        # Store transaction
        conn2 = get_wallet_db()
        cursor2 = conn2.cursor()

        cursor2.execute("""
            INSERT INTO transactions (sender, receiver, amount)
            VALUES (?, ?, ?)
        """, (
            sender["username"],
            receiver["username"],
            amount
        ))

        conn2.commit()
        conn2.close()

        # Add transaction to blockchain
        blockchain.add_transaction(
            sender=sender["username"],
            receiver=receiver["username"],
            amount=amount
        )

        flash("Transaction successful!", "success")
        return redirect(url_for("dashboard"))

    return render_template("send.html")
@app.route("/receive")
def receive():
    if "username" not in session:
        return redirect(url_for("login"))

    conn = get_user_db()
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM users WHERE username=?",
        (session["username"],)
    )

    user = cursor.fetchone()
    conn.close()

    # Generate QR Code
    qr = qrcode.make(user["wallet_address"])

    buffer = io.BytesIO()
    qr.save(buffer, format="PNG")

    qr_code = base64.b64encode(buffer.getvalue()).decode()

    return render_template(
        "receive.html",
        user=user,
        qr_code=qr_code
    )

@app.route("/mine")
def mine():
    if "username" not in session:
        return redirect(url_for("login"))
    if not blockchain.pending_transactions:
        flash("No pending transactions to mine!", "warning")
        return redirect(url_for("dashboard"))

    previous_block = blockchain.get_previous_block()
    proof = blockchain.proof_of_work(previous_block["proof"])
    previous_hash = blockchain.hash(previous_block)

    # Reward miner
    blockchain.add_transaction(
        sender="NETWORK",
        receiver=session["username"],
        amount=10
    )

    # Create block
    block = blockchain.create_block(proof, previous_hash)

    # Calculate the current block hash
    current_hash = blockchain.hash(block)

    # Update user's balance
    conn = get_user_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET balance = balance + 10 WHERE username=?",
        (session["username"],)
    )
    conn.commit()
    conn.close()

    # Store mining result
    session["mine_result"] = {
    "index": block["index"],
    "proof": block["proof"],
    "previous_hash": block["previous_hash"],
    "timestamp": datetime.fromtimestamp(
        block["timestamp"]
    ).strftime("%d-%m-%Y %I:%M:%S %p"),
     "current_hash": current_hash,
   "transactions": block["transactions"],
    "reward": 10
}

    flash("Block mined successfully!", "success")
    return redirect(url_for("dashboard"))
@app.route("/validate")
def validate():

    valid = blockchain.is_chain_valid()

    session["validation_result"] = {
        "status": valid,
        "blocks": len(blockchain.chain),
        "last_hash": blockchain.hash(blockchain.get_previous_block())
    }

    if valid:
        flash("Blockchain is valid!", "success")
    else:
        flash("Blockchain is invalid!", "danger")

    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully!", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True, port=5001)