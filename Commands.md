streamlit run app.py --> Web-Gui
## Lokaler Start

```bash
uv sync
ollama serve
ollama pull nomic-embed-text
ollama pull gemma3:4b
ollama pull llama3.1:latest
streamlit run app.py
```

Die drei Pipeline-Schritte werden in der Streamlit-Seitenleiste nacheinander
ausgeführt:

1. PDF-Dateien hochladen und parsen
2. Bild-Captions und Tabellen-Summaries erzeugen
3. Chunks in ChromaDB vektorisieren

## Einzelne Schritte per CLI

```bash
python -m src.ingestion.parser
python -m src.enrichment.captioner
python -m src.enrichment.summarizer
python -m src.retrieval.vector_store
python -m src.agent.react_agent
```

Für einen schnellen Ollama-Test:

```bash
python test_ollama.py
```

Die PDF-Dateien bleiben unter `data/raw/`; erzeugte JSON-Dateien, Bilder und
der Vektorindex liegen unter `data/processed/` beziehungsweise `data/vectors/`.