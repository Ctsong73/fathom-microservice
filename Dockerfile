# Dockerfile
FROM python:3.9-slim

WORKDIR /app

# Copy requirements first (for better caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the src directory (contains all your Python files AND static/templates)
COPY src/ ./src/

# Create data directory for SQLite database
RUN mkdir -p /app/data

# Expose port
EXPOSE 5000

# Run the application
CMD ["python", "src/app.py"]