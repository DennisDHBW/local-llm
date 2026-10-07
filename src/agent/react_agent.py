import re
import ollama
from typing import List, Dict
from src.agent.tools import AgentTools


class ReActAgent:
    def __init__(self, model_name: str = "llama3.1:latest"):
        self.model_name = model_name
        self.tools = AgentTools()

        # System-Prompt definiert die Persona und erzwingt das ReAct-Format[cite: 1, 35, 36]
        self.system_prompt = """Du bist der 'Private Energie- & Versorgungs-Auditor', ein lokaler KI-Agent zur Prüfung von Rechnungen.
        Dir stehen folgende Werkzeuge (Tools) zur Verfügung:
        1. search_documents: Sucht in Texten nach Klauseln/Vertragsdetails (Parameter: query, top_k)
        2. search_tables: Sucht in Tabellen nach Zahlen, Verbräuchen, Preisen (Parameter: query, top_k)
        3. search_images: Sucht in Diagramm-Bildbeschreibungen (Parameter: query, top_k)
        4. get_document_outline: Zeigt die Struktur/Überschriften des Dokuments (Parameter: filename_filter)
        5. calculate: Führt mathematische Berechnungen aus. WICHTIG: Übermittle NUR reine Zahlen und Operatoren (z.B. 29.05 + 3.65 oder 32.337 * 3500), keine Einheiten!

        Führe immer nur GENAU EINE Action pro Durchlauf aus!

        Du MUSST strikt in folgendem Format antworten:

        Thought: [Deine Überlegung, was als Nächstes zu tun ist]
        Action: [Name des Werkzeugs]
        Action Input: [Der Parameter für das Werkzeug]

        Wenn du alle Informationen hast und das Ziel erreicht ist, beende die Aufgabe so:

        Thought: Ich habe alle Informationen.
        Final Answer: [Deine finale Antwort mit Quellenbeleg]
        """

    def run(self, user_query: str, max_iterations: int = 7) -> str:
        """Startet die ReAct-Schleife (Thought -> Action -> Observation)[cite: 1, 35, 36, 42]."""

        # Initialer Chat-Verlauf
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": f"Frage: {user_query}"}
        ]

        print(f"\n--- Starte Agenten-Loop für: '{user_query}' ---\n")

        for i in range(max_iterations):
            # 1. LLM generiert einen Thought und eine Action (oder Final Answer)
            response = ollama.chat(
                model=self.model_name,
                messages=messages,
                options={"stop": ["Observation:"]}  # Zwingt das LLM zum Warten
            )
            llm_output = response["message"]["content"]
            print(llm_output + "\n")

            messages.append({"role": "assistant", "content": llm_output})

            # 2. Prüfen, ob das LLM fertig ist[cite: 1, 35]
            if "Final Answer:" in llm_output:
                return llm_output.split("Final Answer:")[-1].strip()

            # 3. Parsen der Action und des Inputs via Regex (nur die erste Aktion nehmen)
            action_match = re.search(r"Action:\s*(.*)", llm_output)
            input_match = re.search(r"Action Input:\s*(.*)", llm_output)

            if action_match and input_match:
                action = action_match.group(1).strip()
                action_input = input_match.group(1).strip()

                # Falls das Modell Zeilenumbrüche im Input hat, nur die erste Zeile nehmen
                action_input = action_input.split('\n')[0].strip()

                # 4. Tool ausführen (Action -> Observation)[cite: 1, 35, 36]
                observation = self._execute_tool(action, action_input)
                print(f"\033[93mObservation: {observation}\033[0m\n")  # Gelbe Farbe für Sichtbarkeit in Konsole

                # Observation dem Modell mitteilen
                messages.append({"role": "user", "content": f"Observation: {observation}"})
            else:
                # Modell hat das Format missachtet
                error_msg = "Formatfehler. Bitte nutze strikt 'Thought:', 'Action:' und 'Action Input:'."
                messages.append({"role": "user", "content": f"Observation: {error_msg}"})
                print(f"\033[91m{error_msg}\033[0m\n")

        return "Abbruch: Die maximale Anzahl an Iterationen wurde überschritten."

    def _execute_tool(self, action: str, action_input: str) -> str:
        """Mappt den String des Modells auf die Python-Methoden[cite: 1, 41]."""
        if action == "search_documents":
            return self.tools.search_documents(action_input)
        elif action == "search_tables":
            return self.tools.search_tables(action_input)
        elif action == "search_images":
            return self.tools.search_images(action_input)
        elif action == "get_document_outline":
            return self.tools.get_document_outline(action_input)
        elif action == "calculate":
            return self.tools.calculate(action_input)
        else:
            return f"Fehler: Unbekanntes Werkzeug '{action}'."


# --- Direkter Test-Block ---
if __name__ == "__main__":
    agent = ReActAgent()
    # Testen wir den in der Prüfung geforderten "Multi-Hop & Multimodal" Grenzfall[cite: 1, 45]
    test_query = "Wie hoch ist der aktuelle Arbeitspreis laut Tabelle und was ergibt das bei 3500 kWh Jahresverbrauch?"

    ergebnis = agent.run(test_query)
    print("\n\033[92m=== FINALES ERGEBNIS ===\033[0m")
    print(ergebnis)