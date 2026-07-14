# The model stand-in (server.py): a recording proxy in each stack's model
# path. One trivial image, shared by all three harness stacks.
FROM python:3.13-alpine

RUN pip install --no-cache-dir aiohttp==3.14.1 pydantic-settings==2.14.2

COPY server.py /app/server.py

USER nobody
EXPOSE 8080 8081
CMD ["python", "/app/server.py"]
