# assistente-academico-terceiro-ciclo
Este é um projeto desenvolvido por 7 pessoas que tem um viés servir alunos de uma universidade, que cursam algo que envolva tecnologia,

## O que tem no projeto

| Arquivo | Para que serve |
|---|---|
| `projeto_mimir.py` | Servidor Flask: login, rotas do aluno/professor e a conversa com a IA (Ollama) |
| `index.html` | Todo o front-end (telas, estilos e scripts num arquivo só) |
| `criar_banco.py` | Cria o banco `universidade.db` e popula com dados de exemplo (ou com o `dados_exportados.json`, se existir) |
| `exportar_dados.py` | Exporta o banco inteiro para `dados_exportados.json` (para levar os dados pra outra máquina) |
| `requirements.txt` | Lista de dependências Python |
| `.env.example` | Modelo das variáveis de ambiente (copie para `.env`) |

## Como rodar pela primeira vez

1. Instale as dependências:
   ```
   pip install -r requirements.txt
   ```
2. Copie o `.env.example` para `.env` e preencha (pelo menos o `ollama_model`).
3. Tenha o [Ollama](https://ollama.com) rodando com o modelo configurado no `.env`.
4. Crie o banco de dados:
   ```
   python criar_banco.py
   ```
5. Suba o servidor:
   ```
   python projeto_mimir.py
   ```
6. Abra http://localhost:5000 no navegador.

Para expor na internet, defina `USAR_NGROK=true` e o `ngrok_token` no `.env`
(nesse modo o debug do Flask é desligado automaticamente, por segurança).
