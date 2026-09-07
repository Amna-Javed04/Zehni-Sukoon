# ---------------------------------------------------------
# Zehni Sukoon — production image
# ---------------------------------------------------------

FROM python:3.11-slim

# Prevent python from writing pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV FLASK_ENV=production

WORKDIR /app

# Install system dependencies (build-essential needed for any C-extension compilations)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . /app/

# Expose the default port; platforms like Railway inject $PORT at runtime.
EXPOSE 5000

# Start Flask app using Gunicorn WSGI server in production mode.
# ${PORT:-5000} lets the platform override the port; falls back to 5000 locally.
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-5000} --workers 4 --timeout 120 run:app"]
