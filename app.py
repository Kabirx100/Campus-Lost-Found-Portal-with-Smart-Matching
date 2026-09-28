import os, sqlite3, uuid
from flask import Flask, render_template, request, redirect, url_for, g, flash, send_from_directory
from werkzeug.utils import secure_filename
from matcher import best_matches

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-change-me")
DB = os.path.join(os.path.dirname(__file__), "portal.db")
UPLOADS = os.path.join(os.path.dirname(__file__), "uploads")
CATEGORIES = ["Electronics", "ID / Cards", "Books", "Clothing", "Keys", "Bags", "Other"]

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(_):
    d = g.pop("db", None)
    if d: d.close()

def init_db():
    with sqlite3.connect(DB) as c:
        c.execute("""CREATE TABLE IF NOT EXISTS items(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT CHECK(kind IN ('lost','found')) NOT NULL,
            title TEXT NOT NULL, description TEXT DEFAULT '',
            category TEXT NOT NULL, location TEXT NOT NULL,
            date TEXT NOT NULL, contact TEXT NOT NULL,
            image TEXT, status TEXT DEFAULT 'open',
            created TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")

@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    kind = request.args.get("kind", "")
    sql, args = "SELECT * FROM items WHERE status='open'", []
    if kind in ("lost", "found"):
        sql += " AND kind=?"; args.append(kind)
    if q:
        sql += " AND (title LIKE ? OR description LIKE ? OR location LIKE ?)"
        args += [f"%{q}%"] * 3
    items = db().execute(sql + " ORDER BY created DESC", args).fetchall()
    return render_template("index.html", items=items, q=q, kind=kind)

@app.route("/report/<kind>", methods=["GET", "POST"])
def report(kind):
    if kind not in ("lost", "found"):
        return redirect(url_for("index"))
    if request.method == "POST":
        f = request.form
        image = None
        file = request.files.get("image")
        if file and file.filename:
            image = f"{uuid.uuid4().hex}_{secure_filename(file.filename)}"
            file.save(os.path.join(UPLOADS, image))
        cur = db().execute(
            "INSERT INTO items(kind,title,description,category,location,date,contact,image) VALUES(?,?,?,?,?,?,?,?)",
            (kind, f["title"], f.get("description", ""), f["category"], f["location"], f["date"], f["contact"], image))
        db().commit()
        flash("Report submitted. Here are possible matches.")
        return redirect(url_for("item", item_id=cur.lastrowid))
    return render_template("report.html", kind=kind, categories=CATEGORIES)

@app.route("/item/<int:item_id>")
def item(item_id):
    it = db().execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not it: return "Not found", 404
    opposite = "found" if it["kind"] == "lost" else "lost"
    cands = [dict(r) for r in db().execute(
        "SELECT * FROM items WHERE kind=? AND status='open'", (opposite,))]
    return render_template("item.html", item=it, matches=best_matches(dict(it), cands))

@app.route("/item/<int:item_id>/resolve", methods=["POST"])
def resolve(item_id):
    db().execute("UPDATE items SET status='resolved' WHERE id=?", (item_id,))
    db().commit()
    flash("Marked as resolved.")
    return redirect(url_for("index"))

@app.route("/uploads/<path:name>")
def uploads(name):
    return send_from_directory(UPLOADS, name)

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
  
