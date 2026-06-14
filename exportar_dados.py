import sqlite3 # banco de dados
import json # gravar os dados num arquivo de texto legível (e versionável no git)

CAMINHO_BANCO = "universidade.db" # mesmo arquivo de banco usado pelo projeto_mimir.py
ARQUIVO_DADOS = "dados_exportados.json" # arquivo gerado; o criar_banco.py lê ele na outra máquina

# COMO USAR: depois de mexer nos dados (notas, senhas, provas...), rode
#   python exportar_dados.py
# e commite o dados_exportados.json. Na outra máquina, ao rodar o
# criar_banco.py com o banco vazio, esses dados são aplicados no lugar
# dos dados de exemplo.

conexao = sqlite3.connect(CAMINHO_BANCO)
conexao.row_factory = sqlite3.Row # permite acessar colunas pelo nome: linha["nome"]

# Lista todas as tabelas criadas por nós (ignora as internas do SQLite, tipo sqlite_sequence)
tabelas = [linha["name"] for linha in conexao.execute(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
)]

# Monta um dicionário, cada linha vira {coluna: valor}
dados = {}
for tabela in tabelas:
    linhas = conexao.execute(f"SELECT * FROM {tabela}").fetchall()
    dados[tabela] = [dict(linha) for linha in linhas]

conexao.close()

# ensure_ascii=False mantém os acentos legíveis no arquivo (ele é salvo em UTF-8)
with open(ARQUIVO_DADOS, "w", encoding="utf-8") as arquivo:
    json.dump(dados, arquivo, ensure_ascii=False, indent=2)

total_registros = sum(len(linhas) for linhas in dados.values())
print(f"Exportados {total_registros} registros de {len(tabelas)} tabelas para {ARQUIVO_DADOS}.")
print("Agora é só commitar esse arquivo para levar os dados para outra máquina.")
