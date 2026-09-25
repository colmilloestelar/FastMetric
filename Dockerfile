FROM python:3.12-slim

WORKDIR /srv/fastmetric

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./server/
COPY web/ ./web/

ENV SERVER_HOST=0.0.0.0
ENV SERVER_PORT=8456

EXPOSE 8456

CMD ["python", "-m", "server"]