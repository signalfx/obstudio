"""Separate source-owned operations used to check orchestration classification."""


def one_shot(client, model, messages):
    return client.chat.completions.create(model=model, messages=messages)


def summarize_then_translate(client, model, text):
    summary = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": "Summarize: " + text}]
    )
    return client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Translate: " + summary.choices[0].message.content}],
    )
