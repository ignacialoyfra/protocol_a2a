import ollama

client = ollama.Client(host='http://127.0.0.1:11434')

# sanity check: lista de modelos
print(client.list())

# chat
resp = client.chat(
    model='llama3:8b',
    messages=[{'role':'user','content':'Resume: El agua es esencial para la vida en español.'}]
)
print(resp['message']['content'])
