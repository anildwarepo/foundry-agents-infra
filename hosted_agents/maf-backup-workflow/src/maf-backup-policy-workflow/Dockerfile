FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY backup_api/ ./backup_api/
COPY backup_mock_data.json ./backup_mock_data.json
COPY hosted_agent.py ./hosted_agent.py

EXPOSE 8088

RUN PYTHONDONTWRITEBYTECODE= python -m compileall -q .

CMD ["python", "hosted_agent.py"]