# Comments

from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_jwt_extended import JWTManager, create_access_token, jwt_required
import stripe
from printer_connector import PrinterCommunicator  # Custom C++ integration module

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql://user:pass@localhost/printer_db'
app.config['JWT_SECRET_KEY'] = 'super-secret-key'
app.config['STRIPE_SECRET_KEY'] = 'sk_test_...'

db = SQLAlchemy(app)
jwt = JWTManager(app)
stripe.api_key = app.config['STRIPE_SECRET_KEY']

# Database Models
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True)
    password = db.Column(db.String(120))
    account_type = db.Column(db.String(20), default='free')
    balance = db.Column(db.Float, default=0.0)

class Printer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    location = db.Column(db.String(120))
    status = db.Column(db.String(20))
    ip_address = db.Column(db.String(15))

class PrintJob(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    printer_id = db.Column(db.Integer, db.ForeignKey('printer.id'))
    file_path = db.Column(db.String(255))
    status = db.Column(db.String(20))
    pages = db.Column(db.Integer)
    cost = db.Column(db.Float)

# Authentication Endpoints
@app.route('/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    new_user = User(
        username=data['username'],
        password=data['password']  # In practice: hash password
    )
    db.session.add(new_user)
    db.session.commit()
    return jsonify({'message': 'User created'}), 201

@app.route('/auth/login', methods=['POST'])
def login():
    username = request.json.get('username')
    password = request.json.get('password')
    user = User.query.filter_by(username=username).first()
    if user and user.password == password:
        access_token = create_access_token(identity=username)
        return jsonify(access_token=access_token)
    return jsonify({"msg": "Bad credentials"}), 401

# Printer Management Endpoints
@app.route('/printers', methods=['GET'])
@jwt_required()
def get_printers():
    printers = Printer.query.filter_by(status='active').all()
    return jsonify([{
        'id': p.id,
        'location': p.location,
        'status': p.status
    } for p in printers])

# Print Job Endpoints
@app.route('/print_jobs', methods=['POST'])
@jwt_required()
def create_print_job():
    data = request.get_json()
    user = User.query.filter_by(username=get_jwt_identity()).first()
    
    # Check balance/premium status
    if user.account_type == 'free' and user.balance < data['cost']:
        return jsonify({'error': 'Insufficient balance'}), 400
    
    # Create print job
    new_job = PrintJob(
        user_id=user.id,
        printer_id=data['printer_id'],
        file_path=data['file_path'],
        pages=data['pages'],
        cost=data['cost'],
        status='queued'
    )
    db.session.add(new_job)
    db.session.commit()
    
    # Send to printer
    printer = Printer.query.get(data['printer_id'])
    PrinterCommunicator.send_to_printer(
        printer_ip=printer.ip_address,
        job_id=new_job.id,
        file_path=new_job.file_path
    )
    
    return jsonify({'job_id': new_job.id}), 201

# Payment Endpoints
@app.route('/payment/create-checkout-session', methods=['POST'])
@jwt_required()
def create_payment_session():
    user = User.query.filter_by(username=get_jwt_identity()).first()
    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Premium Account Upgrade',
                    },
                    'unit_amount': 999,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=request.host_url + 'payment/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=request.host_url + 'payment/cancel',
        )
        return jsonify({'sessionId': checkout_session['id']})
    except Exception as e:
        return jsonify(error=str(e)), 403

@app.route('/payment/webhook', methods=['POST'])
def stripe_webhook():
    # Handle payment confirmation webhook
    # Update user account type in database
    pass

# Printer Communication Endpoints
@app.route('/printer/status/<printer_id>', methods=['GET'])
def get_printer_status(printer_id):
    printer = Printer.query.get(printer_id)
    status = PrinterCommunicator.get_status(printer.ip_address)
    return jsonify({'status': status})

if __name__ == '__main__':
    app.run(debug=True)