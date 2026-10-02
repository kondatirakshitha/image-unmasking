"""Image-authenticity Flask app, ready for local use or cloud deployment."""
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path

from flask import Flask, flash, g, jsonify, redirect, render_template, request, session, url_for
from PIL import Image, UnidentifiedImageError
import requests
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)
DATABASE_PATH = BASE_DIR / "truthlens.db"

app = Flask(__name__, template_folder=str(BASE_DIR))
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "change-this-before-public-deployment")

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_error):
    connection = g.pop("db", None)
    if connection is not None:
        connection.close()


def initialise_database():
    connection = sqlite3.connect(DATABASE_PATH)
    connection.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            image_name TEXT NOT NULL,
            result TEXT NOT NULL,
            confidence REAL NOT NULL,
            ai_score REAL NOT NULL,
            real_score REAL NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id)
        );
    """)
    connection.commit()
    connection.close()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            if request.path in {"/upload", "/batch-upload"}:
                return jsonify(error="Sign in to analyse and save your results."), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


@app.context_processor
def add_current_user():
    return {"current_username": session.get("username")}


initialise_database()


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def classify_image(img_path):
    """Call Sightengine's maintained AI-image detection API."""
    api_user = os.getenv("SIGHTENGINE_API_USER")
    api_secret = os.getenv("SIGHTENGINE_API_SECRET")
    if not api_user or not api_secret:
        raise RuntimeError("Sightengine credentials are not configured yet.")
    try:
        with open(img_path, "rb") as media:
            response = requests.post(
                "https://api.sightengine.com/1.0/check.json",
                data={"models": "genai", "api_user": api_user, "api_secret": api_secret},
                files={"media": (img_path.name, media, "application/octet-stream")},
                timeout=45,
            )
        data = response.json()
    except (requests.RequestException, ValueError) as error:
        raise RuntimeError("Could not contact Sightengine. Check your internet connection.") from error
    if not response.ok or data.get("status") != "success":
        raise RuntimeError(data.get("error", {}).get("description", "Sightengine could not analyse this image."))
    ai_score = float(data["type"]["ai_generated"])
    real_score = 1 - ai_score
    if ai_score >= 0.80:
        result, confidence = "Likely AI-generated or AI-edited", ai_score * 100
    elif ai_score <= 0.20:
        result, confidence = "Likely real", real_score * 100
    else:
        result = "Inconclusive — needs another check"
        confidence = max(ai_score, real_score) * 100
    return result, round(confidence, 2), round(ai_score * 100, 2), round(real_score * 100, 2)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        password = request.form.get("password", "")

        # Username can be any non-empty text.
        if not username:
            flash("Please enter a username.")
        elif len(password) < 8:
            flash("Use a password with at least 8 characters.")
        else:
            try:
                db = get_db()
                db.execute(
                    "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                    (username, generate_password_hash(password), datetime.now(timezone.utc).isoformat()),
                )
                db.commit()
                user = db.execute(
                    "SELECT id, username FROM users WHERE username = ?", (username,)
                ).fetchone()
                session.clear()
                session["user_id"], session["username"] = user["id"], user["username"]
                return redirect(url_for("home"))
            except sqlite3.IntegrityError:
                flash("That username is already in use.")
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip().lower()
        user = get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if user is None or not check_password_hash(
            user["password_hash"], request.form.get("password", "")
        ):
            flash("Incorrect username or password.")
        else:
            session.clear()
            session["user_id"], session["username"] = user["id"], user["username"]
            return redirect(url_for("home"))
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.get("/history")
@login_required
def history():
    rows = get_db().execute(
        "SELECT image_name, result, confidence, ai_score, real_score, created_at FROM scans "
        "WHERE user_id = ? ORDER BY id DESC LIMIT 50",
        (session["user_id"],),
    ).fetchall()
    return render_template("history.html", scans=rows)


@app.route("/upload", methods=["POST"])
@login_required
def upload_image():
    file = request.files.get("image")
    if not file or not file.filename:
        return jsonify(error="No image uploaded."), 400
    if not allowed_file(file.filename):
        return jsonify(error="Upload a JPG, PNG, or WebP image."), 400

    original_name = secure_filename(file.filename)
    stored_name = f"{uuid.uuid4().hex}_{original_name}"
    save_path = UPLOAD_DIR / stored_name
    file.save(save_path)
    try:
        with Image.open(save_path) as image:
            image.verify()
        with Image.open(save_path) as image:
            width, height = image.size
            metadata_present = bool(image.getexif())
        result, confidence, ai_score, real_score = classify_image(save_path)
    except (UnidentifiedImageError, OSError):
        return jsonify(error="The uploaded file is not a valid image."), 400
    except RuntimeError as error:
        return jsonify(error=str(error)), 503
    finally:
        save_path.unlink(missing_ok=True)

    db = get_db()
    db.execute(
        "INSERT INTO scans (user_id, image_name, result, confidence, ai_score, real_score, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            session["user_id"], original_name, result, confidence, ai_score, real_score,
            datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC"),
        ),
    )
    db.commit()

    return jsonify(
        filename=original_name,
        result=result,
        confidence=confidence,
        ai_score=ai_score,
        real_score=real_score,
        image_size={"width": width, "height": height},
        metadata_present=metadata_present,
        notice="Powered by Sightengine. Scores between 20% and 80% are shown as inconclusive.",
    )


@app.route("/batch-upload", methods=["POST"])
@login_required
def batch_upload():
    """Analyse a small folder selection without exhausting the API quota."""
    files = [file for file in request.files.getlist("images") if file and file.filename]
    valid_files = [file for file in files if allowed_file(file.filename)]
    if not valid_files:
        return jsonify(error="Choose a folder containing JPG, PNG, or WebP images."), 400
    if len(valid_files) > 20:
        return jsonify(error="A batch can contain up to 20 images. Split a larger folder into smaller batches."), 400

    rows, errors = [], []
    db = get_db()
    for file in valid_files:
        original_name = secure_filename(file.filename) or "image"
        save_path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{original_name}"
        try:
            file.save(save_path)
            if save_path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError("Image is larger than 10 MB.")
            with Image.open(save_path) as image:
                image.verify()
            result, confidence, ai_score, real_score = classify_image(save_path)
            db.execute(
                "INSERT INTO scans (user_id, image_name, result, confidence, ai_score, real_score, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    session["user_id"], original_name, result, confidence, ai_score, real_score,
                    datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC"),
                ),
            )
            rows.append({
                "filename": original_name,
                "result": result,
                "confidence": confidence,
                "ai_score": ai_score,
                "real_score": real_score,
            })
        except (UnidentifiedImageError, OSError, ValueError, RuntimeError) as error:
            errors.append({"filename": original_name, "error": str(error)})
        finally:
            save_path.unlink(missing_ok=True)
    db.commit()
    return jsonify(
        results=rows,
        errors=errors,
        summary={
            "ai": sum(row["result"].startswith("Likely AI") for row in rows),
            "real": sum(row["result"] == "Likely real" for row in rows),
            "inconclusive": sum(row["result"].startswith("Inconclusive") for row in rows),
        },
    )


@app.errorhandler(413)
def file_too_large(_error):
    return jsonify(error="Image must be 10 MB or smaller."), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
