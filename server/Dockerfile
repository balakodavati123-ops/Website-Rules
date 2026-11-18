# Live price relay. Build from the repository root:  docker build -f server/Dockerfile -t desk-stream .
FROM python:3.12-slim
WORKDIR /app
COPY server/requirements.txt server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt
COPY server server
RUN pip install --no-cache-dir grpcio-tools && cd server && python -m grpc_tools.protoc -I. --python_out=. MarketDataFeedV3.proto && pip uninstall -y grpcio-tools
COPY backend backend
ENV PORT=8787
EXPOSE 8787
CMD ["python", "server/stream.py"]
