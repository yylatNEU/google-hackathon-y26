FROM python:3.13-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY . .

# Cloud Run sets the PORT environment variable
ENV PORT=8000
EXPOSE ${PORT}

# Run the FastAPI server
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT}
