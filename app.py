from flask import Flask
from routes.webhook_routes import webhook_bp
from config import LOG_FILE
from services.logger import setup_logging



# Initialize Flask app
app = Flask(__name__)

# Setup logging
setup_logging(LOG_FILE)

# Register routes
app.register_blueprint(webhook_bp, url_prefix='/webhook')

@app.route("/")
def index():
    return "Flask running!"

@app.route("/status")
def status():
    return {"status": "Application is running", "version": "1.0"}

if __name__ == '__main__':
    # Specify the host and port; enable debug mode for development
    app.run(host='0.0.0.0', port=5001, debug=True)
