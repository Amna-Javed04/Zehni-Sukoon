"""
Entry point — run with:
    python run.py
or (with venv active):
    flask run
"""

from backend.app import create_app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
