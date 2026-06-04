from flask import Flask, request, jsonify, send_from_directory, session  # comunicação com o front-end
from werkzeug.security import check_password_hash                        # conferir senha com hash (vem junto do Flask)
from dotenv import load_dotenv                                           # esconder a api / configs no .env
from pyngrok import ngrok                                                # expor o servidor na internet (opcional)
from contextlib import contextmanager                                    # criar o gerenciador de conexão "with"
from functools import wraps                                              # preservar o nome das funções nos decorators
import sqlite3   # banco de dados
import requests  # requisições HTTP à API do Ollama
import re
import json
import os

load_dotenv()  # carrega as variáveis do .env


OLLAMA_URL   = os.getenv("OLLAMA_URL", "http://localhost:11434") # URL do Ollama (local por padrão)
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen3.5:9b") # modelo do Ollama
NGROK_TOKEN  = os.getenv("ngrok_token", "") # token do ngrok (opcional)
CAMINHO_BANCO = "universidade.db" # nome do arquivo do banco em um só lugar
LIMITE_CARACTERES_PERGUNTA = 500 # tamanho máximo da pergunta
ALUNO_PADRAO = 1 # aluno usado em modo demonstração

servidor = Flask(__name__)
servidor.secret_key = os.getenv("SEGREDOSEGREDO", "bologna") # chave que assina os cookies de sessão

# Palavras-chave acadêmicas: filtram perguntas fora do tema antes de gastar tokens com a IA
PALAVRAS_ACADEMICAS = [
    "nota", "média", "falta", "prova", "matéria", "disciplina", "aprovado",
    "reprovado", "frequência", "aula", "semestre", "resultado", "desempenho",
    "preciso", "tirar", "passar", "boletim", "calendário", "conteúdo", "estudo",
    "quanto", "quando", "qual", "quais", "como", "me", "minha", "meu", "tenho"
]



@contextmanager
def conectar_db():
    conexao = sqlite3.connect(CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row # permite acessar colunas pelo nome: linha["nome"]
    conexao.execute("PRAGMA foreign_keys = ON;")  # liga o ON DELETE CASCADE
    try:
        yield conexao
        conexao.commit() # se chegou aqui sem erro, grava as alterações
    finally:
        conexao.close() # fecha a conexão de qualquer jeito




def login_obrigatorio(rota):
    @wraps(rota)
    def protegida(*args, **kwargs):
        if not session.get("usuario_tipo"):
            return jsonify({"status": "erro", "mensagem": "Faça login para continuar."}), 401
        return rota(*args, **kwargs)
    return protegida


def apenas_professor(rota):
    """Decorator: libera a rota só para quem está logado como professor."""
    @wraps(rota)
    def protegida(*args, **kwargs):
        if session.get("usuario_tipo") != "professor":
            return jsonify({"status": "erro", "mensagem": "Acesso negado. Apenas professores."}), 403
        return rota(*args, **kwargs)
    return protegida


def aluno_atual():
    if session.get("aluno_id"):
        return session["aluno_id"]
    if session.get("usuario_tipo") == "professor":
        return request.args.get("aluno_id", ALUNO_PADRAO, type=int)
    return None


def buscar_dados_aluno(id_aluno):
    """Lê tudo do aluno no banco e devolve já com médias, situação de faltas e cálculos prontos."""
    with conectar_db() as conexao:
        cursor = conexao.cursor()

        cursor.execute("SELECT nome FROM alunos WHERE id = ?", (id_aluno,))
        aluno = cursor.fetchone()
        if not aluno:
            return None  # o "with" fecha a conexão sozinho

        cursor.execute("SELECT materia, nota FROM notas WHERE aluno_id = ? ORDER BY materia, id", (id_aluno,))
        notas = cursor.fetchall()

        cursor.execute("SELECT materia, faltas, total_aulas FROM faltas WHERE aluno_id = ?", (id_aluno,))
        registros_faltas = cursor.fetchall()

        cursor.execute("SELECT materia, data, conteudo FROM provas WHERE aluno_id = ?", (id_aluno,))
        provas = cursor.fetchall()

    # Agrupa as notas por matéria (uma lista de notas para cada matéria)
    notas_por_materia = {}
    for linha in notas:
        notas_por_materia.setdefault(linha["materia"], []).append(linha["nota"])

    # Média de cada matéria (calculada no Python para evitar erros de arredondamento do SQL)
    medias_calculadas = {
        materia: sum(lista) / len(lista)
        for materia, lista in notas_por_materia.items()
    }

    # Situação de faltas: percentual e se passou ou não do limite de 25%
    faltas_calculadas = {}
    for linha in registros_faltas:
        materia, faltadas, total = linha["materia"], linha["faltas"], linha["total_aulas"]
        percentual = (faltadas / total) * 100 if total else 0
        limite = total * 0.25
        situacao = "Frequência OK" if faltadas <= limite else "Reprovado por falta"
        faltas_calculadas[materia] = {
            "faltas": faltadas, "total": total,
            "percentual": round(percentual, 2), "situacao": situacao
        }

    # Quanto o aluno ainda precisa tirar para fechar média 6.0
    necessario_para_passar = {}
    for materia, media_atual in medias_calculadas.items():
        if media_atual < 6.0:
            qtd_notas = len(notas_por_materia[materia])
            soma_atual = sum(notas_por_materia[materia])
            # (média_alvo * (qtd_notas + 1)) - soma_atual = nota necessária na próxima avaliação
            nota_necessaria = (6.0 * (qtd_notas + 1)) - soma_atual
            necessario_para_passar[materia] = min(round(nota_necessaria, 2), 10.0)
        else:
            necessario_para_passar[materia] = "Média atingida"

    # Alertas automáticos de faltas (crítico quando reprovou, atenção a partir de 20%)
    alertas_faltas = []
    for materia, info in faltas_calculadas.items():
        if info["situacao"] == "Reprovado por falta":
            alertas_faltas.append(f"REPROVADO POR FALTA em {materia}")
        elif info["percentual"] >= 20.0:
            alertas_faltas.append(f"ATENÇÃO: {materia} com {info['percentual']}% de faltas (limite: 25%)")

    return {
        "nome": aluno["nome"],
        "medias": medias_calculadas,
        "faltas": faltas_calculadas,
        "provas": [
            {"materia": p["materia"], "data": p["data"], "conteudo": p["conteudo"]}
            for p in provas
        ],
        "necessario_para_passar": necessario_para_passar,
        "alertas_faltas": alertas_faltas,
        "notas_por_materia": notas_por_materia,
    }

# Histórico separado por aluno (cada aluno tem a sua conversa em memória)
historicos = {}

def historico_do(id_aluno):
    return historicos.setdefault(id_aluno, [])


def pergunta_e_academica(pergunta):
    """True se a pergunta tiver pelo menos uma palavra-chave acadêmica."""
    pergunta_lower = pergunta.lower()
    return any(palavra in pergunta_lower for palavra in PALAVRAS_ACADEMICAS)


def condicionais(pergunta, id_aluno):
    """Valida a pergunta, monta o contexto com os dados do aluno e consulta a IA (Ollama)."""
    if not pergunta or not pergunta.strip():
        return {"tipo": "resposta", "texto": "Por favor, digite uma pergunta."}

    # Validação: limite de caracteres
    if len(pergunta) > LIMITE_CARACTERES_PERGUNTA:
        return {"tipo": "resposta", "texto": f"Pergunta muito longa. O limite é {LIMITE_CARACTERES_PERGUNTA} caracteres."}

    # Validação: pergunta fora do escopo acadêmico (economiza tokens não chamando a IA)
    if not pergunta_e_academica(pergunta):
        return {"tipo": "resposta", "texto": "Só consigo responder perguntas relacionadas ao seu desempenho acadêmico."}

    dados = buscar_dados_aluno(id_aluno)
    if not dados:
        return {"tipo": "resposta", "texto": "Aluno não encontrado."}

    historico_conversa = historico_do(id_aluno)
    historico_conversa.append({"role": "user", "content": pergunta})

    # Mantém só as últimas 10 mensagens para não estourar o contexto da IA
    if len(historico_conversa) > 10:
        del historico_conversa[:-10]

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
                    {"role": "system", "content": sabio}, # contexto com os dados do aluno
                    *historico_conversa # histórico da conversa
                ],
                "stream": False
            },
            timeout=60
        )
        resposta.raise_for_status()
        texto = resposta.json()["message"]["content"].strip()
        texto = re.sub(r"```json|```", "", texto).strip() # tira blocos de código caso o modelo use
        resultado = json.loads(texto)

        historico_conversa.append({"role": "assistant", "content": resultado.get("texto", "")})
        return resultado

    except requests.exceptions.ConnectionError:
        return {"tipo": "resposta", "texto": "Não foi possível conectar ao Ollama. Verifique se ele está rodando e se a URL está correta no .env."}
    except requests.exceptions.Timeout:
        return {"tipo": "resposta", "texto": "O Ollama demorou demais para responder. Tente novamente."}
    except Exception as e:
        return {"tipo": "resposta", "texto": f"Erro ao consultar IA: {str(e)}"}


# ───────────────────────── ROTAS: PÁGINA E SESSÃO ─────────────────────────

@servidor.route("/")
def index():
    return send_from_directory(".", "index.html")


@servidor.route("/login", methods=["POST"])
def login():
    dados = request.get_json() or {}
    username = (dados.get("username") or "").strip()
    senha = dados.get("senha") or ""

    if not username or not senha:
        return jsonify({"status": "erro", "mensagem": "Informe usuário e senha."}), 400

    with conectar_db() as conexao:
        cursor = conexao.cursor()
        cursor.execute(
            "SELECT id, senha, tipo, aluno_id FROM usuarios WHERE username = ?",
            (username,)
        )
        usuario = cursor.fetchone()

    # check_password_hash compara a senha digitada com o hash salvo (nunca guardamos a senha pura)
    if usuario and check_password_hash(usuario["senha"], senha):
        session["usuario_id"]   = usuario["id"]
        session["usuario_tipo"] = usuario["tipo"]
        session["username"]     = username
        session["aluno_id"]     = usuario["aluno_id"]
        return jsonify({
            "status": "sucesso",
            "tipo": usuario["tipo"],
            "username": username,
            "mensagem": "Login realizado!"
        })

    return jsonify({"status": "erro", "mensagem": "Usuário ou senha incorretos."}), 401


@servidor.route("/logout", methods=["POST"])
def logout():
    session.clear()  # apaga os dados de login da sessão (cookie)
    return jsonify({"status": "sucesso", "mensagem": "Você saiu do sistema."})


@servidor.route("/sessao", methods=["GET"])
def sessao():
    """O front-end usa para saber, ao abrir a página, se o usuário já está logado."""
    if session.get("usuario_tipo"):
        return jsonify({
            "logado": True,
            "tipo": session.get("usuario_tipo"),
            "username": session.get("username")
        })
    return jsonify({"logado": False})


@servidor.route("/dados_aluno", methods=["GET"])
@login_obrigatorio
def dados_aluno_route():
    """Entrega ao HTML todos os dados já calculados do aluno logado."""
    id_aluno = aluno_atual()
    if id_aluno is None:
        return jsonify({"status": "erro", "mensagem": "Sua conta não está vinculada a um aluno."}), 400

    dados = buscar_dados_aluno(id_aluno)
    if not dados:
        return jsonify({"status": "erro", "mensagem": "Aluno não encontrado."}), 404

    dados["status"] = "sucesso"
    return jsonify(dados)


@servidor.route("/perguntar", methods=["POST"])
@login_obrigatorio
def perguntar():
    dados = request.get_json() or {}
    pergunta = dados.get("pergunta", "")
    return jsonify(condicionais(pergunta, aluno_atual()))


@servidor.route("/resetar", methods=["POST"])
@login_obrigatorio
def resetar():
    """Limpa o histórico de conversa do aluno logado."""
    historicos[aluno_atual()] = []
    return jsonify({"status": "ok", "mensagem": "Histórico resetado."})


@servidor.route("/cadastrar_nota", methods=["POST"])
@apenas_professor
def cadastrar_nota():
    dados = request.get_json() or {}
    id_aluno = dados.get("aluno_id")
    materia  = dados.get("materia")
    nota     = dados.get("nota")

    if not id_aluno or not materia or nota is None:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos."}), 400

    with conectar_db() as conexao:
        conexao.execute(
            "INSERT INTO notas (aluno_id, materia, nota) VALUES (?, ?, ?)",
            (id_aluno, materia, nota)
        )
    return jsonify({"status": "sucesso", "mensagem": f"Nota cadastrada para o aluno {id_aluno}!"})


@servidor.route("/cadastrar_aluno", methods=["POST"])
@apenas_professor
def cadastrar_aluno():
    dados = request.get_json() or {}
    novo_id   = dados.get("id")
    novo_nome = dados.get("nome")

    if not novo_id or not novo_nome:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos."}), 400

    try:
        with conectar_db() as conexao:
            conexao.execute("INSERT INTO alunos (id, nome) VALUES (?, ?)", (novo_id, novo_nome))
        return jsonify({"status": "sucesso", "mensagem": f"Aluno {novo_nome} cadastrado!"})
    except sqlite3.IntegrityError:
        return jsonify({"status": "erro", "mensagem": f"O ID {novo_id} já está em uso."}), 409


@servidor.route("/atualizar_aluno", methods=["POST"])
@apenas_professor
def atualizar_aluno():
    dados = request.get_json() or {}
    id_aluno  = dados.get("id")
    novo_nome = dados.get("nome")

    if not id_aluno or not novo_nome:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos."}), 400

    with conectar_db() as conexao:
        conexao.execute("UPDATE alunos SET nome = ? WHERE id = ?", (novo_nome, id_aluno))
    return jsonify({"status": "sucesso", "mensagem": "Nome do aluno atualizado!"})


@servidor.route("/deletar_aluno", methods=["POST"])
@apenas_professor
def deletar_aluno():
    dados = request.get_json() or {}
    id_aluno = dados.get("id")

    if not id_aluno:
        return jsonify({"status": "erro", "mensagem": "Informe o ID do aluno."}), 400

    # Com PRAGMA foreign_keys = ON (ligado no conectar_db), apagar o aluno apaga
    # em cascata as notas, faltas e provas dele.
    with conectar_db() as conexao:
        conexao.execute("DELETE FROM alunos WHERE id = ?", (id_aluno,))
    return jsonify({"status": "sucesso", "mensagem": "Aluno e seus registros foram apagados!"})


@servidor.route("/cadastrar_falta", methods=["POST"])
@apenas_professor
def cadastrar_falta():
    dados = request.get_json() or {}
    id_aluno = dados.get("aluno_id")
    materia = dados.get("materia")
    faltas = dados.get("faltas")
    total_aulas = dados.get("total_aulas")

    if not id_aluno or not materia or faltas is None or not total_aulas:
        return jsonify({"status": "erro", "mensagem": "Dados incompletos. Informe ID, matéria, faltas e total de aulas."}), 400

    try:
        with conectar_db() as conexao:
            conexao.execute(
                "INSERT INTO faltas (aluno_id, materia, faltas, total_aulas) VALUES (?, ?, ?, ?)",
                (id_aluno, materia, faltas, total_aulas)
            )
        return jsonify({"status": "sucesso", "mensagem": f"Faltas cadastradas para o aluno {id_aluno} em {materia}!"})
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": f"Erro ao cadastrar falta: {str(e)}"}), 500


@servidor.route("/relatorio_geral", methods=["POST"])
@apenas_professor
def relatorio_geral():
    with conectar_db() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT id, nome FROM alunos ORDER BY id")
        alunos = cursor.fetchall()

        if not alunos:
            return jsonify({"status": "sucesso", "relatorio": "Nenhum aluno cadastrado no sistema."})

        texto = "=== RELATORIO GERAL DA UNIVERSIDADE ===\n\n"
        for aluno in alunos:
            id_aluno, nome = aluno["id"], aluno["nome"]
            texto += f"MATRICULA [{id_aluno}] - {nome.upper()}\n"

            cursor.execute("SELECT materia, nota FROM notas WHERE aluno_id = ?", (id_aluno,))
            notas = cursor.fetchall()
            if notas:
                texto += "  Notas:\n"
                for n in notas:
                    texto += f"     - {n['materia']}: {n['nota']}\n"
            else:
                texto += "  Notas: (Nenhuma nota lançada)\n"

            cursor.execute("SELECT materia, faltas FROM faltas WHERE aluno_id = ?", (id_aluno,))
            faltas = cursor.fetchall()
            if faltas:
                texto += "  Faltas:\n"
                for fa in faltas:
                    texto += f"     - {fa['materia']}: {fa['faltas']} faltas\n"

            texto += "---------------------------------------\n"

    return jsonify({"status": "sucesso", "relatorio": texto})


@servidor.route("/todos_alunos", methods=["GET"])
@apenas_professor
def todos_alunos():
    """Painel do professor: devolve todos os alunos já com média geral, frequência e situação calculadas."""
    with conectar_db() as conexao:
        cursor = conexao.cursor()
        cursor.execute("SELECT id, nome FROM alunos ORDER BY nome")
        lista = cursor.fetchall()

    alunos = []
    for registro in lista:
        # Reaproveita o mesmo cálculo usado na tela do aluno (médias, faltas, situação)
        dados = buscar_dados_aluno(registro["id"])
        if not dados:
            continue

        medias = list(dados["medias"].values())
        media_geral = round(sum(medias) / len(medias), 1) if medias else 0

        total_faltas = sum(f["faltas"] for f in dados["faltas"].values())
        total_aulas  = sum(f["total"]  for f in dados["faltas"].values())
        freq_geral = round((total_aulas - total_faltas) / total_aulas * 100) if total_aulas else 0

        # Uma disciplina entra "em risco" se a média ficou abaixo de 6 ou se reprovou por falta
        em_risco = {m for m, media in dados["medias"].items() if media < 6.0}
        em_risco |= {m for m, f in dados["faltas"].items() if f["situacao"] == "Reprovado por falta"}

        alunos.append({
            "id": registro["id"],
            "nome": dados["nome"],
            "media_geral": media_geral,
            "frequencia_geral": freq_geral,
            "total_disciplinas": len(dados["medias"]),
            "em_risco": sorted(em_risco),
            "medias": dados["medias"],
            "faltas": dados["faltas"],
        })

    total = len(alunos)
    resumo = {
        "total_alunos": total,
        "media_turma": round(sum(a["media_geral"] for a in alunos) / total, 1) if total else 0,
        "frequencia_media": round(sum(a["frequencia_geral"] for a in alunos) / total) if total else 0,
        "alunos_em_risco": sum(1 for a in alunos if a["em_risco"]),
    }

    return jsonify({"status": "sucesso", "alunos": alunos, "resumo": resumo})


# ───────────────────────── INICIALIZAÇÃO ─────────────────────────

if __name__ == "__main__":
    usar_ngrok = os.getenv("USAR_NGROK", "false").lower() == "true"

    if usar_ngrok:
        if NGROK_TOKEN:
            ngrok.set_auth_token(NGROK_TOKEN)
        try:
            ngrok.kill()  # fecha túneis abertos numa execução anterior
            tunnel = ngrok.connect(5000)
            print(f"\nURL pública (ngrok): {tunnel.public_url}\n")
        except Exception as e:
            print(f"\nAviso: ngrok falhou ({e}). Rodando só local.\n")
    else:
        print("\nServidor local: http://localhost:5000\n")

    servidor.run(debug=True, use_reloader=False)
