# Use official Python image from Docker Hub
FROM python:3.14-alpine

# Set working directory in container
WORKDIR /app

# Copy requirements.txt to the working directory
COPY requirements.txt .

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the Python script and any other required files into the container
COPY *.py .
# Command to run the Python script
CMD ["python","-u", "sync.py"]