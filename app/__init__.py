import os
from flask import Flask
from .models import db


def create_app():
    app = Flask(__name__, instance_relative_config=True)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-key-change-in-production")
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///" + os.path.join(
        app.instance_path, "attendance.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB upload limit

    os.makedirs(app.instance_path, exist_ok=True)

    db.init_app(app)

    with app.app_context():
        from .routes import instructor, student
        app.register_blueprint(instructor.bp)
        app.register_blueprint(student.bp)
        db.create_all()

    return app
