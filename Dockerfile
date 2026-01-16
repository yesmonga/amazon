FROM python:3.10-slim

WORKDIR /app

# Copy requirements first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app files
COPY . .

# Expose port
EXPOSE 5000

# Run with gunicorn on dynamic PORT with logging
CMD gunicorn --workers 1 --bind 0.0.0.0:$PORT --timeout 120 --access-logfile - --error-logfile - --capture-output --enable-stdio-inheritance app:app
