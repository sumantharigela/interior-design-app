from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os
from dotenv import load_dotenv
import json
import uuid

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///interior_design.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    projects = db.relationship('Project', backref='owner', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    room_type = db.Column(db.String(50), nullable=False)
    style = db.Column(db.String(50), nullable=False)
    color_scheme = db.Column(db.String(50))
    dimensions = db.Column(db.String(100))
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    elements = db.relationship('DesignElement', backref='project', lazy=True, cascade='all, delete-orphan')

class DesignElement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    element_type = db.Column(db.String(50), nullable=False)  # furniture, lighting, wall, floor
    name = db.Column(db.String(100), nullable=False)
    dimensions = db.Column(db.String(100))
    color = db.Column(db.String(50))
    quantity = db.Column(db.Integer, default=1)
    notes = db.Column(db.Text)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create tables
with app.app_context():
    db.create_all()

# Routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']
        
        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))
        
        user = User(username=username, email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        
        flash('Registration successful! Please login.')
        return redirect(url_for('login'))
    
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('dashboard'))
        
        flash('Invalid username or password')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    projects = Project.query.filter_by(user_id=current_user.id).order_by(Project.created_at.desc()).all()
    return render_template('dashboard.html', projects=projects)

@app.route('/create_project', methods=['GET', 'POST'])
@login_required
def create_project():
    if request.method == 'POST':
        project = Project(
            name=request.form['name'],
            room_type=request.form['room_type'],
            style=request.form['style'],
            color_scheme=request.form.get('color_scheme', ''),
            dimensions=request.form.get('dimensions', ''),
            description=request.form.get('description', ''),
            user_id=current_user.id
        )
        db.session.add(project)
        db.session.commit()
        
        flash('Project created successfully!')
        return redirect(url_for('project_detail', project_id=project.id))
    
    return render_template('create_project.html')

@app.route('/project/<int:project_id>')
@login_required
def project_detail(project_id):
    project = Project.query.get_or_404(project_id)
    if project.user_id != current_user.id:
        flash('Access denied')
        return redirect(url_for('dashboard'))
    return render_template('project_detail.html', project=project)

@app.route('/api/add_element', methods=['POST'])
@login_required
def add_element():
    data = request.json
    element = DesignElement(
        element_type=data['element_type'],
        name=data['name'],
        dimensions=data.get('dimensions', ''),
        color=data.get('color', ''),
        quantity=data.get('quantity', 1),
        notes=data.get('notes', ''),
        project_id=data['project_id']
    )
    
    # Verify project ownership
    project = Project.query.get(data['project_id'])
    if project and project.user_id == current_user.id:
        db.session.add(element)
        db.session.commit()
        return jsonify({'success': True, 'element_id': element.id})
    
    return jsonify({'success': False, 'error': 'Unauthorized'}), 403

@app.route('/api/delete_element/<int:element_id>', methods=['DELETE'])
@login_required
def delete_element(element_id):
    element = DesignElement.query.get_or_404(element_id)
    if element.project.user_id == current_user.id:
        db.session.delete(element)
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': 'Unauthorized'}), 403

@app.route('/api/style_recommendations', methods=['POST'])
def get_recommendations():
    """AI-like recommendations based on room style"""
    data = request.json
    style = data.get('style', 'modern')
    room_type = data.get('room_type', 'living')
    
    recommendations = {
        'modern': {
            'colors': ['Neutral tones', 'Black and white', 'Gray', 'Beige'],
            'furniture': ['Minimalist sofas', 'Glass tables', 'Geometric shapes'],
            'accessories': ['Abstract art', 'Metal accents', 'Simple vases']
        },
        'scandinavian': {
            'colors': ['White', 'Light gray', 'Pastel accents', 'Natural wood'],
            'furniture': ['Light wood pieces', 'Comfortable sofas', 'Simple chairs'],
            'accessories': ['Wool throws', 'Ceramic vases', 'Indoor plants']
        },
        'industrial': {
            'colors': ['Dark gray', 'Brown', 'Black', 'Brick red'],
            'furniture': ['Metal frames', 'Leather sofas', 'Reclaimed wood'],
            'accessories': ['Exposed bulbs', 'Vintage signs', 'Metal art']
        },
        'bohemian': {
            'colors': ['Earthy tones', 'Patterns', 'Jewel tones', 'Natural hues'],
            'furniture': ['Low seating', 'Wooden pieces', 'Floor cushions'],
            'accessories': ['Macramé', 'Textiles', 'Plants', 'Tapestries']
        }
    }
    
    rec = recommendations.get(style, recommendations['modern'])
    
    return jsonify({
        'style': style,
        'room_type': room_type,
        'recommendations': rec,
        'message': f'Based on {style} style for your {room_type} room'
    })

@app.route('/health')
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.utcnow().isoformat()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=False)
