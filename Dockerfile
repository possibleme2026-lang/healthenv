FROM python:3.13-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY data ./data
COPY generated ./generated
RUN pip install --no-cache-dir .

EXPOSE 8765
CMD ["healthenv", "serve", "generated/demo/healthenv-83c7e7283dac.json", "--host", "0.0.0.0", "--port", "8765"]
