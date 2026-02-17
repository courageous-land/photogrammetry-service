# Dockerfile otimizado para Cloud Run
FROM python:3.11.11-slim

WORKDIR /app

# Variáveis de ambiente padrão
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Instala dependências do sistema (gcc necessário para compilar grpcio),
# instala pacotes Python e remove gcc para reduzir superfície de ataque
COPY requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove gcc \
    && rm -rf /var/lib/apt/lists/*

# Cria usuário não-root
RUN useradd -m -u 1000 appuser

# Copia código
COPY . .

# Ajusta permissões
RUN chown -R appuser:appuser /app

# Executa como não-root
USER appuser

# Cloud Run usa a porta da variável PORT (padrão 8080)
ENV PORT=8080
EXPOSE 8080

# Comando para Cloud Run
CMD exec uvicorn main:app --host 0.0.0.0 --port $PORT
