import ollama

# 1. Chat- & Reasoning-Modell testen
print("Teste Chat-Modell (llama3.1:8b)...")
chat_response = ollama.chat(
    model='llama3.1:8b',
    messages=[{'role': 'user', 'content': 'Antworte kurz auf Deutsch: Ist das System bereit?'}]
)
print("Antwort:", chat_response['message']['content'])

# 2. Embedding-Modell testen
print("\nTeste Embedding-Modell (nomic-embed-text)...")
embed_response = ollama.embeddings(
    model='nomic-embed-text',
    prompt='Testvektor für ChromaDB'
)
print("Embedding erfolgreich erzeugt! Dimension:", len(embed_response['embedding']))

# 3. Query-Rewriting-Modell testen
print("\nTeste Query-Rewriter (llama3.2)...")
rewriter_response = ollama.chat(
    model='llama3.2',
    messages=[{'role': 'user', 'content': 'Formuliere kurz um: Was kostet Strom?'}]
)
print("Antwort:", rewriter_response['message']['content'])

# 4. Vision-Modell testen
print("\nTeste Vision-Modell (gemma3:4b)...")
vision_response = ollama.chat(
    model='gemma3:4b',
    messages=[{'role': 'user', 'content': 'Bist du einsatzbereit?'}]
)
print("Antwort:", vision_response['message']['content'])
