# Opérations

## Démarrage

```bash
uvicorn main:app --reload
```

## Health Check

```bash
curl http://localhost:8000/health
```

## Premier cycle

```bash
curl -X POST http://localhost:8000/cycle \
  -H "Content-Type: application/json" \
  -d '{"message": "Analyse nos documents fondateurs"}'
```

## Tests

```bash
pytest tests/ -v
coverage run -m pytest tests/
coverage report
```

## Documentation

```bash
pip install mkdocs-material
mkdocs serve
```
