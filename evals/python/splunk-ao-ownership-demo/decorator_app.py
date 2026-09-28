"""Independent entrypoint where Splunk AO owns application GenAI spans."""

from splunk_ao import log


@log(span_type="retriever")
def search_documents(query: str) -> list[str]:
    return [f"private document matching {query}"]


@log(span_type="tool")
def get_weather(city: str) -> str:
    return f"Weather for {city}: sunny"


@log
def answer_question(account_id: str, question: str) -> str:
    documents = search_documents(question)
    weather = get_weather("Seattle")
    return f"{account_id}: {question}: {documents[0]}: {weather}"
