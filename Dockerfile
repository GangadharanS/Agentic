FROM python:3.11-slim

WORKDIR /app

# Copy requirements first to leverage Docker cache
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all application files
COPY . .

# If custom_mcp_tools is a local package, install it in editable mode
RUN if [ -f "setup.py" ]; then pip install -e .; fi

EXPOSE 8000

CMD ["python", "main.py"]