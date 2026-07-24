from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import hashlib
import uuid
import json
from time import time

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
        check_proof = False

        while not check_proof:
            hash_operation = hashlib.sha256(
                str(new_proof**2 - previous_proof**2).encode()
            ).hexdigest()

            if hash_operation[:4] == '0000':
                check_proof = True
            else:
                new_proof += 1

        return new_proof

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
def get_connection():
    conn = sqlite3.connect("wallet.db")
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        wallet_address TEXT UNIQUE NOT NULL,
        balance REAL DEFAULT 100.0
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sender TEXT NOT NULL,
        receiver TEXT NOT NULL,
        amount REAL NOT NULL,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """)

    conn.commit()
    conn.close()


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def get_wallet_by_username(username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT wallet_address FROM users WHERE username = ?", (username,))
    user = cursor.fetchone()
    conn.close()
    return user["wallet_address"] if user else None


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

        conn = get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
            INSERT INTO users (username, password, wallet_address, balance)
            VALUES (?, ?, ?, ?)
            """, (username, hashed_password, wallet_address, 100.0))
            conn.commit()
            flash("Registration successful. Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username already exists.", "danger")
        finally:
            conn.close()

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = hash_password(request.form["password"])

        conn = get_connection()
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
            flash("Invalid username or password.", "danger")

    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "username" not in session:
        return redirect(url_for("login"))

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT username, wallet_address, balance FROM users WHERE username = ?
    """, (session["username"],))
    user = cursor.fetchone()

    cursor.execute("""
    SELECT * FROM transactions
    WHERE sender = ? OR receiver = ?
    ORDER BY id DESC
    """, (user["wallet_address"], user["wallet_address"]))
    transactions = cursor.fetchall()

    conn.close()

    return render_template("dashboard.html", user=user, transactions=transactions, chain=blockchain.chain)


@app.route("/send", methods=["GET", "POST"])
def send():
    if "username" not in session:
        return redirect(url_for("login"))

    if request.method == "POST":
        receiver_wallet = request.form["receiver_wallet"]
        amount = float(request.form["amount"])

        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE username = ?", (session["username"],))
        sender = cursor.fetchone()

        cursor.execute("SELECT * FROM users WHERE wallet_address = ?", (receiver_wallet,))
        receiver = cursor.fetchone()

        if not receiver:
            flash("Receiver wallet not found.", "danger")
            conn.close()
            return redirect(url_for("send"))

        if sender["wallet_address"] == receiver_wallet:
            flash("You cannot send coins to your own wallet.", "danger")
            conn.close()
            return redirect(url_for("send"))

        if sender["balance"] < amount:
            flash("Insufficient balance.", "danger")
            conn.close()
            return redirect(url_for("send"))

        new_sender_balance = sender["balance"] - amount
        new_receiver_balance = receiver["balance"] + amount

        cursor.execute("UPDATE users SET balance = ? WHERE username = ?", (new_sender_balance, session["username"]))
        cursor.execute("UPDATE users SET balance = ? WHERE wallet_address = ?", (new_receiver_balance, receiver_wallet))

        cursor.execute("""
        INSERT INTO transactions (sender, receiver, amount)
        VALUES (?, ?, ?)
        """, (sender["wallet_address"], receiver_wallet, amount))

        conn.commit()
        conn.close()

        blockchain.add_transaction(sender["wallet_address"], receiver_wallet, amount)

        flash("Transaction successful.", "success")
        return redirect(url_for("dashboard"))

    return render_template("send.html")


@app.route("/mine")
def mine():
    previous_block = blockchain.get_previous_block()
    previous_proof = previous_block["proof"]
    proof = blockchain.proof_of_work(previous_proof)
    previous_hash = blockchain.hash(previous_block)
    blockchain.create_block(proof, previous_hash)
    flash("Block mined successfully.", "success")
    return redirect(url_for("dashboard"))


@app.route("/validate")
def validate():
    if blockchain.is_chain_valid():
        flash("Blockchain is valid.", "success")
    else:
        flash("Blockchain is invalid.", "danger")
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)