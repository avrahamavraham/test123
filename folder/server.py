from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import json
import os
import random
import string
from datetime import datetime, timedelta
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pymongo import MongoClient
from waitress import serve
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'your-secret-key-here'  # Required for session management

# Email configuration
EMAIL_ADDRESS = 'your-email@gmail.com'  # Replace with your email
EMAIL_PASSWORD = 'your-app-password'  # Use app password for Gmail
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587

client = MongoClient('mongodb+srv://avrahamgen:eJXt7AKUDanPNPkl@cluster0.hobhy.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')
db = client['game_database']  # Create/use a database named 'game_database'
players_collection = db['players']  # Collection for player data
users_collection = db['users']    # Collection for user data
verification_collection = db['verification']  # Collection for verification codes

# Helper function to read player data
def read_player_data():
    if os.path.exists(PLAYER_DATA_FILE):
        with open(PLAYER_DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

# Helper function to write player data
def write_player_data(data, player_name):
    player = {'name': player_name}
    data['player'] = player
    with open(PLAYER_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def ensure_admin_exists():
    # Check if admin exists
    admin_user = users_collection.find_one({'username': 'admin'})
    if admin_user:
        # Update admin password if user exists
        users_collection.update_one(
            {'username': 'admin'},
            {'$set': {'password': generate_password_hash('123')}}
        )
    else:
        # Create new admin user
        users_collection.insert_one({
            'username': 'admin',
            'password': generate_password_hash('123'),
            'email': 'admin@example.com',
            'verified': True
        })

# Call this when the server starts
ensure_admin_exists()

# Function to generate a random verification code
def generate_verification_code(length=6):
    return ''.join(random.choices(string.digits, k=length))

# Function to send verification email
def send_verification_email(email, username, verification_code):
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_ADDRESS
        msg['To'] = email
        msg['Subject'] = 'אימות חשבון - עולם המשנה'
        
        body = f'''שלום {username},

תודה שנרשמת לעולם המשנה. קוד האימות שלך הוא:

{verification_code}

הקוד תקף למשך 24 שעות.

בברכה,
צוות עולם המשנה
'''
        msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

@app.route('/api/players', methods=['GET'])
def get_players():
    players = list(players_collection.find({}, {'_id': 0}))  # Exclude MongoDB _id field
    return jsonify(players)

@app.route('/api/players', methods=['POST'])
def save_players():
    data = request.get_json()
    # Remove existing players and insert new data
    players_collection.delete_many({})
    if data:  # Check if data is not empty
        players_collection.insert_many(data)
    return jsonify({"status": "success"})

@app.route('/api/player/<name>', methods=['GET'])
def get_player(name):
    player = players_collection.find_one({'name': name}, {'_id': 0})
    if player:
        return jsonify(player)
    return jsonify({}), 404

@app.route('/api/player/<name>', methods=['POST'])
def update_player(name):
    data = request.get_json()
    data['name'] = name  # Ensure the name matches the URL parameter
    
    # Update or insert the player data
    players_collection.update_one(
        {'name': name},
        {'$set': data},
        upsert=True
    )
    return jsonify({"status": "success"})

def create_new_player(username):
    player_data = {
        'name': username,
        # Add any default player properties here
        'experience': 0,
        'level': 1,
        # Add other default player properties as needed
    }
    players_collection.insert_one(player_data)
    return player_data

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    password = data.get('password')
    
    if not username or not email or not password:
        return jsonify({'message': 'חסרים פרטים לצורך הרשמה'}), 400

    if username.lower() == 'admin':
        return jsonify({'message': 'שם משתמש זה שמור למערכת'}), 400

    # Check if username already exists
    if users_collection.find_one({'username': username}):
        return jsonify({'message': 'שם המשתמש כבר קיים במערכת'}), 400
        
    # Check if email already exists
    if users_collection.find_one({'email': email}):
        return jsonify({'message': 'כתובת הדואר האלקטרוני כבר רשומה במערכת'}), 400

    # Generate verification code
    verification_code = generate_verification_code()
    expiration_time = datetime.now() + timedelta(hours=24)
    
    # Store verification code
    verification_collection.insert_one({
        'username': username,
        'email': email,
        'code': verification_code,
        'expires': expiration_time,
        'password': generate_password_hash(password)
    })
    
    # Send verification email
    if send_verification_email(email, username, verification_code):
        return jsonify({'message': 'קוד אימות נשלח לדואר האלקטרוני שלך'}), 200
    else:
        verification_collection.delete_one({'username': username})
        return jsonify({'message': 'שגיאה בשליחת קוד האימות'}), 500

@app.route('/verify-email', methods=['POST'])
def verify_email():
    data = request.get_json()
    username = data.get('username')
    verification_code = data.get('verificationCode')
    
    if not username or not verification_code:
        return jsonify({'message': 'חסרים פרטים לאימות'}), 400
    
    # Find verification record
    verification = verification_collection.find_one({
        'username': username,
        'code': verification_code,
        'expires': {'$gt': datetime.now()}
    })
    
    if not verification:
        return jsonify({'message': 'קוד אימות שגוי או שפג תוקפו'}), 400
    
    # Create verified user
    users_collection.insert_one({
        'username': verification['username'],
        'email': verification['email'],
        'password': verification['password'],
        'verified': True,
        'created_at': datetime.now()
    })
    
    # Create player profile
    create_new_player(username)
    
    # Remove verification record
    verification_collection.delete_one({'_id': verification['_id']})
    
    return jsonify({'message': 'האימות בוצע בהצלחה'}), 200

@app.route('/resend-verification', methods=['POST'])
def resend_verification():
    data = request.get_json()
    username = data.get('username')
    email = data.get('email')
    
    if not username or not email:
        return jsonify({'message': 'חסרים פרטים לשליחה חוזרת'}), 400
    
    # Find existing verification
    verification = verification_collection.find_one({
        'username': username,
        'email': email
    })
    
    if not verification:
        return jsonify({'message': 'לא נמצא רישום להשלמה'}), 404
    
    # Generate new verification code
    verification_code = generate_verification_code()
    expiration_time = datetime.now() + timedelta(hours=24)
    
    # Update verification record
    verification_collection.update_one(
        {'_id': verification['_id']},
        {
            '$set': {
                'code': verification_code,
                'expires': expiration_time
            }
        }
    )
    
    # Send new verification email
    if send_verification_email(email, username, verification_code):
        return jsonify({'message': 'קוד אימות חדש נשלח בהצלחה'}), 200
    else:
        return jsonify({'message': 'שגיאה בשליחת קוד האימות'}), 500

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    if not username or not password:
        return jsonify({'message': 'חסרים שם משתמש או סיסמה'}), 400

    user = users_collection.find_one({'username': username})
    if not user:
        return jsonify({'message': 'שם משתמש או סיסמה שגויים'}), 401
    
    if not user.get('verified', False) and username != 'admin':
        return jsonify({'message': 'חשבון זה לא אומת. בדוק את תיבת הדואר האלקטרוני שלך'}), 401
    
    if check_password_hash(user['password'], password):
        session['username'] = username
        return jsonify({'message': 'התחברת בהצלחה'}), 200
    
    return jsonify({'message': 'שם משתמש או סיסמה שגויים'}), 401

@app.route('/register-page')
def register_page():
    return render_template('register.html')

@app.route('/')
@app.route('/statt new')
def statt_new():
    return render_template("statt new.html")

@app.route('/world_map')
def world_map():
    is_admin = session.get('username') == 'admin'
    return render_template('world_map.html', is_admin=is_admin)

@app.route('/')
@app.route('/biet_m')
def beit_m():
    return render_template("beit_m.html")

@app.route('/')
@app.route('/cards')
def cards():
    return render_template("cards.html")

@app.route('/')
@app.route('/game')
def game():
    return render_template("game.html")

@app.route('/')
@app.route('/hnot')
def hnot():
    return render_template("hnot.html")

@app.route('/')
@app.route('/index')
def index():
    is_admin = session.get('username') == 'admin'
    return render_template('index.html', is_admin=is_admin)

@app.route('/')
@app.route('/isof')
def isof():
    return render_template("isof.html")

@app.route('/')
@app.route('/map')
def map():
    return render_template("map.html")

@app.route('/personal-area')
def personal_area():
    return render_template("personal-area.html")

@app.route('/')
@app.route('/shimosh')
def shimosh():
    return render_template("shimosh.html")

@app.route('/')
@app.route('/timeh')
def timeh():
    return render_template("timeh.html")

@app.route('/')
@app.route('/דוקרבבןשחקנים')
def דוקרבבןשחקנים():
    return render_template("דו קרב בין שחקנים.html")

@app.route('/')
@app.route('/דו קרב מחשב')
def דוקרבמחשב():
    return render_template("דו קרב מחשב.html")

if __name__ == "__main__":
    serve(app, host="0.0.0.0", port=8000, threads=8)