import os
from datetime import datetime
from flask import (
    Flask, render_template, redirect, url_for, request,
    flash, send_from_directory, abort
)
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, login_user, login_required,
    logout_user, current_user, UserMixin
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

# ----------------------------
# Config
# ----------------------------
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "dev-secret-key-change-this")
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    "DATABASE_URL",
    "sqlite:///" + os.path.join(BASE_DIR, "instance", "app.db")
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024  # 4MB uploads

# Ensure instance folder exists
os.makedirs(os.path.join(BASE_DIR, "instance"), exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ----------------------------
# Models
# ----------------------------
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    display_name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(200), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    bio = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    projects = db.relationship('Project', backref='owner', lazy=True)
    bids = db.relationship('Bid', backref='bidder', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    budget = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    image = db.Column(db.String(300), nullable=True)  # filename if uploaded

    bids = db.relationship('Bid', backref='project', lazy=True)

class Bid(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    price = db.Column(db.String(80), nullable=False)
    message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    project_id = db.Column(db.Integer, db.ForeignKey('project.id'), nullable=False)
    bidder_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    accepted = db.Column(db.Boolean, default=False)

# ----------------------------
# Login loader
# ----------------------------
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ----------------------------
# Utility: allowed uploads
# ----------------------------
ALLOWED_EXT = {"png", "jpg", "jpeg", "gif"}
def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

# ----------------------------
# Routes: Public
# ----------------------------
@app.route("/")
def index():
    projects = Project.query.order_by(Project.created_at.desc()).limit(20).all()
    return render_template("index.html", projects=projects)

@app.route("/project/<int:project_id>")
def project_detail(project_id):
    project = Project.query.get_or_404(project_id)
    return render_template("project_detail.html", project=project)

# Serve uploaded files (optional)
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# ----------------------------
# Auth: register / login / logout
# ----------------------------
@app.route("/register", methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        display_name = request.form.get("display_name", username)

        if not username or not email or not password:
            flash("لطفاً همه‌ی فیلدها را پر کنید.", "danger")
            return redirect(url_for('register'))

        if User.query.filter((User.username == username) | (User.email == email)).first():
            flash("نام کاربری یا ایمیل قبلاً استفاده شده.", "warning")
            return redirect(url_for('register'))

        user = User(username=username, email=email, display_name=display_name)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        login_user(user)
        flash("خوش آمدی! حساب ساخته شد.", "success")
        return redirect(url_for('index'))

    return render_template("register.html")

@app.route("/login", methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter((User.username==username) | (User.email==username)).first()
        if user and user.check_password(password):
            login_user(user, remember=True)
            flash("ورود موفقیت‌آمیز بود.", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("نام کاربری یا رمز عبور اشتباه است.", "danger")
            return redirect(url_for('login'))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("از حساب خارج شدید.", "info")
    return redirect(url_for('index'))

# ----------------------------
# Project creation & bidding
# ----------------------------
@app.route("/projects/new", methods=['GET', 'POST'])
@login_required
def new_project():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip()
        budget = request.form.get("budget", "").strip()
        file = request.files.get("image")

        if not title or not description:
            flash("عنوان و توضیحات لازم است.", "warning")
            return redirect(url_for('new_project'))

        filename = None
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(f"{int(datetime.utcnow().timestamp())}_{file.filename}")
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

        project = Project(
            title=title, description=description,
            budget=budget, owner_id=current_user.id,
            image=filename
        )
        db.session.add(project)
        db.session.commit()
        flash("پروژه با موفقیت ایجاد شد.", "success")
        return redirect(url_for('project_detail', project_id=project.id))

    return render_template("new_project.html")

@app.route("/projects/<int:project_id>/bid", methods=['POST'])
@login_required
def place_bid(project_id):
    project = Project.query.get_or_404(project_id)
    price = request.form.get("price", "").strip()
    message = request.form.get("message", "").strip()

    if not price:
        flash("قیمت پیشنهاد لازم است.", "warning")
        return redirect(url_for('project_detail', project_id=project_id))

    bid = Bid(price=price, message=message, project_id=project.id, bidder_id=current_user.id)
    db.session.add(bid)
    db.session.commit()
    flash("پیشنهاد ارسال شد.", "success")
    return redirect(url_for('project_detail', project_id=project_id))

@app.route("/projects/<int:project_id>/bid/<int:bid_id>/accept", methods=['POST'])
@login_required
def accept_bid(project_id, bid_id):
    project = Project.query.get_or_404(project_id)
    if project.owner_id != current_user.id:
        abort(403)
    bid = Bid.query.filter_by(id=bid_id, project_id=project.id).first_or_404()
    # simple logic: mark this bid accepted and others not
    for b in project.bids:
        b.accepted = False
    bid.accepted = True
    db.session.commit()
    flash("پیشنهاد پذیرفته شد.", "success")
    return redirect(url_for('project_detail', project_id=project_id))

# ----------------------------
# User dashboard & profile
# ----------------------------
@app.route("/dashboard")
@login_required
def dashboard():
    my_projects = Project.query.filter_by(owner_id=current_user.id).order_by(Project.created_at.desc()).all()
    my_bids = Bid.query.filter_by(bidder_id=current_user.id).order_by(Bid.created_at.desc()).all()
    return render_template("dashboard.html", projects=my_projects, bids=my_bids)

@app.route("/profile/<int:user_id>")
@login_required
def profile(user_id):
    user = User.query.get_or_404(user_id)
    projects = Project.query.filter_by(owner_id=user.id).order_by(Project.created_at.desc()).all()
    return render_template("profile.html", user=user, projects=projects)

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/contact')
def contact():
    return render_template('contact.html')


# ----------------------------
# CLI helper to init db
# ----------------------------
@app.cli.command("init-db")
def init_db():
    db.create_all()
    print("Database initialized.")

# ----------------------------
# Run
# ----------------------------
if __name__ == "__main__":
    # if db doesn't exist, create
    if not os.path.exists(os.path.join(BASE_DIR, "instance", "app.db")):
        with app.app_context():
            db.create_all()
            print("Created DB.")
    app.run(debug=True, host="0.0.0.0", port=5000)
