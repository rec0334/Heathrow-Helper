from datetime import datetime, timezone

from flask import render_template, request, jsonify, Response, send_from_directory

from .bot import respond_full


PAGE_META = {
    "/": {
        "title": "Heathrow Helper",
        "description": "Live flight status, terminals, lounges, security wait times, transport and customs help for London Heathrow Airport. Free chat assistant powered by Heathrow's own live board.",
    },
    "/about": {
        "title": "About",
        "description": "Heathrow Helper is an unofficial passenger assistant for London Heathrow Airport built to help first-time fliers and older passengers quickly find flight, terminal, lounge and transport information.",
    },
    "/privacy": {
        "title": "Privacy Policy",
        "description": "How Heathrow Helper handles your data. No accounts, no tracking, no advertising. Chat messages processed in memory only.",
    },
    "/terms": {
        "title": "Terms of Service",
        "description": "Terms of Service for Heathrow Helper, an independent unofficial passenger assistant for London Heathrow Airport.",
    },
    "/contact": {
        "title": "Contact",
        "description": "Report a bug, suggest a fix, or get in touch with the Heathrow Helper team.",
    },
}


def _meta(path):
    m = PAGE_META.get(path, {"title": "Heathrow Helper", "description": "Heathrow Helper."})
    return {"path": path, "title": m["title"], "description": m["description"]}


def register_routes(app):
    @app.after_request
    def set_security_headers(resp):
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        resp.headers.setdefault("Permissions-Policy", "geolocation=(), camera=(), microphone=(self), payment=(), fullscreen=(self)")
        return resp

    @app.route("/")
    def index():
        return render_template("index.html", **_meta("/"))

    @app.route("/about")
    def about():
        return render_template("about.html", **_meta("/about"))

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html", **_meta("/privacy"))

    @app.route("/terms")
    def terms():
        return render_template("terms.html", **_meta("/terms"))

    @app.route("/contact")
    def contact():
        return render_template("contact.html", **_meta("/contact"))

    @app.route("/chat", methods=["POST"])
    def chat():
        msg = (request.json or {}).get("message", "").strip()
        return jsonify(respond_full(msg))

    @app.route("/health")
    def health():
        return jsonify({"ok": True, "service": "heathrow-helper", "time": datetime.now(timezone.utc).isoformat()})

    @app.route("/robots.txt")
    def robots_txt():
        base = request.host_url.rstrip("/")
        body = (
            "User-agent: *\n"
            "Allow: /\n"
            "Disallow: /chat\n"
            "Disallow: /health\n\n"
            f"Sitemap: {base}/sitemap.xml\n"
        )
        return Response(body, mimetype="text/plain")

    @app.route("/sitemap.xml")
    def sitemap_xml():
        base = request.host_url.rstrip("/")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        urls = [
            ("/", "daily", "1.0"),
            ("/about", "monthly", "0.7"),
            ("/privacy", "yearly", "0.4"),
            ("/terms", "yearly", "0.4"),
            ("/contact", "monthly", "0.5"),
        ]
        body = ['<?xml version="1.0" encoding="UTF-8"?>',
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
        for path, freq, prio in urls:
            body.append(
                f"  <url><loc>{base}{path}</loc><lastmod>{today}</lastmod><changefreq>{freq}</changefreq><priority>{prio}</priority></url>"
            )
        body.append("</urlset>")
        return Response("\n".join(body), mimetype="application/xml")

    @app.route("/favicon.ico")
    def favicon_ico():
        return send_from_directory(app.static_folder, "favicon.svg", mimetype="image/svg+xml")
