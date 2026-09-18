"""Small health endpoint for the Azure WebJob host."""

from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/health")
def health():
    return jsonify(status="ok", service="google-indexing-pipeline")


@app.get("/health/db")
def database_health():
    from db.models import get_connection

    try:
        with get_connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT count(*) AS n FROM urls")
                count = cursor.fetchone()["n"]
        return jsonify(status="ok", database="ok", urls=count)
    except Exception:
        return jsonify(status="error", database="unavailable"), 503
