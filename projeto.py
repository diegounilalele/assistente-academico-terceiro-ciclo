from flask import Flask, request, jsonify, send_from_directory,session # comunicação com o front-end
from dotenv import load_dotenv # Esconder a api
from pyngrok import ngrok # Usado para expor o servidor Flask na internet via túnel ngrok
import sqlite3 # banco de dados
import requests # Usado para fazer requisições HTTP à API do Ollama
import re
import json
import os

load_dotenv() # carrega as variáveis do .env

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434") # URL do Ollama, local por padrão ou na nuvem via ngrok pelo .env
OLLAMA_MODEL = os.getenv('OLLAMA_MODEL', 'qwen3.5:9b') # Modelo do Ollama a ser usado, pode ser alterado no .env
NGROK_TOKEN = os.getenv("ngrok_token", "") # Token do ngrok, necessário para URL fixa (opcional no plano gratuito)

servidor = Flask(__name__)
servidor.secret_key = os.getenv("SEGREDOSEGREDO","bologna")


aluno_id = 1 # É só colocar input que é possível a busca dos dados por ID

LIMITE_CARACTERES_PERGUNTA = 500 # Limite de caracteres para a pergunta do aluno, evitando abusos

# Palavras-chave acadêmicas para verificar se a pergunta é relevante antes de chamar a IA, economizando tokens
PALAVRAS_ACADEMICAS = [
    "nota", "média", "falta", "prova", "matéria", "disciplina", "aprovado",
    "reprovado", "frequência", "aula", "semestre", "resultado", "desempenho",
    "preciso", "tirar", "passar", "boletim", "calendário", "conteúdo", "estudo",
    "quanto", "quando", "qual", "quais", "como", "me", "minha", "meu", "tenho"
]


# banco de dados

# Função para a API buscar os dados no banco

def buscar_dados_aluno(aluno_id):
    conexao = sqlite3.connect("universidade.db") # Conexão com o sql
    cursor = conexao.cursor() # Serve para executar os comandos sql

    cursor.execute("SELECT nome FROM alunos WHERE id = ?", (aluno_id,)) # consulta sql, esta consultando o nome de acordo com id
    aluno = cursor.fetchone() # Busca e retorna o primeiro resultado da consulta SQL em uma tupla

    if not aluno:
        conexao.close() # Se não tiver nada na variável 'aluno', fecha a conexão do sql e retorna nulo
        return None

    cursor.execute("SELECT materia, nota FROM notas WHERE aluno_id = ?", (aluno_id,)) # Faz uma consulta na colunas do SELECT na tabela notas de acordo com o id
    notas = cursor.fetchall() # Busca e retorna todos os resultados da consulta SQL em uma lista de tuplas

    cursor.execute("SELECT materia, faltas, total_aulas FROM faltas WHERE aluno_id = ?", (aluno_id,)) # Consulta das colunas do SELECT na tabela faltas de acordo com id
    registros_faltas = cursor.fetchall() # Busca e retorna todos os resultados da consulta SQL em uma lista de tuplas

    cursor.execute("SELECT materia, data, conteudo FROM provas WHERE aluno_id = ?", (aluno_id,)) # Faz uma consulta no banco nas colunas do SELECT na tabela provas de acordo com o id
    provas = cursor.fetchall() # Busca e retorna todos os resultados da consulta SQL em uma lista de tuplas

    conexao.close() # Fecha a conexão para não usar recursos atoa

    # Calcula média por matéria (Cálculo feito no python para evitar erros)
    medias = {} # dicionário para armazenar as médias por matéria
    for materia, nota in notas: # para cada matéria e nota na lista de notas
        if materia not in medias: # se a matéria ainda não estiver no dicionário de médias, cria uma nova entrada com uma lista vazia
            medias[materia] = []
        medias[materia].append(nota) # adiciona a nota à lista de notas da matéria correspondente

    medias_calculadas = {
        materia: sum(lista_notas) / len(lista_notas) # calcula a média
        for materia, lista_notas in medias.items() # para cada matéria e lista de notas no dicionário de médias
    }

    # Calcula situação de faltas por matéria
    faltas_calculadas = {} # dicionário para armazenar a situação de faltas por matéria
    for materia, f, total in registros_faltas: # para cada matéria, número de faltas e total de aulas na lista de faltas
        percentual = (f / total) * 100 # calcula o percentual de faltas em relação ao total de aulas
        limite = total * 0.25 # limite de faltas é 25% do total de aulas
        situacao = "Frequência OK" if f <= limite else "Reprovado por falta" # condicionais direto na váriavel para ficar mais prático
        faltas_calculadas[materia] = {
            "faltas": f, "total": total,
            "percentual": round(percentual, 2), "situacao": situacao # armazena as informações de faltas, total de aulas, percentual e situação no dicionário de faltas calculadas
        }

    # Calcula o que o aluno precisa tirar na próxima prova para passar (média mínima 6.0)
    necessario_para_passar = {}
    for materia, media_atual in medias_calculadas.items():
        qtd_notas = len(medias[materia]) # quantidade de notas já lançadas
        if media_atual < 6.0: # só calcula se o aluno ainda não atingiu a média mínima
            # fórmula: (media_minima * (qtd_notas + 1)) - soma_atual = nota necessária
            soma_atual = sum(medias[materia])
            nota_necessaria = (6.0 * (qtd_notas + 1)) - soma_atual
            nota_necessaria = min(round(nota_necessaria, 2), 10.0) # limita a 10, que é a nota máxima
            necessario_para_passar[materia] = nota_necessaria
        else:
            necessario_para_passar[materia] = "Média atingida"

    # Gera alertas automáticos de faltas para matérias próximas do limite (>= 20% de faltas)
    alertas_faltas = []
    for materia, info in faltas_calculadas.items():
        if info["situacao"] == "Reprovado por falta":
            alertas_faltas.append(f"REPROVADO POR FALTA em {materia}") # alerta crítico
        elif info["percentual"] >= 20.0: # avisa quando está perto do limite de 25%
            alertas_faltas.append(f"ATENÇÃO: {materia} com {info['percentual']}% de faltas (limite: 25%)")

    return {
        "nome": aluno[0],
        "medias": medias_calculadas,
        "faltas": faltas_calculadas,
        "provas": [
            {"materia": materia, "data": data, "conteudo": conteudo}
            for materia, data, conteudo in provas
        ],
        "necessario_para_passar": necessario_para_passar, # nota necessária para passar em cada matéria
        "alertas_faltas": alertas_faltas # alertas de faltas próximas ou acima do limite
    }


# Verifica se a pergunta tem relação com o ambiente acadêmico antes de chamar a IA
def pergunta_e_academica(pergunta):
    pergunta_lower = pergunta.lower()
    return any(palavra in pergunta_lower for palavra in PALAVRAS_ACADEMICAS) # retorna True se qualquer palavra acadêmica for encontrada na pergunta


# api

# Histórico de conversa da sessão atual, armazenado em memória (resetado ao reiniciar o servidor)
historico_conversa = []

def condicionais(pergunta):
    global historico_conversa

    # Validação: pergunta vazia
    if not pergunta or not pergunta.strip():
        return {"tipo": "resposta", "texto": "Por favor, digite uma pergunta."}

    # Validação: limite de caracteres
    if len(pergunta) > LIMITE_CARACTERES_PERGUNTA:
        return {"tipo": "resposta", "texto": f"Pergunta muito longa. O limite é {LIMITE_CARACTERES_PERGUNTA} caracteres."}

    # Validação: pergunta fora do escopo acadêmico (economiza tokens não chamando a IA)
    if not pergunta_e_academica(pergunta):
        return {"tipo": "resposta", "texto": "Só consigo responder perguntas relacionadas ao seu desempenho acadêmico."}

    dados = buscar_dados_aluno(aluno_id) # Busca os dados do aluno usando a função buscar_dados_aluno e o ID do aluno definido anteriormente

    if not dados: # Se a função buscar_dados_aluno retornar None, ou seja, se o aluno não for encontrado, retorna um JSON indicando que o aluno não foi encontrado
        return {"tipo": "resposta", "texto": "Aluno não encontrado."}

    # Adiciona a pergunta atual ao histórico no formato do Ollama
    historico_conversa.append({"role": "user", "content": pergunta})

    # Limita o histórico às últimas 10 mensagens para não estourar o contexto
    if len(historico_conversa) > 10:
        historico_conversa = historico_conversa[-10:]

    # Monta os alertas para incluir no prompt, se houver
    alertas_texto = ""
    if dados["alertas_faltas"]:
        alertas_texto = f"\nAlertas de faltas: {json.dumps(dados['alertas_faltas'], ensure_ascii=False)}"

    sabio = f"""
Você é um assistente especialista em tecnologia. Responda qualquer pergunta sobre tecnologia de forma clara e direta.

Você domina todos os assuntos de tecnologia, incluindo:
Programação (Python, JavaScript, C, Java, SQL, e qualquer outra linguagem)
Banco de dados, APIs, servidores e redes
Inteligência artificial e machine learning
Hardware, sistemas operacionais e segurança
Desenvolvimento web, mobile e desktop
DevOps, cloud e ferramentas de desenvolvimento
Qualquer outro assunto relacionado a tecnologia

Dados acadêmicos do aluno {dados['nome']} nesta instituição:
Médias por matéria: {json.dumps(dados['medias'], ensure_ascii=False)}
Faltas: {json.dumps(dados['faltas'], ensure_ascii=False)}
Provas agendadas: {json.dumps(dados['provas'], ensure_ascii=False)}
Nota necessária para passar por matéria: {json.dumps(dados['necessario_para_passar'], ensure_ascii=False)}
{alertas_texto}

Histórico recente da conversa: {json.dumps(historico_conversa[:-1], ensure_ascii=False)}

Pergunta do aluno: "{pergunta}"

Responda SOMENTE com um JSON válido, sem texto extra:
{{"tipo": "resposta", "texto": "<sua resposta aqui>"}}
Caso não for um json válido, responda:
{{"tipo": "resposta", "texto": "Desculpe, não consigo responder essa pergunta."}}

Importante:
Para perguntas sobre notas, faltas ou provas use os dados acadêmicos acima.
Para perguntas de tecnologia, responda de forma técnica e didática.
Nunca invente dados acadêmicos que não estejam listados acima.
Se houver alertas de faltas, mencione-os quando relevante.
"""
    try:
        resposta = requests.post(
    f"{OLLAMA_URL}/api/chat",
    json={
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": sabio}, # envia o prompt com os dados do aluno como system prompt
            *historico_conversa # expande o histórico de mensagens do usuário e da IA
        ],
        "stream": False
    },
    timeout=60
        )
        resposta.raise_for_status() # Lança exceção se o status HTTP for de erro (4xx ou 5xx)
        texto = resposta.json()["message"]["content"].strip()
        texto = re.sub(r"```json|```", "", texto).strip() # Regex para não impedir o json.loads de funcionar caso o modelo coloque o json dentro de blocos de código
        resultado = json.loads(texto)

        # Adiciona a resposta da IA ao histórico no formato do Ollama
        historico_conversa.append({"role": "assistant", "content": resultado.get("texto", "")})

        return resultado

    except requests.exceptions.ConnectionError:
        return {"tipo": "resposta", "texto": "Não foi possível conectar ao Ollama. Verifique se ele está rodando e se a URL está correta no .env."} # Erro de conexão com o Ollama
    except requests.exceptions.Timeout:
        return {"tipo": "resposta", "texto": "O Ollama demorou demais para responder. Tente novamente."} # Timeout na requisição
    except Exception as e:
        return {"tipo": "resposta", "texto": f"Erro ao consultar IA: {str(e)}"} # Em caso de erro na consulta à IA, retorna um JSON indicando o erro ocorrido


# rotas do flask para servir o html e receber as perguntas do frontend

@servidor.route("/")
def index():
    return send_from_directory(".", "index.html")


@servidor.route("/perguntar", methods=["POST"])
def perguntar():
    dados = request.get_json() # Recebe a pergunta do frontend em formato JSON e armazena na variável 'dados'
    pergunta = dados.get("pergunta", "") # Extrai a pergunta do JSON recebido, usando o método get para evitar erros caso a chave "pergunta" não exista, e armazena na variável 'pergunta'
    return jsonify(condicionais(pergunta)) # Retorna para o código principal a pergunta em json

#------------------------------------------------------------
@servidor.route("/login", methods=["POST"])
def login():
    dados = request.get_json()
    username = dados.get("username") #direto do universidade.db
    senha = dados.get("senha")

    #conectar ao universidade.db
    conexao = sqlite3.connect("universidade.db")
    cursor = conexao.cursor()

    #Buscar o usuario correspondente
    cursor.execute("""
	SELECT id, tipo
	FROM usuarios
	WHERE username = ? AND senha = ?
    """, (username, senha))

    usuario = cursor.fetchone()
    conexao.close()

    #Valida o resultado
    if usuario:
        # Se achou, 'usuario' será uma tupla como (1, 'professor')
        session["usuario_id"] = usuario[0]
        session["usuario_tipo"] = usuario[1]
        
        return jsonify({"status": "sucesso", "tipo": usuario[1], "mensagem": "Login realizado!"})
    else:
        return jsonify({"status": "erro", "mensagem": "Usuário ou senha incorretos."}), 401 #não autorizado
#-------------------------------------------------------------
#1------------------------------------------------------------
@servidor.route("/cadastrar_nota", methods=["POST"])
def cadastrar_nota():
    # se for diferente de professor, não pode (padrao json, estilo api do ollama)
    if session.get("usuario_tipo") != "professor":
        return jsonify({"status": "erro", "mensagem": "Acesso negado. Apenas professores podem cadastrar notas."}), 403 #

    dados = request.get_json()            #direto do arquivo .db
    aluno_id_gamer = dados.get("aluno_id")
    materia = dados.get("materia")
    nota = dados.get("nota")

    #validação
    if not aluno_id_gamer or not materia or nota is None:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos."}), 400

    # Abre sessão
    conexao = sqlite3.connect("universidade.db")
    cursor = conexao.cursor()
    
    cursor.execute("INSERT INTO notas (aluno_id, materia, nota) VALUES (?, ?, ?)", (aluno_id_gamer, materia, nota))
    
    conexao.commit() # Salva no universidade.db
    conexao.close() # Encerra sessão

    return jsonify({"status": "sucesso", "mensagem": f"Nota cadastrada com sucesso para o aluno ID {aluno_id_gamer}!"})# para o html, não é print, é return (demorei pra descobrir)
#1-------------------------------------------------------------
#2-------------------------------------------------------------
@servidor.route("/cadastrar_aluno", methods=["POST"])
def cadastrar_aluno():
    #barreira de segurança específico
    if session.get("usuario_tipo") != "professor":
        return jsonify({"status": "erro", "mensagem": "Acesso negado."}), 403 #forbidden

    dados = request.get_json()
    novo_id = dados.get("id") #pego do universidade.db
    novo_nome = dados.get("nome")

    if not novo_id or not novo_nome:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos."}), 400

    conexao = sqlite3.connect("universidade.db")
    cursor = conexao.cursor()

    try:
        # Insere permanentemente na tabela alunos do universidade.db
        cursor.execute("INSERT INTO alunos (id, nome) VALUES (?, ?)", (novo_id, novo_nome))
        conexao.commit() # é aqui que grava
        return jsonify({"status": "sucesso", "mensagem": f"Aluno {novo_nome} cadastrado com sucesso!"})
    except sqlite3.IntegrityError:
        # Se tentar cadastrar um id que já existe
        return jsonify({"status": "erro", "mensagem": f"Erro: O ID {novo_id} já está em uso por outro aluno."})
    finally: #enfim
        conexao.close()
#2-------------------------------------------------------------
#3-------------------------------------------------------------
@servidor.route("/atualizar_aluno", methods=["POST"])
def atualizar_aluno():
    if session.get("usuario_tipo") != "professor": return jsonify({"status": "erro"}), 403
    
    dados = request.get_json()
    aluno_id = dados.get("id")
    novo_nome = dados.get("nome")

    conexao = sqlite3.connect("universidade.db")
    cursor = conexao.cursor()
    cursor.execute("UPDATE alunos SET nome = ? WHERE id = ?", (novo_nome, aluno_id)) # parte mais importante do def
    conexao.commit()
    conexao.close()
    return jsonify({"status": "sucesso", "mensagem": "Nome do aluno atualizado!"})
#3--------------------------------------------------------------
#4--------------------------------------------------------------
@servidor.route("/deletar_aluno", methods=["POST"])
def deletar_aluno():
    if session.get("usuario_tipo") != "professor": return jsonify({"status": "erro"}), 403
    
    dados = request.get_json()
    aluno_id = dados.get("id")

    conexao = sqlite3.connect("universidade.db")
    cursor = conexao.cursor()
    
    # pragma é um negócio interessante, é = CASCADE que é = a deletar tudo sobre o aluno
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("DELETE FROM alunos WHERE id = ?", (aluno_id,))
    
    conexao.commit()
    conexao.close()
    return jsonify({"status": "sucesso", "mensagem": "Aluno e todos os seus registros acadêmicos foram apagados!"})
#4-------------------------------------------------------------
#5------------------------------------------------------------- 
@servidor.route("/relatorio_geral", methods=["POST"])
def relatorio_geral():
    # clássica trava de segurança
    if session.get("usuario_tipo") != "professor": 
        return jsonify({"status": "erro", "mensagem": "Acesso negado."}), 403

    conexao = sqlite3.connect("universidade.db")
    cursor = conexao.cursor()

    # Puxa todos os alunos
    cursor.execute("SELECT id, nome FROM alunos ORDER BY id")
    alunos = cursor.fetchall()

    if not alunos:
        conexao.close()
        return jsonify({"status": "sucesso", "relatorio": "Nenhum aluno cadastrado no sistema."})

    texto_sigma = "=== RELATÓRIO GERAL DA UNIVERSIDADE ===\n\n"

    # Para cada aluno
    for id_aluno, nome in alunos:
        texto_sigma += f"🎓 MATRÍCULA [{id_aluno}] - {nome.upper()}\n" #soubesse que dava pra coloca emoji
        
        # Busca as notas desse aluno específico
        cursor.execute("SELECT materia, nota FROM notas WHERE aluno_id = ?", (id_aluno,))
        notas = cursor.fetchall()
        
        if notas:
            texto_sigma += " 📄 Notas:\n"
            for materia, nota in notas:
                texto_sigma += f"     - {materia}: {nota}\n"
        else:
            texto_sigma += "  📄 Notas: (Nenhuma nota lançada)\n"

        # Busca as faltas desse aluno
        cursor.execute("SELECT materia, faltas FROM faltas WHERE aluno_id = ?", (id_aluno,))
        faltas = cursor.fetchall()
        
        if faltas:
            texto_sigma += "  ⚠️ Faltas:\n"
            for materia, falta in faltas:
                texto_sigma += f"     - {materia}: {falta} faltas\n"

        texto_sigma += "---------------------------------------\n"

    conexao.close()
    
    # Devolve o dossiê completo para o JavaScript
    return jsonify({"status": "sucesso", "relatorio": texto_sigma})
#5------------------------------------------------------------------- fim?
#6------------------------------------------------------------------- nao
@servidor.route("/cadastrar_falta", methods=["POST"])
def cadastrar_falta():
    if session.get("usuario_tipo") != "professor":
        return jsonify({"status": "erro", "mensagem": "Acesso negado."}), 403

    dados = request.get_json()           #preciso dizer que é pego do .db?
    aluno_id = dados.get("aluno_id")
    materia = dados.get("materia")
    faltas = dados.get("faltas")
    total_aulas = dados.get("total_aulas")

    if not aluno_id or not materia or faltas is None or not total_aulas: #vai que...
        return jsonify({"status": "erro", "mensagem": "Dados incompletos. Informe ID, matéria, faltas e total de aulas."}), 400

    conexao = sqlite3.connect("universidade.db")
    cursor = conexao.cursor()

    try:
        # Insere o registro de faltas na gaveta correta
        cursor.execute(
            "INSERT INTO faltas (aluno_id, materia, faltas, total_aulas) VALUES (?, ?, ?, ?)", 
            (aluno_id, materia, faltas, total_aulas)
        )
        conexao.commit() #cadastrar info:
        return jsonify({"status": "sucesso", "mensagem": f"Faltas cadastradas com sucesso para o aluno {aluno_id} em {materia}!"})
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": f"Erro ao cadastrar falta: {str(e)}"}), 500
    finally:
        conexao.close()
#6-------------------------------------------------------------------
#7-------------------------------------------------------------------
@servidor.route("/logout", methods=["POST"])
def logout():
    # session.clear() apaga os cookies do login do navegador
    session.clear()
    return jsonify({"status": "sucesso", "mensagem": "Você saiu do modo professor e o sistema foi bloqueado novamente."})
#7-------------------------------------------------------------------

# Rota que expõe os dados do aluno ao frontend (HTML)
@servidor.route("/dados_aluno", methods=["GET"])
def dados_aluno_route():
    dados = buscar_dados_aluno(aluno_id)
    if not dados:
        return jsonify({"status": "erro", "mensagem": "Aluno não encontrado."}), 404

    # Busca também as notas individuais para exibir no Desempenho
    conexao = sqlite3.connect("universidade.db")
    cursor = conexao.cursor()
    cursor.execute(
        "SELECT materia, nota FROM notas WHERE aluno_id = ? ORDER BY materia, id",
        (aluno_id,)
    )
    notas_raw = cursor.fetchall()
    conexao.close()

    notas_por_materia = {}
    for materia, nota in notas_raw:
        notas_por_materia.setdefault(materia, []).append(nota)

    return jsonify({
        "status": "sucesso",
        "nome": dados["nome"],
        "medias": dados["medias"],
        "faltas": dados["faltas"],
        "provas": dados["provas"],
        "necessario_para_passar": dados["necessario_para_passar"],
        "alertas_faltas": dados["alertas_faltas"],
        "notas_por_materia": notas_por_materia
    })


# Rota para resetar o histórico de conversa da sessão
@servidor.route("/resetar", methods=["POST"])
def resetar():
    global historico_conversa
    historico_conversa = [] # Limpa o histórico de conversa
    return jsonify({"status": "ok", "mensagem": "Histórico resetado."})


if __name__ == "__main__":
    usar_ngrok = os.getenv("USAR_NGROK", "false").lower() == "true"

    if usar_ngrok:
        if NGROK_TOKEN:
            ngrok.set_auth_token(NGROK_TOKEN)
        try:
            ngrok.kill() # Fecha túneis anteriores antes de abrir um novo
            tunnel = ngrok.connect(5000)
            print(f"\nURL pública (ngrok): {tunnel.public_url}\n")
        except Exception as e:
            print(f"\nAviso: ngrok falhou ({e}). Rodando só local.\n")
    else:
        print("\nServidor local: http://localhost:5000\n")

    servidor.run(debug=True, use_reloader=False)